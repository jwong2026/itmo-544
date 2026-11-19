""" User-data and launch templates. """
from __future__ import annotations
import base64
import logging
import gzip
import json
from botocore.exceptions import ClientError
from .clients import AwsClients
from .config  import Settings, Tier
from .network import StackError
from .util import error_code

log = logging.getLogger("stack")
RDS_CA_URL = "https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem"
MAX_USER_DATA_BYTES = 16 * 1024

def _b64_gz_file(path) -> str:
    compressed = gzip.compress(path.read_bytes(), compresslevel=9)
    return base64.b64encode(compressed).decode()

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
        f"Environment=GEMINI_PARAM_NAME={settings.gemini_param_name}",
        f"Environment=GEMINI_MODEL={settings.gemini_model}",
        f"Environment=KEY_CACHE_SECONDS={settings.key_cache_seconds}",
        f"Environment=CONTACT_EMAIL={settings.contact_email}",
        f"Environment=ADVISOR_TABLE_NAME={settings.advisor_table_name}",
        f"Environment=DAILY_GEMINI_CAP={settings.daily_gemini_cap}",
        f"Environment=REPORT_CACHE_SECONDS={settings.report_cache_seconds}",
        f"Environment=VISITOR_REPORT_LIMIT_PER_MIN={settings.visitor_report_limit_per_min}",
        f"Environment=VISITOR_EMAIL_LIMIT_PER_HOUR={settings.visitor_email_limit_per_hour}",
        f"Environment=MAX_ADVICE_CHARS={settings.max_advice_chars}",
        f"Environment=VISITOR_HASH_SALT={settings.visitor_hash_salt}",
    ]

def build_user_data(settings: Settings, tier: Tier, alb_dns: str | None = None, db_host: str | None = None) -> str:
    """Build a pure Python EC2 user-data boot script (no bash) to unpack, install, and start the Node app."""
    app_js = _b64_gz_file(tier.app_dir / "app.js")
    package_json = _b64_gz_file(tier.app_dir / "package.json")
    env_lines = "\n".join(tier_environment(settings, tier, alb_dns, db_host))

    packages = ["nodejs", "postgresql15"] if tier.name == "weather" else ["nodejs"]
    download_ca = (
        f'urllib.request.urlretrieve("{RDS_CA_URL}", "/opt/app/rds-ca.pem")'
        if tier.name == "weather"
        else "pass"
    )

    service_unit = f"""[Unit]
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
"""

    return f"""#!/usr/bin/env python3
import base64
import gzip
import pathlib
import shutil
import subprocess
import urllib.request

APP_JS_B64 = {json.dumps(app_js)}
PACKAGE_JSON_B64 = {json.dumps(package_json)}
SERVICE_UNIT = {json.dumps(service_unit)}
PACKAGES = {json.dumps(packages)}

subprocess.run(["dnf", "update", "-y"])
subprocess.run(["dnf", "install", "-y", *PACKAGES])

app_dir = pathlib.Path("/opt/app")
app_dir.mkdir(parents=True, exist_ok=True)
{download_ca}

(app_dir / "app.js").write_bytes(gzip.decompress(base64.b64decode(APP_JS_B64)))
(app_dir / "package.json").write_bytes(gzip.decompress(base64.b64decode(PACKAGE_JSON_B64)))

subprocess.run(["npm", "install", "--omit=dev", "--prefix", "/opt/app"], check=True)

service_path = pathlib.Path("/etc/systemd/system/{tier.service_name}.service").write_text(SERVICE_UNIT, encoding="utf-8")

shutil.chown("/opt/app", user="ec2-user", group="ec2-user")
for item in app_dir.rglob("*"):
    shutil.chown(item, user="ec2-user", group="ec2-user")

subprocess.run(["systemctl", "daemon-reload"], check=True)
subprocess.run(["systemctl", "enable", "{tier.service_name}.service"], check=True)
subprocess.run(["systemctl", "start", "{tier.service_name}.service"], check=True)
"""

def launch_template_data(settings: Settings, tier: Tier, alb_dns: str | None = None, db_host: str | None = None) -> dict:
    user_data = build_user_data(settings, tier, alb_dns, db_host)
    size = len(user_data.encode("utf-8"))
    if size > MAX_USER_DATA_BYTES:
        raise StackError(f"{tier.name} user-data is {size} bytes, over the 16 KB EC2 limit. Keep the app under the limit.")
    return {
        "ImageId": settings.ami_id,
        "InstanceType": settings.instance_type,
        "KeyName": settings.key_name,
        "SecurityGroupIds": [settings.app_sg_id],
        "IamInstanceProfile": {"Name": tier.profile_name},
        # The API wants user-data already base64 encoded.
        "UserData": base64.b64encode(user_data.encode("utf-8")).decode("ascii"),
        "TagSpecifications": [{
            "ResourceType": "instance",
            "Tags": [{"Key": "Name", "Value": f"{tier.name}-app"}],
        }],
    }

def launch_template_exists(aws: AwsClients, tier: Tier) -> bool:
    """ Return True if the launch template already exists. """
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