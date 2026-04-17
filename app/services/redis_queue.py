from __future__ import annotations

import json
from typing import Iterator

from redis import Redis

from app.config import get_settings


def get_redis_client() -> Redis:
    settings = get_settings()
    return Redis.from_url(settings.redis_url, decode_responses=True)


def get_job_queue_name() -> str:
    return get_settings().redis_queue_name


def get_event_channel(job_id: str) -> str:
    settings = get_settings()
    return f"{settings.event_channel_prefix}:{job_id}"


def enqueue_job(job_id: str) -> None:
    redis_client = get_redis_client()
    redis_client.lpush(get_job_queue_name(), job_id)


def dequeue_job(timeout_seconds: int) -> str | None:
    redis_client = get_redis_client()
    item = redis_client.brpop(get_job_queue_name(), timeout=timeout_seconds)
    if not item:
        return None
    _, job_id = item
    return job_id


def publish_job_event(job_id: str, payload: dict) -> None:
    redis_client = get_redis_client()
    redis_client.publish(get_event_channel(job_id), json.dumps(payload, ensure_ascii=False))


def subscribe_job_events(job_id: str) -> Iterator[dict]:
    redis_client = get_redis_client()
    pubsub = redis_client.pubsub(ignore_subscribe_messages=True)
    pubsub.subscribe(get_event_channel(job_id))
    try:
        for message in pubsub.listen():
            data = message.get("data")
            if not data:
                continue
            try:
                yield json.loads(data)
            except json.JSONDecodeError:
                continue
    finally:
        pubsub.close()
