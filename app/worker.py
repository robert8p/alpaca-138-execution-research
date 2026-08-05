from __future__ import annotations

import logging
import signal
import sys
import time

from app.config import get_settings
from app.db import close_pool, open_pool
from app.orchestrator import advance_all
from app.processors import process_partition
from app.queue import claim, fail

settings = get_settings()
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("alpaca_138.worker")
_running = True


def _stop(signum, _frame) -> None:
    global _running
    logger.info("Stop requested", extra={"signal": signum})
    _running = False


def main() -> None:
    settings.validate_worker()
    settings.ensure_temp_dir()
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    open_pool()
    logger.info("Research worker started", extra={"version": "1.1.1"})
    try:
        while _running:
            try:
                advance_all()
                partition = claim()
                if partition is None:
                    time.sleep(settings.worker_poll_seconds)
                    continue
                logger.info(
                    "Processing partition",
                    extra={
                        "partition_id": str(partition["id"]),
                        "run_id": str(partition["run_id"]),
                        "stage": partition["stage"],
                        "partition_key": partition["partition_key"],
                        "attempt": partition["attempts"],
                    },
                )
                try:
                    process_partition(partition)
                    logger.info("Partition completed", extra={"partition_id": str(partition["id"])})
                except BaseException as exc:  # partition failures must be checkpointed before loop continues
                    logger.exception("Partition failed", extra={"partition_id": str(partition["id"])})
                    fail(partition, exc)
            except BaseException:
                logger.exception("Worker loop error")
                time.sleep(min(30.0, settings.worker_poll_seconds * 5))
    finally:
        close_pool()
        logger.info("Research worker stopped")


if __name__ == "__main__":
    main()
