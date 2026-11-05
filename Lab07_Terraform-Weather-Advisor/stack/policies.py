"""
IAM policy documents as plain Python dictionaries.
Keeping them as pure functions means we can test them without touching AWS.
"""
from __future__ import annotations

def parameter_arn(region: str, account_id: str, name: str) -> str:
    """ ARN of an SSM parameter. The ARN has one slash after 'parameter', whether or not the name starts with one. """
    return f"arn:aws:ssm:{region}:{account_id}:parameter/{name.lstrip('/')}"

def trust_policy() -> dict:
    """ Who may assume the role: the EC2 service, nobody else. """
    return {
        "Version": "2012-10-17",
        "Statement": [{
            "Effect": "Allow",
            "Principal": {"Service": "ec2.amazonaws.com"},
            "Action": "sts:AssumeRole",
        }],
    }

def weather_policy(region: str, account_id: str, db_password_param: str) -> dict:
    """ Read the private database password SecureString parameter, and nothing else. """
    return {
        "Version": "2012-10-17",
        "Statement": [{
            "Effect": "Allow",
            "Action": ["ssm:GetParameter"],
            "Resource": parameter_arn(region, account_id, db_password_param)
        }],
    }

def advisor_policy(region: str, account_id: str, gemini_param_name: str) -> dict:
    """ Read the private Gemini API key SecureString parameter, and nothing else. """
    return {
        "Version": "2012-10-17",
        "Statement": [{
            "Effect": "Allow",
            "Action": ["ssm:GetParameter"],
            "Resource": parameter_arn(region, account_id, gemini_param_name)
        }],
    }

def policy_for(tier_name: str, region: str, account_id: str, param_path: str) -> dict:
    """ Routing dispatch function to cleanly select a policy document dictionary by tier name. """
    return {
        "weather": weather_policy,
        "advisor": advisor_policy
    }[tier_name](region, account_id, param_path)