""" User-data and launch templates. """
from __future__ import annotations
import base64
import logging
from botocore.exceptions import ClientError
from .clients import AwsClients
from .config  import Settings, Tier
from .network import StackError
from .util import error_code

log = logging.getLogger("stack")
RDS_CA_URL = "https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem"
MAX_USER_DATA_BYTES = 16 * 1024

def _b64_file(path) -> str:
    return base64.b64encode(path.read_bytes()).decode()

def tier_setup(tier: Tier) -> str:
    """ Pull amazon cert pem file """
    if tier.name == "weather":
        return f"dnf install -y postgresql15\ncurl -sS -o /opt/app/rds-ca.pem {RDS_CA_URL}\n"
    return ""

def tier_environment(settings: Settings, tier: Tier, alb_dns: str | None, db_host: str | None ) -> list[str]:
    """ this function is for extra environment lines in systemd service. """
    if tier.name == "weather":
        if not db_host:
            raise StackError("The weather user-data needs the database host (run create_database.py).")
        return [
            f'Environment="NWS_USER_AGENT=(itmo-544-weather-lab, {settings.contact_email})"',
            f"Environment=DB_HOST={db_host}",
            f"Environment=DB_NAME={settings.db_name}",
            f"Environment=DB_USER={settings.db_user}",
            f"Environment=DB_PASSWORD_PARAM={settings.db_password_param}",
            f"Environment=CACHE_SECONDS={settings.cache_seconds}",
        ]
    if not alb_dns:
        raise StackError("The advisor user-data needs the ALB DNS name, so the ALB must be created first.")
    return [
        f"Environment=WEATHER_URL=http://{alb_dns}:{settings.weather.listener_port}",
        f"Environment=GEMINI_KEY_PARAM={settings.gemini_param_name}",
        f"Environment=GEMINI_MODEL={settings.gemini_model}",
        f"Environment=KEY_CACHE_SECONDS={settings.key_cache_seconds}",
    ]

def build_user_data(settings: Settings, tier: Tier, alb_dns: str | None = None, db_host: str | None = None) -> str:
    """ The boot script: write the app files, install Node, run the app as a service. """
    app_js = _b64_file(tier.app_dir / "app.js")
    package_json = _b64_file(tier.app_dir / "package.json")
    env_lines = "\n".join(tier_environment(settings, tier, alb_dns, db_host))
    return	f"""#!/bin/bash
dnf update -y
dnf install -y nodejs
mkdir -p /opt/app
{tier_setup(tier)}
echo "{app_js}" | base64 -d > /opt/app/app.js
echo "{package_json}" | base64 -d > /opt/app/package.json
cd /opt/app
npm install --omit=dev

cat > /etc/systemd/system/{tier.service_name}.service << 'SERVICE'
[Unit]
Description={tier.name.capitalize()} App
After=network.target
[Service]
Environment=AWS_REGION={settings.region}
Environment=PORT={settings.app_port}
{env_lines}
WorkingDirectory=/opt/app
ExecStart=/usr/bin/node /opt/app/app.js
Restart=always
User=ec2-user
[Install]
WantedBy=multi-user.target
SERVICE

chown -R ec2-user:ec2-user /opt/app
systemctl daemon-reload
systemctl enable {tier.service_name}.service
systemctl start {tier.service_name}.service
"""

def launch_template_data(settings: Settings, tier: Tier, alb_dns: str | None = None, db_host: str | None = None) -> dict:
    user_data = build_user_data(settings, tier, alb_dns, db_host)
    size = len(user_data.encode())
    if size > MAX_USER_DATA_BYTES:
        raise StackError(f"{tier.name} user-data is {size} bytes, over the 16 KB EC2 limit. Keep the app under the limit.")
    return {
        "ImageId": settings.ami_id,
        "InstanceType": settings.instance_type,
        "KeyName": settings.key_name,
        "SecurityGroupIds": [settings.app_sg_id],
        "IamInstanceProfile": {"Name": tier.profile_name},
        # The API wants user-data already base64 encoded.
        "UserData": base64.b64encode(user_data.encode()).decode(),
        "TagSpecifications": [{
            "ResourceType": "instance",
            "Tags": [{"Key": "Name", "Value": f"{tier.name}-app"}],
        }],
    }

def launch_template_exists(aws: AwsClients, tier: Tier) -> bool:
    try:
        aws.ec2.describe_launch_templates(LaunchTemplateNames=[tier.lt_name])
        return True
    except ClientError as err:
        if error_code(err) != "InvalidLaunchTemplateName.NotFoundException":
            raise
        return False

def ensure_launch_template(aws: AwsClients, settings: Settings, tier: Tier, alb_dns: str | None = None, db_host: str | None = None) -> int:
    """ Create the template, or publish a new version if it already exists. """
    data = launch_template_data(settings, tier, alb_dns, db_host)
    if not launch_template_exists(aws, tier):
        aws.ec2.create_launch_template(LaunchTemplateName=tier.lt_name, LaunchTemplateData=data)
        log.info("Created launch template %s", tier.lt_name)
        return 1
    response = aws.ec2.create_launch_template_version(
        LaunchTemplateName=tier.lt_name, SourceVersion="1", LaunchTemplateData=data
    )
    version = response["LaunchTemplateVersion"]["VersionNumber"]
    log.info("Template %s exists, published version %s", tier.lt_name, version)
    return version

def delete_launch_template(aws: AwsClients, tier: Tier) -> None:
    if launch_template_exists(aws, tier):
        aws.ec2.delete_launch_template(LaunchTemplateName=tier.lt_name)
        log.info("Deleted launch template %s", tier.lt_name)