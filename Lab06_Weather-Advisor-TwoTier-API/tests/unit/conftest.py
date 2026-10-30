"""Unit-test fixtures: a fake AWS account (moto) with the things earlier labs already created."""
import pytest
from moto import mock_aws
from stack.clients import AwsClients
from stack.config import Settings
from tests.conftest import FAKE_VALUES

@pytest.fixture(autouse=True)
def fake_credentials(monkeypatch):
    """Unit tests must pass with no AWS credentials, and must never reach a real account."""
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", FAKE_VALUES["AWS_REGION"])
    monkeypatch.delenv("AWS_PROFILE", raising=False)

@pytest.fixture
def aws_env(fake_settings):
    """(settings, aws): a fake account with a default VPC, the app security group and a key pair."""
    with mock_aws():
        aws = AwsClients.create(FAKE_VALUES["AWS_REGION"])
        vpc = aws.ec2.describe_vpcs(Filters=[{"Name": "isDefault", "Values": ["true"]}])["Vpcs"][0]
        app_sg = aws.ec2.create_security_group(GroupName="app-sg", Description="app", VpcId=vpc["VpcId"])["GroupId"]
        aws.ec2.authorize_security_group_ingress(GroupId=app_sg, IpPermissions=[{
            "IpProtocol": "tcp", "FromPort": 3000, "ToPort": 3000, "IpRanges": [{"CidrIp": "0.0.0.0/0"}]}])
        aws.ec2.create_key_pair(KeyName="test-key")
        ami = aws.ec2.describe_images()["Images"][0]["ImageId"]
        values = dict(FAKE_VALUES, APP_SECURITY_GROUP_ID=app_sg, AMI_ID=ami)
        settings = Settings.from_values(values, base_dir=fake_settings.weather.app_dir.parent)
        yield settings, aws