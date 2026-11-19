""" S3 bucket and IAM role and instance profile: the foundation of the stack. """
from __future__ import annotations
import json
import logging
from .clients import AwsClients
from .config import Settings, Tier
from .policies import policy_for, trust_policy
from .util import ignore_errors

log = logging.getLogger("stack")

def ensure_role_and_profile(aws: AwsClients, settings: Settings, tier: Tier, account_id: str, param_name: str) -> None:
	""" Create the role, its inline policy, and an instance profile that holds the role. """
	if tier.name == "advisor":
		ensure_abuse_control_table(aws, settings.advisor_table_name) # Automatically provision tracking table before compute starts
	with ignore_errors("EntityAlreadyExists"):
		aws.iam.create_role(
			RoleName=tier.role_name,
            AssumeRolePolicyDocument=json.dumps(trust_policy()),
        )
	aws.iam.put_role_policy(
        RoleName=tier.role_name,
        PolicyName=tier.policy_name,
        PolicyDocument=json.dumps(policy_for(tier.name, settings.region, account_id, param_name, table_name=settings.advisor_table_name)),
    )
	with ignore_errors("EntityAlreadyExists"):
		aws.iam.create_instance_profile(InstanceProfileName=tier.profile_name)
	profile = aws.iam.get_instance_profile(InstanceProfileName=tier.profile_name)
	roles = [r["RoleName"] for r in profile["InstanceProfile"]["Roles"]]
	if tier.role_name not in roles:
		aws.iam.add_role_to_instance_profile(
			InstanceProfileName=tier.profile_name, RoleName=tier.role_name
        )
	log.info("%s role and instance profile are ready.", tier.name)

def delete_role_and_profile(aws: AwsClients, tier: Tier) -> None:
	with ignore_errors("NoSuchEntity"):
		aws.iam.remove_role_from_instance_profile(
			InstanceProfileName=tier.profile_name,
            RoleName=tier.role_name
        )
	with ignore_errors("NoSuchEntity"):
		aws.iam.delete_instance_profile(InstanceProfileName=tier.profile_name)
	with ignore_errors("NoSuchEntity"):
		aws.iam.delete_role_policy(
			RoleName=tier.role_name,
            PolicyName=tier.policy_name
        )
	# A managed policy attached later (for example by a monitoring lab) would block delete_role.
	with ignore_errors("NoSuchEntity"):
		attached = aws.iam.list_attached_role_policies(RoleName=tier.role_name)
		for policy in attached["AttachedPolicies"]:
			aws.iam.detach_role_policy(RoleName=tier.role_name,	PolicyArn=policy["PolicyArn"])
	with ignore_errors("NoSuchEntity"):
		aws.iam.delete_role(RoleName=tier.role_name)
	log.info("Removed %s role and instance profile.", tier.name)

def ensure_abuse_control_table(aws: AwsClients, table_name: str = "LookupsCounter") -> None:
    """ Create the DynamoDB table for tracking daily Gemini call limits with TTL rules. """
    try:
        tables = aws.dynamodb.list_tables()["TableNames"]
        if table_name in tables:
            log.info("Abuse control table %s already exists, skipping.", table_name)
            return
            
        aws.dynamodb.create_table(
            TableName=table_name,
            KeySchema=[{"AttributeName": "PK", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "PK", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST"
        )
        log.info("Waiting for table %s to complete creation...", table_name)
        aws.dynamodb.get_waiter("table_exists").wait(TableName=table_name)
        
        aws.dynamodb.update_time_to_live(
            TableName=table_name,
            TimeToLiveSpecification={"Enabled": True, "AttributeName": "expires_at"}
        )
        log.info("Successfully provisioned atomic tracking datastore %s with active TTL sweeps.", table_name)
    except Exception as err:
        log.error("Could not construct abuse table infrastructure: %s", err)

def delete_abuse_control_table(aws: AwsClients, table_name: str = "LookupsCounter") -> None:
    """ Delete the DynamoDB tracking and report cache table during stack teardown. """
    with ignore_errors("ResourceNotFoundException"):
        aws.dynamodb.delete_table(TableName=table_name)
        log.info("Deleted DynamoDB table %s.", table_name)
