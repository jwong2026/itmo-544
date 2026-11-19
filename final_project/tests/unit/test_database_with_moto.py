"""Run the real database code against moto. No AWS account, no cost.

Creating uses the same five steps as create_database.py. Deleting runs the real
delete_database.main(), so the script itself is what gets tested.
"""
import pytest
import delete_database
from stack.clients import AwsClients
from stack.config import Settings
from stack.database import (
    ensure_database_security_group,
    ensure_db_password_parameter,
    ensure_db_subnet_group,
    ensure_rds_instance,
    get_default_vpc_and_subnets,
)
from stack.network import find_security_group


def build_database(aws, settings):
    """The five steps of create_database.py, in the same order. Returns (db_host, db_security_group_id)."""
    vpc_id, subnet_ids = get_default_vpc_and_subnets(aws, settings)
    db_sg_id = ensure_database_security_group(aws, settings, vpc_id)
    ensure_db_subnet_group(aws, settings, subnet_ids)
    db_password = ensure_db_password_parameter(aws, settings)
    return ensure_rds_instance(aws, settings, db_sg_id, db_password), db_sg_id


@pytest.fixture
def run_delete(aws_env, monkeypatch, tmp_path):
    """Run delete_database.main() against the fake account. Returns its exit code."""
    settings, aws = aws_env
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["delete_database.py"])
    monkeypatch.setattr(Settings, "from_file", classmethod(lambda cls, path: settings))
    monkeypatch.setattr(AwsClients, "create", classmethod(lambda cls, region: aws))
    # moto may not implement automated-backup listing; an empty answer is what a real deleted DB gives.
    monkeypatch.setattr(aws.rds, "describe_db_instance_automated_backups",
                        lambda **kw: {"DBInstanceAutomatedBackups": []})
    return delete_database.main


def test_database_is_free_tier_private_and_has_no_backups(aws_env):
    settings, aws = aws_env
    build_database(aws, settings)
    db = aws.rds.describe_db_instances(DBInstanceIdentifier=settings.db_instance_id)["DBInstances"][0]
    assert db["DBInstanceClass"] == "db.t4g.micro"
    assert db["Engine"] == "postgres"
    assert db["AllocatedStorage"] == 20
    assert db["BackupRetentionPeriod"] == 0
    assert db["MultiAZ"] is False
    assert db["PubliclyAccessible"] is False
    assert db["StorageEncrypted"] is True
    assert db["DeletionProtection"] is False
    assert db["MasterUsername"] == settings.db_user


def test_database_security_group_allows_5432_only_from_the_app_security_group(aws_env):
    settings, aws = aws_env
    _, db_sg_id = build_database(aws, settings)
    group = aws.ec2.describe_security_groups(GroupIds=[db_sg_id])["SecurityGroups"][0]
    rules = group["IpPermissions"]
    assert len(rules) == 1
    rule = rules[0]
    assert (rule["FromPort"], rule["ToPort"]) == (5432, 5432)
    assert [pair["GroupId"] for pair in rule["UserIdGroupPairs"]] == [settings.app_sg_id]
    assert rule["IpRanges"] == [] and rule.get("Ipv6Ranges", []) == [], "no CIDR range may reach the database"


def test_password_is_random_hex_stored_as_a_secure_string(aws_env):
    settings, aws = aws_env
    build_database(aws, settings)
    param = aws.ssm.get_parameter(Name=settings.db_password_param, WithDecryption=True)["Parameter"]
    assert param["Type"] == "SecureString"
    assert len(param["Value"]) == 32 and int(param["Value"], 16) >= 0, "32 hex characters, like openssl rand -hex 16"


def test_the_password_is_not_logged(aws_env, caplog, capsys):
    """Check what OUR code logs and prints. botocore's own DEBUG output echoes every request body
    (including the password), which is why the scripts run at INFO and never turn it on."""
    settings, aws = aws_env
    with caplog.at_level("DEBUG", logger="stack"):
        build_database(aws, settings)
    password = aws.ssm.get_parameter(Name=settings.db_password_param, WithDecryption=True)["Parameter"]["Value"]
    ours = "\n".join(r.getMessage() for r in caplog.records if r.name.startswith("stack"))
    assert ours, "the stack logger wrote nothing, so this test would prove nothing"
    assert password not in ours
    out = capsys.readouterr()
    assert password not in out.out + out.err


