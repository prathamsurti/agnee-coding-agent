import json
import time
from typing import Optional, Dict, Any
import redis.asyncio as aioredis
from .config import settings

class RedisManager:
    def __init__(self, url: str):
        self.url = url
        self.client: Optional[aioredis.Redis] = None
        self._fallback_store: Dict[str, Any] = {}
        self._fallback_expirations: Dict[str, float] = {}

    async def connect(self):
        try:
            self.client = aioredis.from_url(
                self.url, 
                decode_responses=True, 
                socket_timeout=2.0
            )
            await self.client.ping()
        except Exception:
            # Fallback to in-memory store if Redis container isn't reached yet
            self.client = None

    async def close(self):
        if self.client:
            await self.client.close()

    async def set_json(self, key: str, value: Any, ttl: int):
        if self.client:
            try:
                await self.client.set(key, json.dumps(value), ex=ttl)
                return
            except Exception:
                pass
        self._fallback_store[key] = json.dumps(value)
        self._fallback_expirations[key] = time.time() + ttl

    async def get_json(self, key: str) -> Optional[Any]:
        if self.client:
            try:
                val = await self.client.get(key)
                return json.loads(val) if val else None
            except Exception:
                pass
        # Check fallback
        if key in self._fallback_store:
            if time.time() < self._fallback_expirations.get(key, 0):
                return json.loads(self._fallback_store[key])
            else:
                del self._fallback_store[key]
                self._fallback_expirations.pop(key, None)
        return None

    async def set_str(self, key: str, value: str, ttl: int):
        if self.client:
            try:
                await self.client.set(key, value, ex=ttl)
                return
            except Exception:
                pass
        self._fallback_store[key] = value
        self._fallback_expirations[key] = time.time() + ttl

    async def get_str(self, key: str) -> Optional[str]:
        if self.client:
            try:
                return await self.client.get(key)
            except Exception:
                pass
        if key in self._fallback_store:
            if time.time() < self._fallback_expirations.get(key, 0):
                return str(self._fallback_store[key])
            else:
                del self._fallback_store[key]
                self._fallback_expirations.pop(key, None)
        return None

    async def delete(self, key: str):
        if self.client:
            try:
                await self.client.delete(key)
                return
            except Exception:
                pass
        self._fallback_store.pop(key, None)
        self._fallback_expirations.pop(key, None)

    async def check_rate_limit(self, ip: str, limit: int = 10, window: int = 60) -> bool:
        """Returns True if within limit, False if rate limited."""
        key = f"ratelimit:auth:{ip}"
        now = time.time()
        if self.client:
            try:
                current = await self.client.incr(key)
                if current == 1:
                    await self.client.expire(key, window)
                return current <= limit
            except Exception:
                pass
        # Fallback in-memory rate limiter
        counts = self._fallback_store.get(key, 0) + 1
        self._fallback_store[key] = counts
        return counts <= limit

redis_mgr = RedisManager(settings.REDIS_URL)
