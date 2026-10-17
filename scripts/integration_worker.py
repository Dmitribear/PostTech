"""python -m scripts.integration_worker [--once]; opt-in destinations only."""
import argparse
import logging
import time
from dotenv import load_dotenv
from app.services.integrations import run_once

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--once',action='store_true')
    args=parser.parse_args()
    load_dotenv(override=False)
    while True:
        try:
            run_once()
        except Exception:
            # Do not log secrets, payloads or upstream response bodies.
            logging.error('Delivery cycle failed; leased events will be retried')
            if args.once:
                raise SystemExit(1)
        if args.once:
            break
        time.sleep(5)

if __name__=='__main__':
    main()
