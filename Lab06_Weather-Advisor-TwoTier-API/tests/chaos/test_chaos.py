"""Break the real stack on purpose and check it degrades the way the design says.

Slow, and it changes your stack for a few minutes:  pytest -m chaos -s
Needs SSH access to the weather instance (the .pem file in the lab folder, and the lab02 SSH rule).
"""
import time
import pytest
from tests.helpers import get_json, instance_ip, probe, ssh, tier_url, wait_until
from tests.conftest import ROOT

pytestmark = pytest.mark.chaos

RECOVERY_LIMIT_SECONDS = 300
DB_PAUSE_SECONDS = 35        # the weather service leaves a failed database alone for 30 seconds


def test_losing_the_database_does_not_cause_a_weather_outage(aws, settings, outputs, db_outputs):
    """Revoke the database rule, restart the weather service, and expect 200 with cache=unavailable."""
    if not (ROOT / f"{settings.key_name}.pem").is_file():
        pytest.skip(f"{settings.key_name}.pem not found in the lab folder")
    ip = instance_ip(aws, "weather-app")
    assert ip, "no running weather instance with a public address"
    url = tier_url(outputs, settings, "weather").rstrip("/")
    db_sg = db_outputs["DB_SECURITY_GROUP_ID"]
    rule = [{"IpProtocol": "tcp", "FromPort": 5432, "ToPort": 5432,
             "UserIdGroupPairs": [{"GroupId": settings.app_sg_id}]}]
    assert probe(f"{url}/"), "the weather service must be healthy before the experiment"

    aws.ec2.revoke_security_group_ingress(GroupId=db_sg, IpPermissions=rule)
    try:
        # Open connections are not cut when a rule is removed, so restart to force a new connection.
        restart = ssh(settings, ip, "sudo systemctl restart weather")
        assert restart.returncode == 0, restart.stderr
        time.sleep(5)

        status, body = get_json(f"{url}/weather?zip=98101")
        assert status == 200, f"a database failure became a weather outage: {status} {body}"
        assert body["cache"] == "unavailable"
        status, body = get_json(f"{url}/history")
        assert status == 503 and body["error"] == "database_unavailable"
    finally:
        aws.ec2.authorize_security_group_ingress(GroupId=db_sg, IpPermissions=rule)

    time.sleep(DB_PAUSE_SECONDS)
    status, body = get_json(f"{url}/weather?zip=98101")
    assert status == 200 and body["cache"] in ("miss", "hit"), f"the cache did not come back: {body}"

def _in_service_instance(aws, asg_name):
    group = aws.autoscaling.describe_auto_scaling_groups(AutoScalingGroupNames=[asg_name])["AutoScalingGroups"][0]
    for instance in group["Instances"]:
        if instance["LifecycleState"] == "InService":
            return instance["InstanceId"]
    return None

def test_advisor_fails_fast_when_weather_is_down_and_weather_recovers(aws, settings, outputs):
    """Terminate the weather instance. The advisor must answer 502 (not hang), and weather must return within 300 s."""
    weather_url = tier_url(outputs, settings, "weather").rstrip("/")
    advisor_url = tier_url(outputs, settings, "advisor").rstrip("/")
    assert probe(f"{weather_url}/") and probe(f"{advisor_url}/"), "both tiers must be healthy first"

    victim = _in_service_instance(aws, settings.weather.asg_name)
    assert victim, f"no in-service instance in {settings.weather.asg_name}"
    aws.autoscaling.terminate_instance_in_auto_scaling_group(InstanceId=victim, ShouldDecrementDesiredCapacity=False)
    started = time.time()

    statuses, slowest = [], 0.0
    while time.time() - started < 60:
        began = time.time()
        status, body = get_json(f"{advisor_url}/advice?zip=33101", timeout=30)
        slowest = max(slowest, time.time() - began)
        statuses.append(status)
        if status == 502:
            assert body.get("error") == "weather_service_unavailable"
            break
        time.sleep(2)
    assert 502 in statuses, f"the advisor never reported the outage: {statuses}"
    assert slowest < 30, f"the advisor hung for {slowest:.0f}s instead of failing fast"
    assert probe(f"{advisor_url}/"), "the advisor home page must stay up during the outage"

    recovered = wait_until(lambda: probe(f"{weather_url}/weather?zip=60616", timeout=5),
                           timeout=RECOVERY_LIMIT_SECONDS, interval=10)
    elapsed = time.time() - started
    print(f"\nweather: terminated {victim}, back after {elapsed:.0f}s (limit {RECOVERY_LIMIT_SECONDS}s)")
    assert recovered, f"the weather service did not answer 200 within {RECOVERY_LIMIT_SECONDS}s"

    # State lives in the database, not on the instance: the new instance can answer from the old one's data.
    status, body = get_json(f"{weather_url}/weather?zip=60616")
    assert status == 200 and body["cache"] in ("hit", "miss")
