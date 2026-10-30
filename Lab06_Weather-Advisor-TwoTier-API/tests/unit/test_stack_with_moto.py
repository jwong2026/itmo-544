"""
Run the real create and delete code against moto, an in-memory fake of AWS.
Nothing here touches your AWS account, costs money, or needs credentials.
"""
import base64
import json
import pytest
from stack.runner import create_stack, delete_stack
from stack.network import StackError


DB_HOST = "weather-db.abc123.us-east-2.rds.amazonaws.com"
DB_PASSWORD = "0123456789abcdef0123456789abcdef"   # a known value, so we can prove it never leaks
GEMINI_KEY = "AIza-not-a-real-key-for-tests"

def _no_sleep(_seconds):
    return None

@pytest.fixture
def stack_env(aws_env, tmp_path, monkeypatch):
    """The things lab 6 expects before the stack: both secrets in SSM and db_outputs.env on disk."""
    settings, aws = aws_env
    monkeypatch.chdir(tmp_path)   # db_outputs.env and stack_outputs.* live in the current folder
    aws.ssm.put_parameter(Name=settings.gemini_param_name, Type="SecureString", Value=GEMINI_KEY)
    aws.ssm.put_parameter(Name=settings.db_password_param, Type="SecureString", Value=DB_PASSWORD)
    (tmp_path / "db_outputs.env").write_text(f"DB_HOST={DB_HOST}\nDB_SECURITY_GROUP_ID=sg-db\n")
    return settings, aws

def _user_data(aws, lt_name):
    versions = aws.ec2.describe_launch_template_versions(LaunchTemplateName=lt_name)["LaunchTemplateVersions"]
    return base64.b64decode(versions[-1]["LaunchTemplateData"]["UserData"]).decode()

def _policy(aws, tier):
    return aws.iam.get_role_policy(RoleName=tier.role_name, PolicyName=tier.policy_name)["PolicyDocument"]

def test_create_builds_every_resource(stack_env):
    settings, aws = stack_env
    outputs = create_stack(settings, aws, iam_wait=0)
    for tier in settings.tiers:
        profile = aws.iam.get_instance_profile(InstanceProfileName=tier.profile_name)
        assert [r["RoleName"] for r in profile["InstanceProfile"]["Roles"]] == [tier.role_name]
        assert aws.ec2.describe_launch_templates(LaunchTemplateNames=[tier.lt_name])["LaunchTemplates"]
        group = aws.autoscaling.describe_auto_scaling_groups(AutoScalingGroupNames=[tier.asg_name])["AutoScalingGroups"][0]
        assert (group["MinSize"], group["MaxSize"], group["DesiredCapacity"]) == (1, 1, 1)
        assert group["HealthCheckType"] == "ELB"
        tg = aws.elbv2.describe_target_groups(Names=[tier.tg_name])["TargetGroups"][0]
        assert tg["HealthCheckIntervalSeconds"] == 10 and tg["UnhealthyThresholdCount"] == 2
    listeners = aws.elbv2.describe_listeners(LoadBalancerArn=outputs.alb_arn)["Listeners"]
    assert sorted(item["Port"] for item in listeners) == [8080, 8081]
    assert outputs.alb_dns_name

def test_each_role_can_read_only_its_own_secret(stack_env):
    settings, aws = stack_env
    create_stack(settings, aws, iam_wait=0)
    account = aws.sts.get_caller_identity()["Account"]
    db_arn = f"arn:aws:ssm:{settings.region}:{account}:parameter{settings.db_password_param}"
    gemini_arn = f"arn:aws:ssm:{settings.region}:{account}:parameter{settings.gemini_param_name}"

    weather, advisor = _policy(aws, settings.weather), _policy(aws, settings.advisor)
    for policy, own in ((weather, db_arn), (advisor, gemini_arn)):
        assert len(policy["Statement"]) == 1
        statement = policy["Statement"][0]
        assert statement["Effect"] == "Allow"
        assert statement["Action"] in ("ssm:GetParameter", ["ssm:GetParameter"])
        assert statement["Resource"] == own
    assert settings.gemini_param_name not in json.dumps(weather)
    assert settings.db_password_param not in json.dumps(advisor)

def test_the_alb_is_built_first_so_the_advisor_user_data_has_its_dns_name(stack_env):
    settings, aws = stack_env
    outputs = create_stack(settings, aws, iam_wait=0)
    advisor_script = _user_data(aws, settings.advisor.lt_name)
    assert f"Environment=WEATHER_URL=http://{outputs.alb_dns_name}:8080" in advisor_script

def test_weather_user_data_has_the_database_host_but_never_a_secret(stack_env):
    settings, aws = stack_env
    create_stack(settings, aws, iam_wait=0)
    weather_script = _user_data(aws, settings.weather.lt_name)
    advisor_script = _user_data(aws, settings.advisor.lt_name)
    assert f"Environment=DB_HOST={DB_HOST}" in weather_script
    for script in (weather_script, advisor_script):
        assert DB_PASSWORD not in script
        assert GEMINI_KEY not in script

def test_generated_user_data_is_under_16_kb(stack_env):
    settings, aws = stack_env
    create_stack(settings, aws, iam_wait=0)
    for tier in settings.tiers:
        assert len(_user_data(aws, tier.lt_name).encode()) < 16 * 1024

