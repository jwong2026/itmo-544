"""End-to-end edge-case and 10-item report contract checks against the live ALB."""
from datetime import datetime, timedelta, timezone
import pytest
from tests.helpers import get_json, tier_url

pytestmark = pytest.mark.integration

EXPECTED_10_FIELDS = {
    "temperature",
    "windSpeed",
    "visibility",
    "uv",
    "humidity",
    "rainCategory",
    "snowCategory",
    "roadConditions",
    "suggestedDressing",
    "suggestedAccessories",
}


def _date_offset(days: int) -> str:
    dt = datetime.now(timezone.utc) + timedelta(days=days)
    return dt.strftime("%Y-%m-%d")


@pytest.fixture(scope="module")
def weather(settings, outputs) -> str:
    return tier_url(outputs, settings, "weather").rstrip("/")


@pytest.fixture(scope="module")
def advisor(settings, outputs) -> str:
    return tier_url(outputs, settings, "advisor").rstrip("/")


@pytest.mark.parametrize("non_us_code", ["M5V3L9", "SW1A1AA", "1234", "123456"])
def test_refuses_non_us_and_malformed_postal_codes(weather, advisor, non_us_code):
    """Section 5.4: Non-US postal codes and malformed ZIPs must return 400."""
    today = _date_offset(0)
    w_status, w_body = get_json(f"{weather}/weather?zip={non_us_code}&date={today}")
    assert w_status == 400 and w_body.get("error") == "invalid_zip"

    a_status, a_body = get_json(
        f"{advisor}/advice?zip={non_us_code}&date={today}&gender=neutral&email=student@hawk.illinoistech.edu"
    )
    assert a_status == 400 and a_body.get("error") == "invalid_zip"


@pytest.mark.parametrize("bad_date", [_date_offset(-5), _date_offset(10), "2026-02-30", "not-a-date"])
def test_advisor_rejects_dates_outside_7_day_window(advisor, bad_date):
    """Section 5.4: Past dates, far-future dates, and impossible dates must return 400."""
    status, body = get_json(
        f"{advisor}/advice?zip=60616&date={bad_date}&gender=neutral&email=student@hawk.illinoistech.edu"
    )
    assert status == 400 and body.get("error") == "invalid_date"


def test_advisor_rejects_invalid_gender_and_email(advisor):
    """Section 5.4: Unlisted clothing categories and bad emails must return 400."""
    today = _date_offset(0)
    s1, b1 = get_json(
        f"{advisor}/advice?zip=60616&date={today}&gender=custom&email=student@hawk.illinoistech.edu"
    )
    assert s1 == 400 and b1.get("error") == "invalid_gender"

    s2, b2 = get_json(
        f"{advisor}/advice?zip=60616&date={today}&gender=neutral&email=invalid-email"
    )
    assert s2 == 400 and b2.get("error") == "invalid_email"


def test_full_report_contains_all_10_items_for_morning_and_night(advisor):
    """Section 6: Verify both Morning and Night objects contain all 10 required report fields."""
    today = _date_offset(0)
    status, body = get_json(
        f"{advisor}/advice?zip=60616&date={today}&gender=menswear&email=student@hawk.illinoistech.edu"
    )
    assert status == 200, body
    assert EXPECTED_10_FIELDS <= set(body.get("morning", {}).keys())
    assert EXPECTED_10_FIELDS <= set(body.get("night", {}).keys())