def test_create_returns_the_endpoint_and_security_group(aws_env):
    settings, aws = aws_env
    host, sg_id = build_database(aws, settings)
    assert host
    assert sg_id.startswith("sg-")


def test_create_twice_creates_no_duplicates_and_keeps_the_password(aws_env):
    settings, aws = aws_env
    build_database(aws, settings)
    first_password = aws.ssm.get_parameter(Name=settings.db_password_param, WithDecryption=True)["Parameter"]["Value"]
    build_database(aws, settings)
    assert len(aws.rds.describe_db_instances()["DBInstances"]) == 1
    assert len(aws.rds.describe_db_subnet_groups()["DBSubnetGroups"]) == 1
    groups = aws.ec2.describe_security_groups(Filters=[{"Name": "group-name", "Values": [settings.db_sg_name]}])["SecurityGroups"]
    assert len(groups) == 1 and len(groups[0]["IpPermissions"]) == 1
    second = aws.ssm.get_parameter(Name=settings.db_password_param, WithDecryption=True)["Parameter"]["Value"]
    assert second == first_password


def test_create_then_delete_leaves_nothing_behind(aws_env, run_delete):
    settings, aws = aws_env
    build_database(aws, settings)
    assert run_delete() == 0
    assert aws.rds.describe_db_instances()["DBInstances"] == []
    assert aws.rds.describe_db_snapshots()["DBSnapshots"] == []
    assert aws.rds.describe_db_subnet_groups()["DBSubnetGroups"] == []
    vpc_id = aws.ec2.describe_vpcs(Filters=[{"Name": "isDefault", "Values": ["true"]}])["Vpcs"][0]["VpcId"]
    assert find_security_group(aws, settings.db_sg_name, vpc_id) is None
    with pytest.raises(aws.ssm.exceptions.ParameterNotFound):
        aws.ssm.get_parameter(Name=settings.db_password_param)


def test_delete_removes_db_outputs_env(aws_env, run_delete, tmp_path):
    settings, aws = aws_env
    build_database(aws, settings)
    (tmp_path / "db_outputs.env").write_text("DB_HOST=x\n")
    run_delete()
    assert not (tmp_path / "db_outputs.env").exists()


def test_delete_is_safe_to_run_twice(aws_env, run_delete):
    settings, aws = aws_env
    build_database(aws, settings)
    assert run_delete() == 0
    assert run_delete() == 0   # everything is gone already: must not raise


def test_delete_asks_for_no_snapshot_and_no_kept_backups(aws_env, run_delete, monkeypatch):
    """moto cannot take real snapshots, so check the REQUEST: SkipFinalSnapshot and DeleteAutomatedBackups."""
    settings, aws = aws_env
    build_database(aws, settings)
    calls, real = [], aws.rds.delete_db_instance
    monkeypatch.setattr(aws.rds, "delete_db_instance", lambda **kw: (calls.append(kw), real(**kw))[1])
    run_delete()
    assert calls[0]["SkipFinalSnapshot"] is True
    assert calls[0]["DeleteAutomatedBackups"] is True


def test_delete_fails_loudly_when_a_snapshot_is_left_behind(aws_env, run_delete, monkeypatch):
    settings, aws = aws_env
    build_database(aws, settings)
    # A real manual snapshot survives the instance, exactly like the console's default final snapshot.
    # Using a real one (not a patched method) means this works however delete_database.py asks for snapshots.
    aws.rds.create_db_snapshot(DBInstanceIdentifier=settings.db_instance_id, DBSnapshotIdentifier="leftover-snap")
    assert run_delete() == 1
    names = [s["DBSnapshotIdentifier"] for s in aws.rds.describe_db_snapshots()["DBSnapshots"]]
    assert "leftover-snap" in names, "the script reports a leftover snapshot, it must not silently delete it"


def test_delete_fails_loudly_when_an_automated_backup_is_left_behind(aws_env, run_delete, monkeypatch):
    settings, aws = aws_env
    build_database(aws, settings)
    monkeypatch.setattr(aws.rds, "describe_db_instance_automated_backups",
                        lambda **kw: {"DBInstanceAutomatedBackups": [{"DBInstanceIdentifier": "x"}]})
    assert run_delete() == 1
