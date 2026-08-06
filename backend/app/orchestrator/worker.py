from __future__ import annotations

import logging
import threading
import time

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.redis import redis_client
from app.orchestrator.orchestrator import orchestrator

logger = logging.getLogger(__name__)


class QueueWorker:
    """
    Background consumer of the task queue. Runs one or more threads that
    poll the Redis queue and hand work to the orchestrator.

    When Redis is unavailable the worker idles (the orchestrator then runs
    tasks inline, so the platform stays functional without it).
    """

    def __init__(self, workers: int | None = None) -> None:
        self.workers = workers or settings.orchestrator_workers
        self._threads: list[threading.Thread] = []
        self._stop = threading.Event()

    def start(self) -> None:
        if not redis_client.available:
            logger.warning("Redis недоступен: воркеры не запущены, задачи выполняются синхронно.")
            return
        logger.info("Запуск %d воркеров очереди задач", self.workers)
        for _ in range(self.workers):
            thread = threading.Thread(target=self._run, daemon=True)
            thread.start()
            self._threads.append(thread)

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        while not self._stop.is_set():
            db = SessionLocal()
            try:
                orchestrator.poll(db)
            except Exception:  # pragma: no cover - worker must survive errors
                logger.exception("Ошибка в воркере очереди")
                db.rollback()
            finally:
                db.close()
            time.sleep(0.05)


worker = QueueWorker()
