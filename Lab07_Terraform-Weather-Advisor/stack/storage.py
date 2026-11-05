""" S3 bucket and IAM role and instance profile: the foundation of the stack. """
from __future__ import annotations
import json
import logging
from botocore.exceptions import ClientError
from .clients import AwsClients
from .config import Settings, Tier
from .policies import policy_for, trust_policy
from .util import error_code, ignore_errors

log = logging.getLogger("stack")

def ensure_role_and_profile(aws: AwsClients, settings: Settings, tier: Tier, account_id: str, param_name: str) -> None:
	""" Create the role, its inline policy, and an instance profile that holds the role. """
	with ignore_errors("EntityAlreadyExists"):
		aws.iam.create_role(
			RoleName=tier.role_name,
            AssumeRolePolicyDocument=json.dumps(trust_policy()),
        )
	aws.iam.put_role_policy(
        RoleName=tier.role_name,
        PolicyName=tier.policy_name,
        PolicyDocument=json.dumps(policy_for(tier.name, settings.region, account_id, param_name)),
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