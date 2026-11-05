from __future__ import annotations
import logging
import time
from pathlib import Path
from . import balancer, compute, network, scaling, storage
from .clients import AwsClients
from .config import Settings, load_dotenv
from .network import StackError
from .outputs import StackOutputs

log = logging.getLogger("stack")

DB_OUTPUTS_FILE = "db_outputs.env"

def parameter_exists(aws: AwsClients, name: str) -> bool:
    """ True if the SSM parameter exists. Lists metadata only, so the secret is never read. """
    found = aws.ssm.describe_parameters(
        ParameterFilters=[{"Key": "Name", "Option": "Equals", "Values": [name]}]
    )["Parameters"]
    return bool(found)


def check_prerequisites(settings: Settings, aws: AwsClients, db_outputs_file: str = DB_OUTPUTS_FILE) -> str:
    """ == 1. Gemini key and database must exist first. Returns the database host. == """
    if not parameter_exists(aws, settings.gemini_param_name):
        raise StackError(
            f"Parameter {settings.gemini_param_name} was not found. Create it first (Part C of the lab)."
        )
    if not Path(db_outputs_file).is_file():
        raise StackError(f"{db_outputs_file} was not found. Run create_database.py first (Part E of the lab).")
    db_host = load_dotenv(db_outputs_file).get("DB_HOST")
    if not db_host:
        raise StackError(f"{db_outputs_file} has no DB_HOST. Run create_database.py again.")
    return db_host

def create_stack(settings: Settings, aws: AwsClients, iam_wait: int = 15, sleep=time.sleep, dry_run: bool = False, db_outputs_file: str = DB_OUTPUTS_FILE ) -> StackOutputs:
    log.info("== 1. Checking the Gemini key and the database ==")
    db_host = check_prerequisites(settings, aws, db_outputs_file)

    log.info("== 2. IAM roles, instance profiles and one-secret policies ==")
    if dry_run:
        for tier in settings.tiers:
            log.info("[DRY RUN] Would ensure IAM role, profile and policy for tier: %s", tier.name)
        log.info("[DRY RUN] Stopping before any network or compute resources are created.")
        return StackOutputs(
            vpc_id="vpc-dryrun", subnet_a="subnet-a-dryrun", subnet_b="subnet-b-dryrun",
            alb_security_group_id="sg-dryrun", alb_arn="arn-dryrun", alb_dns_name="alb.dryrun.example.com",
            weather_tg_arn="tg-weather-dryrun", advisor_tg_arn="tg-advisor-dryrun",
        )
    account_id = aws.sts.get_caller_identity()["Account"]
    for tier in settings.tiers:
        # weather reads the database password; advisor reads the Gemini key. Neither reads the other's.
        storage.ensure_role_and_profile(aws, settings, tier, account_id, settings.secret_param_for(tier))
    log.info("Waiting %ss for IAM propagation...", iam_wait)
    sleep(iam_wait)

    log.info("== 3. Default VPC and subnets in both AZs ==")
    vpc_id = network.default_vpc_id(aws)
    subnet_a = network.subnet_in_az(aws, vpc_id, settings.az_a)
    subnet_b = network.subnet_in_az(aws, vpc_id, settings.az_b)

    log.info("== 4. Security groups ==")
    alb_sg_id = network.ensure_alb_security_group(aws, settings, vpc_id)
    network.restrict_app_security_group(aws, settings, alb_sg_id)

    log.info("== 5. Target groups and the load balancer (the ALB comes first this time) ==")
    tg_arns = {tier.name: balancer.ensure_target_group(aws, settings, tier, vpc_id) for tier in settings.tiers}
    alb_arn, alb_dns = balancer.ensure_load_balancer(aws, settings, [subnet_a, subnet_b], alb_sg_id)
    for tier in settings.tiers:
        balancer.ensure_listener(aws, alb_arn, tier.listener_port, tg_arns[tier.name])

    log.info("== 6. Launch templates (advisor gets the ALB address, weather gets the DB address) ==")
    for tier in settings.tiers:
        compute.ensure_launch_template(aws, settings, tier, alb_dns=alb_dns, db_host=db_host)

    log.info("== 7. Auto Scaling Groups (these launch the instances) ==")
    for tier in settings.tiers:
        scaling.ensure_asg(aws, tier, tg_arns[tier.name], [subnet_a, subnet_b])

    return StackOutputs(
        vpc_id=vpc_id,
        subnet_a=subnet_a,
        subnet_b=subnet_b,
        alb_security_group_id=alb_sg_id,
        alb_arn=alb_arn,
        alb_dns_name=alb_dns,
        weather_tg_arn=tg_arns["weather"],
        advisor_tg_arn=tg_arns["advisor"],
    )

def delete_stack(settings: Settings, aws: AwsClients, keep_foundation: bool = False, sleep=time.sleep) -> None:
    """
    Delete by name, not by saved state, so it still works after a half-finished create.
    Ensure you run delete_database.py after running delete_weather_stack.py.
    """
    log.info("== Auto Scaling Groups (this also terminates their instances) ==")
    for tier in settings.tiers:
        scaling.delete_asg(aws, tier.asg_name, sleep=sleep)

    log.info("== Load balancer and target groups ==")
    balancer.delete_load_balancer(aws, settings.alb_name)
    for tier in settings.tiers:
        balancer.delete_target_group(aws, tier.tg_name)

    log.info("== Restoring the app security group and deleting the ALB security group ==")
    vpc_id = network.default_vpc_id(aws)
    alb_sg_id = network.find_security_group(aws, settings.alb_sg_name, vpc_id)
    network.restore_app_security_group(aws, settings, alb_sg_id)
    if alb_sg_id:
        network.delete_alb_security_group(aws, alb_sg_id, sleep=sleep)

    if keep_foundation:
        log.info("Keeping the IAM roles and launch templates (--keep-foundation).")
    else:
        log.info("== Launch templates and IAM roles ==")
        for tier in settings.tiers:
            compute.delete_launch_template(aws, tier)
            storage.delete_role_and_profile(aws, tier)

    StackOutputs.remove()
    log.info("Weather stack removed. The database and the Gemini key parameter were left in place.")