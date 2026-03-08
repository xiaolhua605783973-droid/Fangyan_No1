import json
from typing import Optional

import redis as redis_lib

from core.asr_adapter import ASRResult
from core.logger import get_logger

logger = get_logger(__name__)


class ASRCache:
    """
    基于 Redis 的 ASR 结果缓存。
    缓存键为音频 SHA-256 哈希，避免相同音频重复调用商业 ASR API。
    """

    def __init__(self, redis_url: str, ttl: int = 86400):
        self._client = redis_lib.from_url(redis_url, decode_responses=True)
        self._ttl = ttl

    async def get(self, audio_hash: str) -> Optional[ASRResult]:
        """获取缓存的 ASR 结果，未命中返回 None"""
        try:
            value = self._client.get(f"asr:{audio_hash}")
            if value:
                data = json.loads(value)
                return ASRResult(**data)
        except Exception as e:
            logger.warning("cache_get_failed", audio_hash=audio_hash[:8], error=str(e))
        return None

    async def set(self, audio_hash: str, result: ASRResult) -> None:
        """缓存 ASR 结果，TTL 默认 24 小时"""
        try:
            self._client.setex(
                f"asr:{audio_hash}",
                self._ttl,
                json.dumps(result.__dict__, ensure_ascii=False),
            )
        except Exception as e:
            logger.warning("cache_set_failed", audio_hash=audio_hash[:8], error=str(e))

    def ping(self) -> bool:
        """健康检查"""
        try:
            return self._client.ping()
        except Exception:
            return False
