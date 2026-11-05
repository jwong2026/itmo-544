#!/usr/bin/env python3
import argparse
import logging
import time
from pathlib import Path
from botocore.exceptions import ClientError
from stack.clients import AwsClients
from stack.config import Settings, ConfigError
from stack.util import ignore_errors, error_code
from stack.network import StackError

log = logging.getLogger("stack")

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env", default=".env", help="path to the settings file")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    settings = Settings.from_file(args.env)
    aws = AwsClients.create(settings.region)

    log.info("== Deleting the database (no final snapshot, no kept backups) ==")
    try:
        aws.rds.delete_db_instance(
            DBInstanceIdentifier=settings.db_instance_id,
            SkipFinalSnapshot=True,
            DeleteAutomatedBackups=True,
        )
        log.info("Waiting for the database to be deleted (a few minutes)...")
        aws.rds.get_waiter("db_instance_deleted").wait(DBInstanceIdentifier=settings.db_instance_id)
    except ClientError as err:
        if error_code(err) != "DBInstanceNotFound":
            raise
        log.info("Database %s not found, nothing to delete.", settings.db_instance_id)

    log.info("== Deleting the DB subnet group ==")
    with ignore_errors("DBSubnetGroupNotFoundFault"):
        aws.rds.delete_db_subnet_group(DBSubnetGroupName=settings.db_subnet_group_name)

    log.info("== Deleting the database security group ==")
    # Retries loop to handle latent network interface releases safely
    for i in range(1, 11):
        try:
            aws.ec2.delete_security_group(GroupName=settings.db_sg_name)
            log.info("Database security group deleted.")
            break
        except ClientError as err:
            if error_code(err) == "InvalidGroup.NotFound":
                log.info("Database security group not found, nothing to delete.")
                break
            elif error_code(err) == "DependencyViolation" and i < 10:
                log.info("Still releasing database resources, waiting 15s...")
                time.sleep(15)
            else:
                raise

    log.info("== Deleting the database password parameter ==")
    with ignore_errors("ParameterNotFound"):
        aws.ssm.delete_parameter(Name=settings.db_password_param)

    Path("db_outputs.env").unlink(missing_ok=True)
    log.info("== Checking that no snapshots or backups remain ==")
    name = settings.db_instance_id
    try:
        snapshots = [s["DBSnapshotIdentifier"] for s in aws.rds.describe_db_snapshots(DBInstanceIdentifier=name)["DBSnapshots"]]
        backups = aws.rds.describe_db_instance_automated_backups(DBInstanceIdentifier=name)["DBInstanceAutomatedBackups"]
    except ClientError as err:
        # Not being able to look is not the same as nothing being there, so do not report success.
        log.error("Could not check for leftovers (%s). Check by hand: aws rds describe-db-snapshots", error_code(err))
        return 1
    log.info("Snapshots left: %s. Automated backups left: %s.", snapshots or "none", len(backups) or "none")
    if snapshots or backups:
        log.warning("Something is left behind and may cost money. Remove snapshots with: aws rds delete-db-snapshot --db-snapshot-identifier <name>")
        return 1
    log.info("Database removed. Nothing is left behind.")
    return 0

if __name__ == "__main__":
    main()
