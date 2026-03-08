from pydantic import BaseModel, Field
from typing import Literal


class IntentResponse(BaseModel):
    """语音识别结构化输出，遵循 fangyan.yaml API 协议"""

    intent: Literal[
        "CALL_NURSE",
        "CALL_FAMILY",
        "HEALTH_ALERT",
        "EMERGENCY",
        "UNKNOWN",
    ] = Field(..., description="识别到的业务意图")

    slots: dict = Field(default_factory=dict, description="槽位信息（MVP阶段为空对象）")

    confidence: float = Field(..., ge=0.0, le=1.0, description="意图识别置信度")

    risk_level: Literal["LOW", "MEDIUM", "HIGH"] = Field(
        ..., description="风险等级"
    )

    raw_text: str = Field(..., description="ASR 原始转写文本")

    metadata: dict = Field(
        default_factory=dict,
        description="扩展信息（延迟、匹配关键词等）",
    )


class HealthResponse(BaseModel):
    status: str = "ok"
    version: str
    asr_provider: str
