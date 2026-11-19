import base64
import dataclasses
import gzip
import json
import re
import pytest
from stack.compute import MAX_USER_DATA_BYTES, build_user_data, launch_template_data
from stack.network import StackError
from tests.conftest import ROOT

ALB_DNS = "://amazonaws.com"
DB_HOST = "://amazonaws.com"


def test_app_files_are_embedded_and_round_trip(fake_settings):
    tier = fake_settings.weather
    script = build_user_data(fake_settings, tier, db_host=DB_HOST)
    assert script.startswith("#!/usr/bin/env python3"), "boot script must be pure Python (no bash)"
    app_b64 = re.search(r'APP_JS_B64 = "([A-Za-z0-9+/=]+)"', script).group(1)
    pkg_b64 = re.search(r'PACKAGE_JSON_B64 = "([A-Za-z0-9+/=]+)"', script).group(1)
    assert gzip.decompress(base64.b64decode(app_b64)).decode() == (tier.app_dir / "app.js").read_text()
    assert gzip.decompress(base64.b64decode(pkg_b64)).decode() == (tier.app_dir / "package.json").read_text()


def test_advisor_user_data_contains_the_alb_dns_name(fake_settings):
    """The ALB is created first so the advisor can be told where the weather tier is."""
    script = build_user_data(fake_settings, fake_settings.advisor, alb_dns=ALB_DNS)
    assert f"Environment=WEATHER_URL=http://{ALB_DNS}:8080" in script
    assert "Environment=GEMINI_PARAM_NAME=/t/gemini-api-key" in script
    assert "Environment=GEMINI_MODEL=gemini-test-model" in script
    assert "Environment=KEY_CACHE_SECONDS=60" in script
    assert "Environment=CONTACT_EMAIL=you@example.com" in script
    assert "DB_HOST" not in script, "the advisor never touches the database"


def test_weather_user_data_contains_the_database_host(fake_settings):
    script = build_user_data(fake_settings, fake_settings.weather, db_host=DB_HOST)
    assert f"Environment=DB_HOST={DB_HOST}" in script
    assert "Environment=DB_NAME=weather" in script
    assert "Environment=DB_USER=weatherapp" in script
    assert "Environment=DB_PASSWORD_PARAM=/t/db-password" in script
    assert "Environment=CACHE_SECONDS=600" in script
    assert 'PACKAGES = ["nodejs", "postgresql15"]' in script
    assert "/opt/app/rds-ca.pem" in script


def test_nws_user_agent_is_quoted_because_it_contains_spaces(fake_settings):
    """systemd would split an unquoted value at the space, so the whole assignment must be in quotes."""
    script = build_user_data(fake_settings, fake_settings.weather, db_host=DB_HOST)
    unit_json = re.search(r'SERVICE_UNIT = (".*")', script).group(1)
    unit_text = json.loads(unit_json)
    lines = [line for line in unit_text.splitlines() if "NWS_USER_AGENT" in line]
    assert len(lines) == 1
    line = lines[0]
    assert re.fullmatch(r'Environment="NWS_USER_AGENT=\(.*\)"', line), line
    assert fake_settings.contact_email in line
    assert " " in line.split("=", 1)[1]


def test_no_secret_values_can_appear_in_user_data(fake_settings):
    """Only parameter NAMES go into user-data. The values are read from SSM at run time."""
    for tier, kwargs in ((fake_settings.weather, {"db_host": DB_HOST}), (fake_settings.advisor, {"alb_dns": ALB_DNS})):
        script = build_user_data(fake_settings, tier, **kwargs)
        assert "AIza" not in script
        assert "GEMINI_API_KEY" not in script
        assert "DB_PASSWORD=" not in script


def test_the_advisor_cannot_be_built_before_the_alb_exists(fake_settings):
    with pytest.raises(StackError, match="ALB"):
        build_user_data(fake_settings, fake_settings.advisor)


def test_the_weather_tier_cannot_be_built_without_a_database(fake_settings):
    with pytest.raises(StackError, match="database"):
        build_user_data(fake_settings, fake_settings.weather)


def test_launch_template_user_data_is_base64_of_the_script(fake_settings):
    data = launch_template_data(fake_settings, fake_settings.advisor, alb_dns=ALB_DNS)
    decoded = base64.b64decode(data["UserData"]).decode()
    assert decoded == build_user_data(fake_settings, fake_settings.advisor, alb_dns=ALB_DNS)
    assert data["IamInstanceProfile"] == {"Name": "t-advisor-profile"}
    assert data["SecurityGroupIds"] == ["sg-placeholder"]


@pytest.mark.parametrize("tier_name,kwargs", [("weather", {"db_host": DB_HOST}), ("advisor", {"alb_dns": ALB_DNS})])
def test_user_data_is_under_16_kb_for_the_fake_apps(fake_settings, tier_name, kwargs):
    script = build_user_data(fake_settings, fake_settings.tier(tier_name), **kwargs)
    assert len(script.encode()) < MAX_USER_DATA_BYTES


@pytest.mark.parametrize("tier_name,kwargs", [("weather", {"db_host": DB_HOST}), ("advisor", {"alb_dns": ALB_DNS})])
def test_user_data_is_under_16_kb_for_your_real_apps(fake_settings, tier_name, kwargs):
    app_dir = ROOT / f"{tier_name}-app"
    if not (app_dir / "app.js").is_file():
        pytest.skip(f"{app_dir} not found (create it in Part D)")
    real = dataclasses.replace(fake_settings.tier(tier_name), app_dir=app_dir)
    script = build_user_data(fake_settings, real, **kwargs)
    assert len(script.encode()) < MAX_USER_DATA_BYTES, f"{tier_name} user-data is {len(script.encode())} bytes"


def test_user_data_over_the_limit_is_refused(fake_settings):
    # Use high-entropy random bytes so gzip cannot compress 20 KB down below 16 KB
    import os
    (fake_settings.weather.app_dir / "app.js").write_bytes(os.urandom(20000))
    with pytest.raises(StackError, match="16 KB"):
        launch_template_data(fake_settings, fake_settings.weather, db_host=DB_HOST)
