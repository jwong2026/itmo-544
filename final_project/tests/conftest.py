"""Shared fixtures. Unit tests use fake settings, integration tests use your real .env."""
from pathlib import Path
import pytest
from stack.clients import AwsClients
from stack.config import Settings, load_dotenv
from stack.outputs import StackOutputs

ROOT = Path(__file__).resolve().parent.parent

FAKE_VALUES = {
    "AWS_REGION": "us-east-2", "AZ_A": "us-east-2a", "AZ_B": "us-east-2b",
    "AMI_ID": "ami-12345678", "INSTANCE_TYPE": "t3.micro", "KEY_NAME": "test-key",
    "APP_SECURITY_GROUP_ID": "sg-placeholder",
    "WEATHER_ROLE_NAME": "t-weather-role", "WEATHER_PROFILE_NAME": "t-weather-profile",
    "WEATHER_LT_NAME": "t-weather-lt", "WEATHER_TG_NAME": "t-weather-tg",
    "WEATHER_ASG_NAME": "t-weather-asg", "WEATHER_LISTENER_PORT": "8080",
    "ADVISOR_ROLE_NAME": "t-advisor-role", "ADVISOR_PROFILE_NAME": "t-advisor-profile",
    "ADVISOR_LT_NAME": "t-advisor-lt", "ADVISOR_TG_NAME": "t-advisor-tg",
    "ADVISOR_ASG_NAME": "t-advisor-asg", "ADVISOR_LISTENER_PORT": "8081",
    "ALB_NAME": "t-alb", "ALB_SG_NAME": "t-alb-sg",
    "DB_INSTANCE_ID": "t-weather-db", "DB_NAME": "weather", "DB_USER": "weatherapp",
    "DB_SG_NAME": "t-weather-db-sg", "DB_SUBNET_GROUP_NAME": "t-weather-db-subnets",
    "DB_PASSWORD_PARAM": "/t/db-password",
    "GEMINI_PARAM_NAME": "/t/gemini-api-key", "GEMINI_MODEL": "gemini-test-model",
    "CONTACT_EMAIL": "you@example.com",
}

@pytest.fixture
def fake_settings(tmp_path):
    """Settings pointing at two tiny fake app folders, so no real files are needed."""
    for name in ("weather-app", "advisor-app"):
        folder = tmp_path / name
        folder.mkdir()
        (folder / "app.js").write_text(f"console.log('{name}');\n")
        (folder / "package.json").write_text('{"name": "%s"}\n' % name)
    return Settings.from_values(FAKE_VALUES, base_dir=tmp_path)

@pytest.fixture(scope="session")
def settings():
    return Settings.from_file(ROOT / ".env")

@pytest.fixture(scope="session")
def aws(settings):
    return AwsClients.create(settings.region)

@pytest.fixture(scope="session")
def outputs():
    try:
        return StackOutputs.load(ROOT)
    except FileNotFoundError:
        pytest.skip("stack_outputs.json not found. Run python3 create_weather_stack.py first.")

@pytest.fixture(scope="session")
def db_outputs():
    path = ROOT / "db_outputs.env"
    if not path.is_file():
        pytest.skip("db_outputs.env not found. Run python3 create_database.py first.")
    return load_dotenv(path)
