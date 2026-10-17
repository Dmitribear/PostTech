"""Idempotent portal reminders and automatic next learning steps; no email sending."""
import argparse
import logging
import time

from dotenv import load_dotenv
from app.services.academy import _client, _execute


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--once', action='store_true')
    args = parser.parse_args()
    load_dotenv(override=False)
    while True:
        try:
            result = _execute(_client().rpc('run_workflow_reminders', {}))
            logging.warning('Workflow cycle: sent=%s advanced=%s', result.get('sent',0), result.get('advanced',0))
        except Exception:
            logging.error('Workflow cycle failed; check database migrations and connectivity')
            if args.once:
                raise SystemExit(1)
        if args.once:
            break
        time.sleep(60)


if __name__ == '__main__':
    main()
