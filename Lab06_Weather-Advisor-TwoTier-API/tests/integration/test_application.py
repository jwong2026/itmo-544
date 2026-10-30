"""The Python smoke test: both tiers, through the load balancer.
Run after the targets are healthy:  pytest -m integration
"""
import pytest
from tests.helpers import get_json, tier_url

pytestmark = pytest.mark.integration

# Real zip codes, so the upstream APIs know them. We pick one that is not in /history yet.
CANDIDATE_ZIPS = ["60616", "10001", "90210", "98101", "33101", "60601", "94103", "02108", "30301", "77001"]

@pytest.fixture(scope="module")
def weather(settings, outputs):
    return tier_url(outputs, settings, "weather").rstrip("/")

@pytest.fixture(scope="module")
def advisor(settings, outputs):
    return tier_url(outputs, settings, "advisor").rstrip("/")

@pytest.fixture(scope="module")
def fresh_zip(weather):
    """A zip that was not looked up recently, so the first call is a real miss."""
    status, body = get_json(f"{weather}/history")
    recent = {item["zip"].strip() for item in body.get("lookups", [])} if status == 200 else set()
    return next((z for z in CANDIDATE_ZIPS if z not in recent), CANDIDATE_ZIPS[0])

def test_weather_returns_a_forecast_then_a_cache_hit(weather, fresh_zip):
    status, first = get_json(f"{weather}/weather?zip={fresh_zip}")
    assert status == 200 and "forecast" in first
    assert first["cache"] in ("miss", "hit"), f"cache={first.get('cache')} (unavailable means the database is not working)"
    status, second = get_json(f"{weather}/weather?zip={fresh_zip}")
    assert status == 200
    assert second["cache"] == "hit", "a repeat call must be answered from the database"

def test_first_call_for_a_fresh_zip_is_a_miss(weather, settings):
    """Only meaningful if a zip was available that is not cached yet; otherwise it is skipped."""
    status, body = get_json(f"{weather}/history")
    recent = {item["zip"].strip() for item in body.get("lookups", [])} if status == 200 else set()
    unused = [z for z in CANDIDATE_ZIPS if z not in recent]
    if not unused:
        pytest.skip("every candidate zip was looked up recently; wait CACHE_SECONDS and re-run")
    status, first = get_json(f"{weather}/weather?zip={unused[0]}")
    assert status == 200 and first["cache"] == "miss"
    status, second = get_json(f"{weather}/weather?zip={unused[0]}")
    assert second["cache"] == "hit"

def test_history_lists_the_saved_lookups(weather, fresh_zip):
    get_json(f"{weather}/weather?zip={fresh_zip}")
    status, body = get_json(f"{weather}/history")
    assert status == 200 and body["count"] >= 1
    assert fresh_zip in {item["zip"].strip() for item in body["lookups"]}

def test_weather_rejects_a_bad_zip_with_400(weather):
    status, body = get_json(f"{weather}/weather?zip=abc")
    assert status == 400 and body["error"] == "invalid_zip"

def test_weather_returns_404_for_an_unknown_zip(weather):
    status, body = get_json(f"{weather}/weather?zip=00000")
    assert status == 404 and body["error"] == "zip_not_found"

def test_advisor_returns_clothing_advice(advisor, fresh_zip):
    status, body = get_json(f"{advisor}/advice?zip={fresh_zip}")
    assert status == 200 and body.get("advice")
    assert body["source"] in ("gemini", "fallback")

def test_advice_came_from_gemini_not_the_fallback(advisor, fresh_zip):
    """If only this test fails, the stack is fine: check the key, the model name or the free-tier quota."""
    status, body = get_json(f"{advisor}/advice?zip={fresh_zip}")
    assert status == 200
    assert body["source"] == "gemini", "fallback answers mean a gemini_error in the advisor journal"

def test_advisor_rejects_a_bad_zip_with_400(advisor):
    status, _ = get_json(f"{advisor}/advice?zip=abc")
    assert status == 400

def test_advisor_passes_an_unknown_zip_through_as_404(advisor):
    status, _ = get_json(f"{advisor}/advice?zip=00000")
    assert status == 404

def test_advisor_home_page_loads(advisor):
    status, body = get_json(f"{advisor}/")
    assert status == 200 and "<form" in str(body)

def test_advisor_page_escapes_what_it_prints(advisor):
    """AI and user text is untrusted: markup in the zip must never come back as markup."""
    status, body = get_json(f"{advisor}/?zip=%3Cscript%3Ealert(1)%3C/script%3E")
    assert status == 200
    assert "<script>alert(1)" not in str(body)