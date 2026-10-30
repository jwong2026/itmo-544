#!/usr/bin/env python3
from __future__ import annotations
import logging
import secrets
from botocore.exceptions import ClientError
from .clients import AwsClients
from .config import Settings
from .util import ignore_errors

log = logging.getLogger("stack")

def generate_secure_password() -> str:
    """ Using `openssl rand -hex 16` command line to make 32 random characters. """
    return secrets.token_hex(16)

def get_default_vpc_and_subnets(aws: AwsClients, settings: Settings) -> tuple[str, list[str]]:
    """ == 1. Default VPC and subnets in both AZs. == """
    vpcs = aws.ec2.describe_vpcs(Filters=[{"Name": "isDefault", "Values": ["true"]}])["Vpcs"]
    if not vpcs:
        raise RuntimeError("No default VPC found in this region.")
    vpc_id = vpcs[0]["VpcId"]
    subnet_ids = []
    for az in [settings.az_a, settings.az_b]:
        subnets = aws.ec2.describe_subnets(
            Filters=[
                {"Name": "vpc-id", "Values": [vpc_id]},
                {"Name": "availability-zone", "Values": [az]},
            ]
        )["Subnets"]
        if not subnets:
            raise RuntimeError(f"The default VPC has no subnet in availability zone: {az}")
        subnet_ids.append(subnets[0]["SubnetId"])
    return vpc_id, subnet_ids

def ensure_database_security_group(aws: AwsClients, settings: Settings, vpc_id: str) -> str:
    """ == 2. Create a database security group or find it if it already exists. == """
    try:
        groups = aws.ec2.describe_security_groups(
            Filters=[
                {"Name": "group-name", "Values": [settings.db_sg_name]},
                {"Name": "vpc-id", "Values": [vpc_id]},
            ]
        )["SecurityGroups"]
        if groups:
            log.info("Database security group %s already exists, skipping.", settings.db_sg_name)
            return groups[0]["GroupId"]
    except ClientError:
        pass

    group_id = aws.ec2.create_security_group(
        GroupName=settings.db_sg_name,
        Description="PostgreSQL access from the lab app instances only",
        VpcId=vpc_id,
    )["GroupId"]
    log.info("Created database security group %s", group_id)

    # Authorize port 5432 ingress directly from the application tier security group
    with ignore_errors("InvalidPermission.Duplicate"):
        aws.ec2.authorize_security_group_ingress(
            GroupId=group_id,
            IpPermissions=[
                {
                    "IpProtocol": "tcp",
                    "FromPort": 5432,
                    "ToPort": 5432,
                    "UserIdGroupPairs": [{"GroupId": settings.app_sg_id}],
                }
            ],
        )
    return group_id

def ensure_db_subnet_group(aws: AwsClients, settings: Settings, subnet_ids: list[str]) -> None:
    """ == 3. DB subnet group =="""
    try:
        aws.rds.create_db_subnet_group(
            DBSubnetGroupName=settings.db_subnet_group_name,
            DBSubnetGroupDescription="Lab subnets for the weather database",
            SubnetIds=subnet_ids,
        )
        log.info("Created DB subnet group %s", settings.db_subnet_group_name)
    except ClientError as err:
        if err.response["Error"]["Code"] != "DBSubnetGroupAlreadyExists":
            raise
        log.info("DB subnet group %s already exists, skipping.", settings.db_subnet_group_name)

def ensure_db_password_parameter(aws: AwsClients, settings: Settings) -> str:
    """ == 4. Database password (random, stored as a SecureString, never printed). == """
    try:
        # Check if the secret parameter exists
        param = aws.ssm.get_parameter(Name=settings.db_password_param, WithDecryption=True)
        log.info("Password parameter already exists, keeping it.")
        return param["Parameter"]["Value"]
    except aws.ssm.exceptions.ParameterNotFound:
        password = generate_secure_password()
        aws.ssm.put_parameter(
            Name=settings.db_password_param,
            Description="Random master password for the RDS PostgreSQL database instance",
            Type="SecureString",
            Value=password,
            Overwrite=True,
        )
        log.info("Generated and stored new database password parameter.")
        return password

def ensure_rds_instance(aws: AwsClients, settings: Settings, db_sg_id: str, db_password: str) -> None:
    """ == 5. The PostgreSQL instance (free tier size, no backups). == """
    try:
        aws.rds.describe_db_instances(DBInstanceIdentifier=settings.db_instance_id)
        log.info("Database instance %s already exists, skipping.", settings.db_instance_id)
        return
    except ClientError as err:
        if err.response["Error"]["Code"] != "DBInstanceNotFound":
            raise

    aws.rds.create_db_instance(
        DBInstanceIdentifier=settings.db_instance_id,
        DBInstanceClass="db.t4g.micro",
        Engine="postgres",
        AllocatedStorage=20,
        StorageType="gp2",
        MasterUsername=settings.db_user,
        MasterUserPassword=db_password,
        DBName=settings.db_name,
        DBSubnetGroupName=settings.db_subnet_group_name,
        VpcSecurityGroupIds=[db_sg_id],
        AvailabilityZone=settings.az_a,
        BackupRetentionPeriod=0,
        MultiAZ=False,
        PubliclyAccessible=False,
        AutoMinorVersionUpgrade=False,
        DeletionProtection=False,
        StorageEncrypted=True,
    )
    log.info("Waiting for the PostgreSQL instance to complete setup (takes 5-10 minutes)...")
    aws.rds.get_waiter("db_instance_available").wait(DBInstanceIdentifier=settings.db_instance_id)

    desc = aws.rds.describe_db_instances(DBInstanceIdentifier=settings.db_instance_id)
    return desc["DBInstances"][0]["Endpoint"]["Address"]