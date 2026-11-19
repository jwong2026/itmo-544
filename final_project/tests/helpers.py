""" Small helpers shared by the integration tests. """
import subprocess
import time
import requests
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

def probe(url: str, timeout: float = 3.0) -> bool:
    """ True if the URL answers 200 within the timeout. """
    try:
        return requests.get(url, timeout=timeout).status_code == 200
    except requests.RequestException:
        return False

def wait_until(check, timeout: int = 300, interval: int = 10):
    """ Call check() until it returns something truthy, or fail after `timeout` seconds. """
    deadline = time.time() + timeout
    while time.time() < deadline:
        result = check()
        if result:
            return result
        time.sleep(interval)
    return None

def tier_url(outputs, settings, tier_name: str) -> str:
    port = settings.tier(tier_name).listener_port
    return f"http://{outputs.alb_dns_name}:{port}/"

def get_json(url: str, timeout: float = 30.0):
    """Return (status, parsed JSON or text). Connection problems return (0, {...}) instead of raising."""
    try:
        response = requests.get(url, timeout=timeout)
    except requests.RequestException as err:
        return 0, {"error": f"no connection: {err}"}
    try:
        return response.status_code, response.json()
    except ValueError:
        return response.status_code, response.text

def instance_ip(aws, name_tag: str):
    """Public IP of a running instance with this Name tag (weather-app or advisor-app), or None."""
    reservations = aws.ec2.describe_instances(Filters=[
        {"Name": "tag:Name", "Values": [name_tag]},
        {"Name": "instance-state-name", "Values": ["running"]},
    ])["Reservations"]
    for reservation in reservations:
        for instance in reservation["Instances"]:
            if instance.get("PublicIpAddress"):
                return instance["PublicIpAddress"]
    return None

def ssh(settings, ip: str, command: str, timeout: int = 90) -> subprocess.CompletedProcess:
    """Run a command on an instance over SSH with the lab's key pair."""
    key = ROOT / f"{settings.key_name}.pem"
    return subprocess.run(
        ["ssh", "-i", str(key), "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=10",
         f"ec2-user@{ip}", command],
        capture_output=True, text=True, timeout=timeout,
    )