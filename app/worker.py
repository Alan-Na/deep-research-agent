from __future__ import annotations

from app.config import get_settings
from app.db import init_db
from app.services.job_service import process_investment_job
from app.services.redis_queue import dequeue_job
from app.utils.logging import configure_logging, get_logger

configure_logging()
logger = get_logger(__name__)


def main() -> None:
    settings = get_settings()
    init_db(reset=False)
    logger.info("Worker started. Waiting for jobs on queue=%s", settings.redis_queue_name)
    while True:
        job_id = dequeue_job(settings.worker_poll_timeout_seconds)
        if not job_id:
            continue
        logger.info("Worker picked up job_id=%s", job_id)
        process_investment_job(job_id)


if __name__ == "__main__":
    main()
