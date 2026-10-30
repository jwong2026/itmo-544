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
from stack.runner import delete_stack

log = logging.getLogger("stack")

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env", default=".env", help="path to the settings file")
    parser.add_argument("--dry-run", action="store_true", help="check prerequisites and stop before creating anything")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    settings = Settings.from_file(args.env)
    delete_stack(settings, AwsClients.create(settings.region))

    log.info("Next: python3 delete_database.py")

if __name__ == "__main__":
    main()
