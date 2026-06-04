"""
Celery 应用配置

使用项目现有的 Redis 作为 Broker 和 Result Backend。
Worker 启动命令：celery -A app.celery_app worker --loglevel=info --concurrency=2
"""
import os
from celery import Celery

REDIS_HOST = os.getenv("REDIS_HOST", "127.0.0.1")
REDIS_PORT = os.getenv("REDIS_PORT", "6379")
REDIS_DB = os.getenv("CELERY_REDIS_DB", "1")
BROKER_URL = f"redis://{REDIS_HOST}:{REDIS_PORT}/{REDIS_DB}"

celery_app = Celery(
    "modelhub",
    broker=BROKER_URL,
    backend=BROKER_URL,
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_soft_time_limit=300,
    task_time_limit=600,
    task_default_retry_delay=10,
    task_max_retries=3,
)

celery_app.autodiscover_tasks(["app.tasks"])
