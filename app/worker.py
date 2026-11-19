"""Run `python -m app.worker` (one worker) or add `--once` for a single scan."""

import argparse
import json
import logging

from apscheduler.schedulers.blocking import BlockingScheduler
from sqlalchemy.orm import Session

from app.db import get_engine
from app.deadlines import scan_deadlines
from app.models import utc_now

logger = logging.getLogger("resolvedesk.worker")


def run_check():
    try:
        with Session(get_engine()) as session:
            result = scan_deadlines(session, utc_now())
        logger.info("Deadline scan: created=%d busy=%s", result["created"], result["busy"])
        return result
    except Exception:
        # Do not log SQL parameters, credentials, or customer text on failure.
        logger.error(
            "Deadline scan failed; check configuration, migrations, and database availability"
        )
        return None


def main():
    parser = argparse.ArgumentParser(description="ResolveDesk internal deadline scanner")
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    result = run_check()  # Catch up immediately on process start/restart.
    if args.once:
        if result is None:
            raise SystemExit(1)
        print(json.dumps(result))
        return
    scheduler = BlockingScheduler(timezone="UTC")
    scheduler.add_job(
        run_check, "interval", seconds=60, max_instances=1, coalesce=True, misfire_grace_time=60
    )
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        pass


if __name__ == "__main__":
    main()
