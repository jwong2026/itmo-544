import pytest
from stack.config import ConfigError, Settings, load_dotenv
from tests.conftest import FAKE_VALUES

def test_load_dotenv_skips_comments_and_blank_lines(tmp_path):
    env = tmp_path / ".env"
    env.write_text("# a comment\n\nAWS_REGION=us-east-2\nKEY_NAME='quoted'\n")
    assert load_dotenv(env) == {"AWS_REGION": "us-east-2", "KEY_NAME": "quoted"}

def test_missing_keys_are_named_in_the_error():
    values = dict(FAKE_VALUES)
    del values["ALB_NAME"]
    del values["DB_PASSWORD_PARAM"]
    with pytest.raises(ConfigError) as err:
        Settings.from_values(values)
    assert "ALB_NAME" in str(err.value) and "DB_PASSWORD_PARAM" in str(err.value)

def test_tiers_are_built_from_prefixed_keys(fake_settings):
    weather, advisor = fake_settings.tiers
    assert (weather.name, weather.listener_port, weather.asg_name) == ("weather", 8080, "t-weather-asg")
    assert (advisor.name, advisor.listener_port, advisor.lt_name) == ("advisor", 8081, "t-advisor-lt")
    assert weather.policy_name == "t-weather-role-policy"
    assert weather.app_dir.name == "weather-app"

def test_database_and_gemini_settings(fake_settings):
    assert fake_settings.db_instance_id == "t-weather-db"
    assert fake_settings.db_user == "weatherapp"
    assert fake_settings.gemini_param_name == "/t/gemini-api-key"
    assert fake_settings.contact_email == "you@example.com"

def test_each_tier_gets_exactly_its_own_secret(fake_settings):
    assert fake_settings.secret_param_for(fake_settings.weather) == "/t/db-password"
    assert fake_settings.secret_param_for(fake_settings.advisor) == "/t/gemini-api-key"

def test_numbers_are_integers_with_defaults(fake_settings):
    assert isinstance(fake_settings.weather.listener_port, int)
    assert (fake_settings.cache_seconds, fake_settings.key_cache_seconds) == (600, 60)
    custom = Settings.from_values(dict(FAKE_VALUES, CACHE_SECONDS="30", KEY_CACHE_SECONDS="5"))
    assert (custom.cache_seconds, custom.key_cache_seconds) == (30, 5)

@pytest.mark.parametrize("key", ["WEATHER_LISTENER_PORT", "CACHE_SECONDS"])
def test_a_bad_number_names_the_key(key):
    with pytest.raises(ConfigError) as err:
        Settings.from_values(dict(FAKE_VALUES, **{key: "fast"}))
    assert key in str(err.value)

def test_the_two_zones_must_differ():
    with pytest.raises(ConfigError, match="different availability zones"):
        Settings.from_values(dict(FAKE_VALUES, AZ_B=FAKE_VALUES["AZ_A"]))