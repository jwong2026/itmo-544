#!/usr/bin/env python3
"""
Cost Control tracking analyzer for the Weather Advisor deployment stack.
Ensures total development session costs remain well below the $2.00 threshold.
"""
import argparse
import sys
from datetime import datetime, timezone
from stack.clients import AwsClients
from stack.config import Settings

HOURLY_STACK_RATE = 0.07        # Combined ALB, Public IPv4, and micro instances rate
HOURLY_RDS_RATE = 0.016         # RDS db.t4g.micro Single-AZ PostgreSQL rate (us-east-2)
HOURLY_DDB_RATE = 0.001         # DynamoDB on-demand small workload estimate
BUDGET_CAP = 2.00               # Goal for the budget is $2.00

def fetch_live_gemini_calls(settings: Settings) -> int | None:
    """Query DynamoDB LookupsCounter for today's recorded Gemini API call count."""
    try:
        aws = AwsClients.create(settings.region)
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        res = aws.dynamodb.get_item(
            TableName=settings.advisor_table_name,
            Key={"PK": {"S": f"DAILY_CAP#{today}"}},
        )
        item = res.get("Item")
        if item and "call_count" in item:
            return int(item["call_count"]["N"])
        return 0
    except Exception:
        return None

def calculate_session_spend(hours_run: float, gemini_calls: int, rds_hours: float = None) -> dict:
    """Computes specific costs based on runtime hours and API call tallies."""
    active_rds_hours = hours_run if rds_hours is None else rds_hours
    infra_cost = round(hours_run * (HOURLY_STACK_RATE + HOURLY_DDB_RATE), 4)
    rds_cost = round(active_rds_hours * HOURLY_RDS_RATE, 4)
    gemini_cost = 0.00
    total_cost = round(infra_cost + rds_cost + gemini_cost, 4)

    return {
        "hours_tracked": hours_run,
        "rds_hours_tracked": active_rds_hours,
        "gemini_calls": gemini_calls,
        "infrastructure_cost": infra_cost,
        "rds_cost": rds_cost,
        "gemini_cost": gemini_cost,
        "total_cost": total_cost,
        "remaining_budget": round(BUDGET_CAP - total_cost, 4),
    }

def main() -> int:
    parser = argparse.ArgumentParser(description="Track Weather Advisor stack uptime and Gemini API budget.")
    parser.add_argument("--env", default=".env", help="Path to the .env settings file")
    parser.add_argument("--hours", type=float, required=True, help="Total hours the EC2/ALB stack ran")
    parser.add_argument("--rds-hours", type=float, default=None, help="Total hours RDS ran (defaults to --hours)")
    parser.add_argument("--calls", type=int, default=None, help="Override Gemini call count (otherwise read from DynamoDB)")
    args = parser.parse_args()

    settings = Settings.from_file(args.env)
    calls = args.calls if args.calls is not None else fetch_live_gemini_calls(settings)
    if calls is None:
        calls = 0

    metrics = calculate_session_spend(args.hours, calls, args.rds_hours)

    print(f"Stack Active Uptime: {metrics['hours_tracked']} hours")
    print(f"RDS Active Uptime: {metrics['rds_hours_tracked']} hours")
    print(f"Gemini API Invocations: {metrics['gemini_calls']} requests (Free Tier)")
    print("-" * 50)
    print(f"AWS Stack Cost (EC2/ALB/DDB): ${metrics['infrastructure_cost']:.2f}")
    print(f"AWS RDS Cost (PostgreSQL): ${metrics['rds_cost']:.2f}")
    print(f"Gemini Service Cost: ${metrics['gemini_cost']:.2f}")
    print(f"Total Combined Spend: ${metrics['total_cost']:.2f}")
    print(f"Remaining Project Cap: ${metrics['remaining_budget']:.2f}")
    print("=" * 50)

    if metrics["total_cost"] > BUDGET_CAP:
        print("WARNING: Stack operational spend has exceeded the $2.00 target budget limit!")
        return 1
    print("SUCCESS: Project development spend is within safe cost limits.")
    return 0

if __name__ == "__main__":
    sys.exit(main())