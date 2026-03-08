from functools import lru_cache
from pydantic_settings import BaseSettings
from pydantic import ConfigDict


class Settings(BaseSettings):
    model_config = ConfigDict(env_file=".env", env_file_encoding="utf-8")

    # 服务配置
    APP_NAME: str = "Elderly Dialect Speech Infrastructure"
    VERSION: str = "1.0.0"
    DEBUG: bool = False

    # ASR 配置（aliyun | tencent | whisper）
    ASR_PROVIDER: str = "aliyun"
    # RAM AccessKey ID（用于获取 NLS Token，格式: LTAI5t...）
    ALIYUN_ACCESS_KEY: str = ""
    # RAM AccessKey Secret
    ALIYUN_ACCESS_SECRET: str = ""
    # NLS 项目 AppKey（在智能语音控制台获取）
    ALIYUN_NLS_APP_KEY: str = ""
    ALIYUN_REGION: str = "cn-shanghai"
    TENCENT_SECRET_ID: str = ""
    TENCENT_SECRET_KEY: str = ""

    # 音频限制
    MAX_AUDIO_DURATION: int = 8
    MIN_AUDIO_DURATION: int = 2

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"
    CACHE_TTL: int = 86400  # 24小时

    # PostgreSQL
    DATABASE_URL: str = "postgresql://fangyan:password@localhost:5432/fangyan"

    # 成本控制
    ENABLE_CACHE: bool = True
    ENABLE_DEDUP: bool = True


@lru_cache
def get_settings() -> Settings:
    return Settings()
