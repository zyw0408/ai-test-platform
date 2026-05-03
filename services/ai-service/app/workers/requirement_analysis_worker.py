from __future__ import annotations

import logging
import time

from app.cache import build_cache
from app.config import get_settings
from app.database import build_database
from app.services.analysis_queue import AnalysisQueueService
from app.services.providers import build_provider
from app.services.requirement_analysis import RequirementAnalysisService


logger = logging.getLogger(__name__)


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    settings = get_settings()
    db = build_database(settings)
    db.init_schema()
    cache = build_cache(settings)
    provider = build_provider(settings)
    service = RequirementAnalysisService(
        db=db,
        cache=cache,
        provider=provider,
        settings=settings,
    )
    queue = AnalysisQueueService(settings)
    queue.start_worker(service)
    logger.info("Requirement analysis worker started.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Requirement analysis worker stopping.")
        queue.stop_worker()


if __name__ == "__main__":
    main()
