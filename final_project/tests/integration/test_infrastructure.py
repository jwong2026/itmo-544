"""
Does the stack you deployed look the way the design says it should?
Run after create_database.py and create_weather_stack.py: pytest -m integration
"""
import socket
import pytest
import requests
from tests.helpers import instance_ip, wait_until

pytestmark = pytest.mark.integration

def test_both_target_groups_become_healthy(aws, settings, outputs):
    def all_healthy():
        for tier in settings.tiers:
            targets = aws.elbv2.describe_target_health(
                TargetGroupArn=outputs.tg_arn(tier.name))["TargetHealthDescriptions"]
            if not targets or any(t["TargetHealth"]["State"] != "healthy" for t in targets):
                return False
        return True
    assert wait_until(all_healthy, timeout=420, interval=15), "targets never became healthy (first boot installs Node, psql and the app)"

def test_load_balancer_is_public_and_spans_two_azs(aws, settings, outputs):
    lb = aws.elbv2.describe_load_balancers(LoadBalancerArns=[outputs.alb_arn])["LoadBalancers"][0]
    assert lb["State"]["Code"] == "active" and lb["Scheme"] == "internet-facing"
    assert {az["ZoneName"] for az in lb["AvailabilityZones"]} == {settings.az_a, settings.az_b}

def test_listeners_forward_to_the_right_target_groups(aws, settings, outputs):
    listeners = aws.elbv2.describe_listeners(LoadBalancerArn=outputs.alb_arn)["Listeners"]
    forwards = {item["Port"]: item["DefaultActions"][0]["TargetGroupArn"] for item in listeners}
    for tier in settings.tiers:
        assert forwards[tier.listener_port] == outputs.tg_arn(tier.name)

def test_database_is_private_encrypted_single_zone_and_has_no_backups(aws, settings):
    db = aws.rds.describe_db_instances(DBInstanceIdentifier=settings.db_instance_id)["DBInstances"][0]
    assert db["DBInstanceClass"] == "db.t4g.micro"
    assert db["PubliclyAccessible"] is False
    assert db["MultiAZ"] is False
    assert db["StorageEncrypted"] is True
    assert db["BackupRetentionPeriod"] == 0
    assert aws.rds.describe_db_snapshots(DBInstanceIdentifier=settings.db_instance_id)["DBSnapshots"] == []
    try:
        assert aws.rds.describe_db_instance_automated_backups(
            DBInstanceIdentifier=settings.db_instance_id)["DBInstanceAutomatedBackups"] == []
    except aws.rds.exceptions.DBInstanceAutomatedBackupNotFoundFault:
        # A missing record confirms automated backups are off
        pass

def test_database_port_is_not_reachable_from_your_computer(db_outputs):
    """moto cannot prove network reachability. This is the test that covers that gap."""
    with pytest.raises(OSError):
        socket.create_connection((db_outputs["DB_HOST"], 5432), timeout=6).close()

def test_app_port_is_reachable_only_from_the_load_balancer(aws, settings, outputs):
    group = aws.ec2.describe_security_groups(GroupIds=[settings.app_sg_id])["SecurityGroups"][0]
    rules = [p for p in group["IpPermissions"] if p.get("FromPort") == settings.app_port]
    assert rules, "port 3000 rule missing"
    for rule in rules:
        assert rule["IpRanges"] == [], "port 3000 must not be open to a CIDR range"
        assert [p["GroupId"] for p in rule["UserIdGroupPairs"]] == [outputs.alb_security_group_id]

@pytest.mark.parametrize("name_tag", ["weather-app", "advisor-app"])
def test_instances_cannot_be_reached_directly(aws, name_tag):
    """The rule above says it. This proves it: a direct call to the instance must time out."""
    ip = instance_ip(aws, name_tag)
    if not ip:
        pytest.skip(f"no running {name_tag} instance with a public address")
    with pytest.raises(requests.RequestException):
        requests.get(f"http://{ip}:3000/", timeout=5)

def test_database_only_accepts_the_app_security_group(aws, settings, db_outputs):
    group = aws.ec2.describe_security_groups(GroupIds=[db_outputs["DB_SECURITY_GROUP_ID"]])["SecurityGroups"][0]
    rules = [p for p in group["IpPermissions"] if p.get("FromPort") == 5432]
    assert len(rules) == 1 and rules[0]["IpRanges"] == []
    assert [p["GroupId"] for p in rules[0]["UserIdGroupPairs"]] == [settings.app_sg_id]

def _decision(aws, role_name, resource):
    role_arn = aws.iam.get_role(RoleName=role_name)["Role"]["Arn"]
    result = aws.iam.simulate_principal_policy(
        PolicySourceArn=role_arn, ActionNames=["ssm:GetParameter"], ResourceArns=[resource])
    return result["EvaluationResults"][0]["EvalDecision"]

def test_each_role_may_read_only_its_own_secret(aws, settings):
    """Ask IAM itself (the policy simulator) instead of trusting the policy text you wrote."""
    account = aws.sts.get_caller_identity()["Account"]
    db_arn = f"arn:aws:ssm:{settings.region}:{account}:parameter{settings.db_password_param}"
    gemini_arn = f"arn:aws:ssm:{settings.region}:{account}:parameter{settings.gemini_param_name}"
    assert _decision(aws, settings.weather.role_name, db_arn) == "allowed"
    assert _decision(aws, settings.weather.role_name, gemini_arn) != "allowed"
    assert _decision(aws, settings.advisor.role_name, gemini_arn) == "allowed"
    assert _decision(aws, settings.advisor.role_name, db_arn) != "allowed"
