#!/usr/bin/env python3
import argparse
import logging
import json
import time
from pathlib import Path
from botocore.exceptions import ClientError
from stack.clients import AwsClients
from stack.config import Settings, load_dotenv
from stack.util import error_code
from stack.runner import create_stack

log = logging.getLogger("stack")

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env", default=".env", help="path to the settings file")
    parser.add_argument("--dry-run", action="store_true", help="check prerequisites and stop before creating anything")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    settings = Settings.from_file(args.env)
    outputs = create_stack(settings, AwsClients.create(settings.region), dry_run=args.dry_run)
    outputs.save()
    if args.dry_run:
        print("\n[DRY RUN COMPLETE] No live AWS modificiations were committed.")
    else:
        print()
        print(f"Weather: http://{outputs.alb_dns_name}:{settings.weather.listener_port}/weather?zip=60616 (saved lookups: /history)")
        print(f"Advisor: http://{outputs.alb_dns_name}:{settings.advisor.listener_port}/")
        print("Give the target groups 2 to 3 minutes to report healthy (the first boot installs Node and your app).")

if __name__ == "__main__":
    main()
