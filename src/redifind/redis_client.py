from __future__ import annotations

from redis import Redis


def get_client(redis_url: str) -> Redis:
    return Redis.from_url(redis_url, decode_responses=True)
