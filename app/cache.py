from __future__ import annotations

import json
from contextlib import suppress

import redis

from app.config import get_settings

settings = get_settings()


class CacheClient:
    def __init__(self) -> None:
        self.enabled = settings.enable_redis
        self._client = redis.from_url(settings.redis_url, decode_responses=True) if self.enabled else None

    def get_json(self, key: str) -> dict | list | str | int | float | None:
        if not self._client:
            return None
        value = self._client.get(key)
        return json.loads(value) if value else None

    def set_json(self, key: str, value: object, ttl_seconds: int = 60) -> None:
        if not self._client:
            return
        self._client.set(key, json.dumps(value), ex=ttl_seconds)

    def delete(self, key: str) -> None:
        if not self._client:
            return
        with suppress(Exception):
            self._client.delete(key)

    def ping(self) -> bool:
        if not self._client:
            return False
        try:
            return bool(self._client.ping())
        except Exception:
            return False


cache = CacheClient()

