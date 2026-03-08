from functools import lru_cache

from core.audio_processor import AudioProcessor
from core.asr_adapter import ASRAdapter
from core.cache import ASRCache
from core.text_normalizer import ShaoxingDialectNormalizer
from core.intent_engine import RuleBasedIntentEngine
from core.risk_control import RiskController
from db.repository import RecordRepository
from config.settings import get_settings


@lru_cache
def get_audio_processor() -> AudioProcessor:
    return AudioProcessor()


@lru_cache
def get_asr_adapter() -> ASRAdapter:
    settings = get_settings()
    if settings.ASR_PROVIDER == "aliyun":
        from adapters.aliyun_asr import AliyunASRAdapter
        return AliyunASRAdapter(
            access_key=settings.ALIYUN_ACCESS_KEY,
            access_secret=settings.ALIYUN_ACCESS_SECRET,
        )
    elif settings.ASR_PROVIDER == "whisper":
        from adapters.whisper_asr import WhisperASRAdapter
        return WhisperASRAdapter()
    raise ValueError(f"不支持的 ASR 提供商: {settings.ASR_PROVIDER}")


@lru_cache
def get_cache() -> ASRCache:
    settings = get_settings()
    return ASRCache(redis_url=settings.REDIS_URL, ttl=settings.CACHE_TTL)


@lru_cache
def get_text_normalizer() -> ShaoxingDialectNormalizer:
    return ShaoxingDialectNormalizer(dict_path="config/dialect_dict.json")


@lru_cache
def get_intent_engine() -> RuleBasedIntentEngine:
    return RuleBasedIntentEngine(rules_path="config/intent_rules.yaml")


@lru_cache
def get_risk_controller() -> RiskController:
    return RiskController(keywords_path="config/emergency_keywords.json")


@lru_cache
def get_repository() -> RecordRepository | None:
    """DB 写入依赖（PostgreSQL 不可达时降级为 None，不阻塞 API 响应）"""
    settings = get_settings()
    try:
        return RecordRepository(database_url=settings.DATABASE_URL)
    except Exception:
        return None
