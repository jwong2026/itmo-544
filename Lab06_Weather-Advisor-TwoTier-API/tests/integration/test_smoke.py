import os
import pytest
import requests
from tests.helpers import tier_url, get_json

pytestmark = pytest.mark.integration

ZIP = os.environ.get("SMOKE_ZIP", "60616")
UNKNOWN_ZIP = "00000"

@pytest.fixture(scope="module")
def weather(settings, outputs) -> str:
    """Base URL of the weather tier, without a trailing slash."""
    return tier_url(outputs, settings, "weather").rstrip("/")

@pytest.fixture(scope="module")
def advisor(settings, outputs) -> str:
    """Base URL of the advisor tier, without a trailing slash."""
    return tier_url(outputs, settings, "advisor").rstrip("/")

@pytest.fixture(scope="module")
def first_weather_call(weather):
    """The first /weather call for ZIP. Made once, so the cache check below can follow it."""
    return get_json(f"{weather}/weather?zip={ZIP}")

@pytest.fixture(scope="module")
def advice_call(advisor):
    """One /advice call, shared by the two advisor checks so Gemini is asked only once."""
    return get_json(f"{advisor}/advice?zip={ZIP}")

def test_weather_tier_returns_a_forecast(first_weather_call):
    status, body = first_weather_call
    assert status == 200, body
    assert "forecast" in body
    assert {"zip", "city", "state"} <= set(body)

def test_a_repeat_call_is_answered_from_the_database(first_weather_call, weather):
    """The first call saved the lookup, so the second must be a cache hit."""
    status, body = get_json(f"{weather}/weather?zip={ZIP}")
    assert status == 200, body
    assert body.get("cache") == "hit", (
        f"cache={body.get('cache')!r}. 'unavailable' or 'disabled' means the weather tier "
        "cannot use the database: read its journal and look for db_error."
    )

def test_history_lists_the_saved_lookups(first_weather_call, weather):
    status, body = get_json(f"{weather}/history")
    assert status == 200, body
    assert body["count"] >= 1
    assert ZIP in [row["zip"] for row in body["lookups"]]

def test_weather_tier_rejects_a_bad_zip_with_400(weather):
    status, _ = get_json(f"{weather}/weather?zip=abc")
    assert status == 400

def test_weather_tier_returns_404_for_an_unknown_zip(weather):
    status, _ = get_json(f"{weather}/weather?zip={UNKNOWN_ZIP}")
    assert status == 404

def test_advisor_returns_clothing_advice(advice_call):
    status, body = advice_call
    assert status == 200, body
    assert body.get("advice"), "the advisor answered but gave no advice text"
    assert body.get("source") in {"gemini", "fallback"}

def test_advice_came_from_gemini_not_the_fallback(advice_call):
    """Fails when the key, the free-tier quota or GEMINI_MODEL needs attention. The stack itself is fine."""
    status, body = advice_call
    assert status == 200, body
    assert body.get("source") == "gemini", (
        "source is 'fallback'. On the advisor instance run: "
        "sudo journalctl -u advisor --no-pager | grep gemini_error"
    )

def test_advisor_rejects_a_bad_zip_with_400(advisor):
    status, _ = get_json(f"{advisor}/advice?zip=abc")
    assert status == 400

def test_advisor_home_page_loads(advisor):
    """The page stays up (200) even if the weather tier is down, so the ALB keeps the instance."""
    status, body = get_json(f"{advisor}/")
    assert status == 200
    assert "<form" in str(body)