def test_app_security_group_only_accepts_the_alb(stack_env):
    settings, aws = stack_env
    outputs = create_stack(settings, aws, iam_wait=0)
    group = aws.ec2.describe_security_groups(GroupIds=[settings.app_sg_id])["SecurityGroups"][0]
    rules = [p for p in group["IpPermissions"] if p["FromPort"] == 3000]
    assert len(rules) == 1 and rules[0]["IpRanges"] == []
    assert rules[0]["UserIdGroupPairs"][0]["GroupId"] == outputs.alb_security_group_id

def test_create_twice_creates_no_duplicates(stack_env):
    settings, aws = stack_env
    first = create_stack(settings, aws, iam_wait=0)
    second = create_stack(settings, aws, iam_wait=0)
    assert first == second
    assert len(aws.elbv2.describe_load_balancers()["LoadBalancers"]) == 1
    assert len(aws.elbv2.describe_target_groups()["TargetGroups"]) == 2
    assert len(aws.elbv2.describe_listeners(LoadBalancerArn=first.alb_arn)["Listeners"]) == 2
    assert len(aws.autoscaling.describe_auto_scaling_groups()["AutoScalingGroups"]) == 2
    assert len(aws.iam.list_roles()["Roles"]) == 2
    versions = aws.ec2.describe_launch_template_versions(LaunchTemplateName=settings.weather.lt_name)["LaunchTemplateVersions"]
    assert len(versions) == 2, "a second run publishes a new version instead of failing"

def test_create_stops_with_a_clear_message_when_the_gemini_key_is_missing(stack_env):
    settings, aws = stack_env
    aws.ssm.delete_parameter(Name=settings.gemini_param_name)
    with pytest.raises(StackError, match="Gemini|gemini|Part C"):
        create_stack(settings, aws, iam_wait=0)
    assert aws.iam.list_roles()["Roles"] == [], "nothing may be created before the prerequisites pass"

def test_create_stops_with_a_clear_message_when_the_database_was_not_created(stack_env, tmp_path):
    settings, aws = stack_env
    (tmp_path / "db_outputs.env").unlink()
    with pytest.raises(StackError, match="create_database.py"):
        create_stack(settings, aws, iam_wait=0)

def test_dry_run_creates_nothing(stack_env):
    settings, aws = stack_env
    outputs = create_stack(settings, aws, iam_wait=0, dry_run=True)
    assert outputs.alb_dns_name
    assert aws.iam.list_roles()["Roles"] == []
    assert aws.elbv2.describe_load_balancers()["LoadBalancers"] == []

def test_delete_removes_everything_and_restores_the_app_sg(stack_env):
    settings, aws = stack_env
    create_stack(settings, aws, iam_wait=0).save()
    delete_stack(settings, aws, sleep=_no_sleep)
    assert aws.elbv2.describe_load_balancers()["LoadBalancers"] == []
    assert aws.elbv2.describe_target_groups()["TargetGroups"] == []
    assert aws.autoscaling.describe_auto_scaling_groups()["AutoScalingGroups"] == []
    assert aws.ec2.describe_launch_templates()["LaunchTemplates"] == []
    assert aws.iam.list_roles()["Roles"] == []
    assert aws.iam.list_instance_profiles()["InstanceProfiles"] == []
    group = aws.ec2.describe_security_groups(GroupIds=[settings.app_sg_id])["SecurityGroups"][0]
    rules = [p for p in group["IpPermissions"] if p["FromPort"] == 3000]
    assert rules[0]["IpRanges"] == [{"CidrIp": "0.0.0.0/0"}] and rules[0]["UserIdGroupPairs"] == []

def test_delete_leaves_the_secrets_alone(stack_env):
    """The Gemini key is kept so the stack can be rebuilt. The database has its own delete script."""
    settings, aws = stack_env
    create_stack(settings, aws, iam_wait=0)
    delete_stack(settings, aws, sleep=_no_sleep)
    aws.ssm.get_parameter(Name=settings.gemini_param_name)
    aws.ssm.get_parameter(Name=settings.db_password_param)

def test_delete_is_safe_to_run_twice(stack_env):
    settings, aws = stack_env
    create_stack(settings, aws, iam_wait=0)
    delete_stack(settings, aws, sleep=_no_sleep)
    delete_stack(settings, aws, sleep=_no_sleep)   # nothing left, must not raise

def test_keep_foundation_leaves_roles_and_templates(stack_env):
    settings, aws = stack_env
    create_stack(settings, aws, iam_wait=0)
    delete_stack(settings, aws, keep_foundation=True, sleep=_no_sleep)
    assert aws.autoscaling.describe_auto_scaling_groups()["AutoScalingGroups"] == []
    assert len(aws.iam.list_roles()["Roles"]) == 2
    assert len(aws.ec2.describe_launch_templates()["LaunchTemplates"]) == 2

def test_delete_detaches_extra_managed_policies(stack_env):
    settings, aws = stack_env
    create_stack(settings, aws, iam_wait=0)
    extra = aws.iam.create_policy(PolicyName="extra", PolicyDocument=json.dumps({
        "Version": "2012-10-17",
        "Statement": [{"Effect": "Allow", "Action": "logs:PutLogEvents", "Resource": "*"}]}))
    aws.iam.attach_role_policy(RoleName=settings.weather.role_name, PolicyArn=extra["Policy"]["Arn"])
    delete_stack(settings, aws, sleep=_no_sleep)
    assert aws.iam.list_roles()["Roles"] == []