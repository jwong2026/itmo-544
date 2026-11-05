""" Least privilege, checked as code. These tests need no AWS account. """
import json
from stack.policies import advisor_policy, policy_for, trust_policy, weather_policy

REGION, ACCOUNT = "us-east-2", "123456789012"
DB_PARAM, GEMINI_PARAM = "/itmo-444-544/db-password", "/itmo-444-544/gemini-api-key"
DB_ARN = f"arn:aws:ssm:{REGION}:{ACCOUNT}:parameter{DB_PARAM}"
GEMINI_ARN = f"arn:aws:ssm:{REGION}:{ACCOUNT}:parameter{GEMINI_PARAM}"

def test_weather_role_reads_exactly_the_database_password():
    statement = weather_policy(REGION, ACCOUNT, DB_PARAM)["Statement"][0]
    assert statement["Effect"] == "Allow"
    assert statement["Action"] == ["ssm:GetParameter"]
    assert statement["Resource"] == DB_ARN

def test_trust_policy_only_trusts_ec2():
    statement = trust_policy()["Statement"][0]
    assert statement["Principal"] == {"Service": "ec2.amazonaws.com"}
    assert statement["Action"] == "sts:AssumeRole"

def test_advisor_role_reads_exactly_the_gemini_key():
    statement = advisor_policy(REGION, ACCOUNT, GEMINI_PARAM)["Statement"][0]
    assert statement["Action"] == ["ssm:GetParameter"]
    assert statement["Resource"] == GEMINI_ARN


def test_neither_policy_mentions_the_other_secret():
    weather = json.dumps(policy_for("weather", REGION, ACCOUNT, DB_PARAM))
    advisor = json.dumps(policy_for("advisor", REGION, ACCOUNT, GEMINI_PARAM))
    assert "gemini" not in weather and "db-password" not in advisor

def test_no_policy_uses_a_wildcard():
    for tier, param in (("weather", DB_PARAM), ("advisor", GEMINI_PARAM)):
        for statement in policy_for(tier, REGION, ACCOUNT, param)["Statement"]:
            assert statement["Resource"] != "*"
            assert not any(a in ("*", "ssm:*") for a in statement["Action"])

def test_arn_is_the_same_with_or_without_a_leading_slash():
    """SSM ARNs have one slash after 'parameter', whatever the name looks like."""
    with_slash = weather_policy(REGION, ACCOUNT, "/a/b")["Statement"][0]["Resource"]
    without = weather_policy(REGION, ACCOUNT, "a/b")["Statement"][0]["Resource"]
    assert with_slash == without == f"arn:aws:ssm:{REGION}:{ACCOUNT}:parameter/a/b"