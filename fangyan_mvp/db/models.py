import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


class RecognitionRecord(Base):
    """语音识别结果记录（不存储音频，仅存结果）"""

    __tablename__ = "recognition_records"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    audio_hash = Column(String(64), index=True, nullable=False, comment="音频SHA-256哈希")
    raw_text = Column(Text, nullable=True, comment="ASR原始转写文本")
    normalized_text = Column(Text, nullable=True, comment="规范化后文本")
    intent = Column(String(50), nullable=True, comment="识别意图")
    confidence = Column(Float, nullable=True, comment="意图置信度")
    risk_level = Column(String(20), nullable=True, comment="风险等级")
    asr_provider = Column(String(30), nullable=True, comment="ASR提供商")
    asr_duration_ms = Column(Integer, nullable=True, comment="ASR耗时(ms)")
    total_duration_ms = Column(Integer, nullable=True, comment="总处理耗时(ms)")
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    def __repr__(self) -> str:
        return f"<RecognitionRecord id={self.id[:8]} intent={self.intent} risk={self.risk_level}>"
