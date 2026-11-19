"""The Python smoke test: both tiers, through the load balancer.
Run after the targets are healthy:  pytest -m integration
"""
from datetime import datetime, timezone
import json
import os
import pytest
from tests.helpers import get_json, tier_url

pytestmark = pytest.mark.integration

CANDIDATE_ZIPS = ["60616", "10001", "90210", "98101", "33101", "60601", "94103", "02108", "30301", "77001"]
DEFAULT_ZIP = os.environ.get("SMOKE_ZIP", "60616")
UNKNOWN_ZIP = "00000"


def _today_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")

def _parse_history_zips(history_body) -> set[str]:
    """Parse plain-text /history output ('Count: N\\n{json}\\n...')."""
    if not isinstance(history_body, str):
        return set()
    zips = set()
    for line in history_body.splitlines():
        line = line.strip()
        if line.startswith("{"):
            try:
                row = json.loads(line)
                if "zip" in row:
                    zips.add(str(row["zip"]).strip())
            except ValueError:
                pass
    return zips

@pytest.fixture(scope="module")
def weather(settings, outputs) -> str:
    return tier_url(outputs, settings, "weather").rstrip("/")

@pytest.fixture(scope="module")
def advisor(settings, outputs) -> str:
    return tier_url(outputs, settings, "advisor").rstrip("/")

@pytest.fixture(scope="module")
def fresh_zip(weather) -> str:
    status, body = get_json(f"{weather}/history")
    recent = _parse_history_zips(body) if status == 200 else set()
    return next((z for z in CANDIDATE_ZIPS if z not in recent), DEFAULT_ZIP)

def test_weather_returns_morning_and_night_then_a_cache_hit(weather, fresh_zip):
    today = _today_str()
    status, first = get_json(f"{weather}/weather?zip={fresh_zip}&date={today}")
    assert status == 200, first
    assert "morning" in first and "night" in first
    assert {"zip", "city", "state", "date"} <= set(first)
    assert first["cache"] in ("miss", "hit"), f"cache={first.get('cache')}"

    status, second = get_json(f"{weather}/weather?zip={fresh_zip}&date={today}")
    assert status == 200, second
    assert second["cache"] == "hit", "a repeat call must be answered from the database"

def test_history_lists_the_saved_lookups(weather, fresh_zip):
    today = _today_str()
    get_json(f"{weather}/weather?zip={fresh_zip}&date={today}")
    status, body = get_json(f"{weather}/history")
    assert status == 200, body
    assert "Count:" in str(body)
    assert fresh_zip in _parse_history_zips(body)

def test_weather_rejects_a_bad_zip_with_400(weather):
    status, body = get_json(f"{weather}/weather?zip=M5V3L9")
    assert status == 400 and body["error"] == "invalid_zip"

def test_weather_returns_404_for_an_unknown_zip(weather):
    status, body = get_json(f"{weather}/weather?zip={UNKNOWN_ZIP}")
    assert status == 404 and body["error"] == "zip_not_found"

def test_advisor_returns_clothing_advice(advisor, fresh_zip):
    today = _today_str()
    query = f"?zip={fresh_zip}&date={today}&gender=neutral&email=student@hawk.illinoistech.edu"
    status, body = get_json(f"{advisor}/advice{query}")
    assert status == 200, body
    assert "morning" in body and "night" in body
    assert {"roadConditions", "suggestedDressing", "suggestedAccessories"} <= set(body["morning"])
    assert body["source"] in ("gemini", "fallback", "fallback_cap_exceeded")

def test_advice_came_from_gemini_not_the_fallback(advisor, fresh_zip):
    """Fails if Gemini quota or key has an issue; stack itself is healthy."""
    today = _today_str()
    query = f"?zip={fresh_zip}&date={today}&gender=neutral&email=student@hawk.illinoistech.edu"
    status, body = get_json(f"{advisor}/advice{query}")
    assert status == 200, body
    assert body["source"] == "gemini", f"source={body.get('source')} (check advisor journal for gemini_error)"

def test_advisor_rejects_a_bad_zip_with_400(advisor):
    today = _today_str()
    status, _ = get_json(f"{advisor}/advice?zip=M5V3L9&date={today}&gender=neutral&email=student@hawk.illinoistech.edu")
    assert status == 400

def test_advisor_passes_an_unknown_zip_through_as_404(advisor):
    today = _today_str()
    status, _ = get_json(f"{advisor}/advice?zip={UNKNOWN_ZIP}&date={today}&gender=neutral&email=student@hawk.illinoistech.edu")
    assert status == 404

def test_advisor_home_page_loads(advisor):
    status, body = get_json(f"{advisor}/")
    assert status == 200
    assert "<form" in str(body)

def test_advisor_page_escapes_what_it_prints(advisor):
    """Untrusted text injection must be sanitized safely before layout rendering."""
    today = _today_str()
    status, body = get_json(
        f"{advisor}/?zip=%3Cscript%3Ealert(1)%3C/script%3E&date={today}&gender=neutral&email=x@x.com"
    )
    assert status == 200
    assert "<script>alert(1)" not in str(body)