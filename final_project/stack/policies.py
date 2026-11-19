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

def advisor_policy(region: str, account_id: str, gemini_param_name: str, table_name: str = "LookupsCounter") -> dict:
    """ Read the private Gemini API key, send SES mail, and update daily metrics on DynamoDB. """
    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Action": ["ssm:GetParameter"],
                "Resource": parameter_arn(region, account_id, gemini_param_name)
            },
            {
                "Effect": "Allow",
                "Action": [
                    "dynamodb:GetItem",
                    "dynamodb:PutItem",
                    "dynamodb:UpdateItem"
                ],
                # Restricted specifically to your LookupsCounter cluster resource ARN blueprint
                "Resource": [
                    f"arn:aws:dynamodb:{region}:{account_id}:table/{table_name}",
                    f"arn:aws:dynamodb:{region}:{account_id}:table/{table_name}/*"
                ]
            },
            {
                "Effect": "Allow",
                "Action": [
                    "ses:SendEmail",
                    "ses:SendRawEmail",
                    "ses:VerifyEmailIdentity"
                ],
                "Resource": f"arn:aws:ses:{region}:{account_id}:identity/*"
            }
        ],
    }

def policy_for(tier_name: str, region: str, account_id: str, param_path: str, table_name: str = "LookupsCounter") -> dict:
    """ Routing dispatch function to cleanly select a policy document dictionary by tier name. """
    if tier_name == "weather":
        return weather_policy(region, account_id, param_path)
    if tier_name == "advisor":
        return advisor_policy(region, account_id, param_path, table_name)
    raise KeyError(f"Unknown tier name: {tier_name}")