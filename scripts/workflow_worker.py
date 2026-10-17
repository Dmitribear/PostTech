"""Idempotent portal reminders and automatic next learning steps; no email sending."""

import argparse
import logging
import time

from dotenv import load_dotenv
from app.bootstrap import configure_application
from app.application.use_cases.academy import data_gateway, execute_query


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    load_dotenv(override=False)
    configure_application()
    while True:
        try:
            result = execute_query(data_gateway().rpc("run_workflow_reminders", {}))
            logging.warning(
                "Workflow cycle: sent=%s advanced=%s",
                result.get("sent", 0),
                result.get("advanced", 0),
            )
        except Exception:
            logging.error(
                "Workflow cycle failed; check database migrations and connectivity"
            )
            if args.once:
                raise SystemExit(1)
        if args.once:
            break
        time.sleep(60)


if __name__ == "__main__":
    main()
