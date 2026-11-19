"""Break the real stack on purpose and check it degrades the way the design says.

Slow, and it changes your stack for a few minutes:  pytest -m chaos -s
Needs SSH access to the weather instance (the .pem file in the lab folder, and the lab02 SSH rule).
"""
from datetime import datetime, timezone
import time
import pytest
from tests.helpers import get_json, instance_ip, probe, ssh, tier_url, wait_until
from tests.conftest import ROOT

pytestmark = pytest.mark.chaos

RECOVERY_LIMIT_SECONDS = 300
DB_PAUSE_SECONDS = 35        # the weather service leaves a failed database alone for 30 seconds

def _today_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")

def test_forcing_gemini_daily_cap_triggers_fallback(aws, settings, outputs):
    """Set today's DynamoDB Gemini counter to the cap limit and verify fallback advice is served."""
    advisor_url = tier_url(outputs, settings, "advisor").rstrip("/")
    assert probe(f"{advisor_url}/health"), "the advisor service must be healthy first"

    today = _today_str()
    table_name = getattr(settings, "advisor_table_name", "LookupsCounter")
    cap_limit = int(getattr(settings, "daily_gemini_cap", 100))
    cap_key = {"PK": {"S": f"DAILY_CAP#{today}"}}

    # Read the current counter so we can restore it afterward
    existing = aws.dynamodb.get_item(TableName=table_name, Key=cap_key).get("Item")
    original_count = existing["call_count"]["N"] if existing and "call_count" in existing else None

    ttl = str(int(time.time()) + 86400)
    try:
        # Force the counter to the cap limit so the next call exceeds it
        aws.dynamodb.put_item(
            TableName=table_name,
            Item={
                "PK": {"S": f"DAILY_CAP#{today}"},
                "call_count": {"N": str(cap_limit)},
                "expires_at": {"N": ttl},
            },
        )

        # Query an uncached ZIP/gender combination so it bypasses the report cache and hits the cap check
        query = f"?zip=99501&date={today}&gender=womenswear&email=student@hawk.illinoistech.edu"
        status, body = get_json(f"{advisor_url}/advice{query}", timeout=25)
        assert status == 200, f"expected 200 with fallback advice, got {status}: {body}"
        assert body.get("source") == "fallback_cap_exceeded", f"expected fallback_cap_exceeded, got {body}"
        assert "morning" in body and "night" in body
        assert body["morning"].get("suggestedDressing")
    finally:
        # Restore the original Gemini call count so subsequent tests are unaffected
        if original_count is not None:
            aws.dynamodb.put_item(
                TableName=table_name,
                Item={
                    "PK": {"S": f"DAILY_CAP#{today}"},
                    "call_count": {"N": original_count},
                    "expires_at": {"N": ttl},
                },
            )
        else:
            aws.dynamodb.delete_item(TableName=table_name, Key=cap_key)

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
    assert probe(f"{weather_url}/health") and probe(f"{advisor_url}/health"), "both tiers must be healthy first"

    victim = _in_service_instance(aws, settings.weather.asg_name)
    assert victim, f"no in-service instance in {settings.weather.asg_name}"
    aws.autoscaling.terminate_instance_in_auto_scaling_group(InstanceId=victim, ShouldDecrementDesiredCapacity=False)
    started = time.time()

    today = _today_str()
    uncached_zips = ["85001", "80202", "97201", "55401", "27601", "37201", "84101", "73102"]
    statuses, slowest = [], 0.0
    idx = 0
    while time.time() - started < 60:
        began = time.time()
        z = uncached_zips[idx % len(uncached_zips)]
        idx += 1
        query = f"?zip={z}&date={today}&gender=neutral&email=student@hawk.illinoistech.edu"
        status, body = get_json(f"{advisor_url}/advice{query}", timeout=30)
        slowest = max(slowest, time.time() - began)
        statuses.append(status)
        if status == 502:
            assert body.get("error") == "weather_service_unavailable"
            break
        time.sleep(2)

    assert 502 in statuses, f"the advisor never reported the outage: {statuses}"
    assert slowest < 30, f"the advisor hung for {slowest:.0f}s instead of failing fast"
    assert probe(f"{advisor_url}/"), "the advisor home page must stay up during the outage"

    valid_weather_query = f"/weather?zip=60616&date={today}"
    recovered = wait_until(lambda: probe(f"{weather_url}{valid_weather_query}", timeout=5),
                           timeout=RECOVERY_LIMIT_SECONDS, interval=10)
    elapsed = time.time() - started
    print(f"\nweather: terminated {victim}, back after {elapsed:.0f}s (limit {RECOVERY_LIMIT_SECONDS}s)")
    assert recovered, f"the weather service did not answer 200 within {RECOVERY_LIMIT_SECONDS}s"

    status, body = get_json(f"{weather_url}{valid_weather_query}")
    assert status == 200 and body["cache"] in ("hit", "miss")
