#!/usr/bin/env python3
import argparse
import logging
from pathlib import Path
from stack.clients import AwsClients
from stack.config import Settings
from stack.database import (
    get_default_vpc_and_subnets,
    ensure_database_security_group,
    ensure_db_subnet_group,
    ensure_db_password_parameter,
    ensure_rds_instance,
)

log = logging.getLogger("stack")

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env", default=".env", help="path to the settings file")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    settings = Settings.from_file(args.env)
    aws = AwsClients.create(settings.region)

    log.info("== 1. Default VPC and subnets in both AZs. ==")
    vpc_id, subnet_ids = get_default_vpc_and_subnets(aws, settings)

    log.info("== 2. Database security group (port 5432, from the app security group only) ==")
    db_sg_id = ensure_database_security_group(aws, settings, vpc_id)

    log.info("== 3. DB subnet group ==")
    ensure_db_subnet_group(aws, settings, subnet_ids)

    log.info("== 4. Database password (random, stored as a SecureString, never printed) ==")
    db_password = ensure_db_password_parameter(aws, settings)

    log.info("== 5. The PostgreSQL instance (free tier size, no backups) ==")
    ensure_rds_instance(aws, settings, db_sg_id, db_password)

    desc = aws.rds.describe_db_instances(DBInstanceIdentifier=settings.db_instance_id)
    db_host = desc["DBInstances"][0]["Endpoint"]["Address"]

    Path("db_outputs.env").write_text(f"DB_HOST={db_host}\nDB_SECURITY_GROUP_ID={db_sg_id}\n")

    log.info("\nDone. Database endpoint: %s", db_host)
    log.info("Automated backups are OFF (retention 0) and no final snapshot will be taken on delete.")

if __name__ == "__main__":
    main()
