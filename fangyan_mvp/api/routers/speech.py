import time
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from api.schemas import IntentResponse
from core.audio_processor import AudioProcessor
from core.asr_adapter import ASRAdapter
from core.cache import ASRCache
from core.text_normalizer import SichuanDialectNormalizer
from core.intent_engine import RuleBasedIntentEngine
from core.risk_control import RiskController
from core.logger import get_logger
from api.dependencies import (
    get_audio_processor,
    get_asr_adapter,
    get_cache,
    get_text_normalizer,
    get_intent_engine,
    get_risk_controller,
)

logger = get_logger(__name__)
router = APIRouter()


@router.post("/speech/recognize", response_model=IntentResponse)
async def recognize_speech(
    audio: UploadFile = File(..., description="音频文件（WAV/MP3/M4A，2-8秒）"),
    processor: AudioProcessor = Depends(get_audio_processor),
    asr: ASRAdapter = Depends(get_asr_adapter),
    cache: ASRCache = Depends(get_cache),
    normalizer: SichuanDialectNormalizer = Depends(get_text_normalizer),
    intent_engine: RuleBasedIntentEngine = Depends(get_intent_engine),
    risk_controller: RiskController = Depends(get_risk_controller),
) -> IntentResponse:
    """
    四川方言老年人语音意图识别接口。

    上传音频文件，返回结构化业务意图 JSON：
    - intent: 识别到的意图（CALL_NURSE / CALL_FAMILY / HEALTH_ALERT / EMERGENCY / UNKNOWN）
    - confidence: 置信度（0.0-1.0）
    - risk_level: 风险等级（LOW / MEDIUM / HIGH）
    - raw_text: ASR 原始转写文本
    """
    start_time = time.time()
    request_id = str(uuid.uuid4())[:8]

    # 1. 读取音频
    audio_bytes = await audio.read()

    # 2. 验证格式和时长
    validation = processor.validate(audio_bytes, audio.filename or "")
    if not validation["valid"]:
        raise HTTPException(status_code=400, detail=validation["error"])

    # 3. 计算哈希（用于去重和缓存）
    audio_hash = processor.compute_hash(audio_bytes)

    logger.info(
        "speech_request",
        request_id=request_id,
        audio_hash=audio_hash[:8],
        format=validation["format"],
        duration=validation["duration"],
    )

    # 4. 检查 Redis 缓存
    cached = await cache.get(audio_hash)
    asr_text = None
    from_cache = False

    if cached:
        asr_text = cached.text
        from_cache = True
        logger.info("cache_hit", request_id=request_id, audio_hash=audio_hash[:8])
    else:
        # 5. 转换为 16kHz PCM WAV
        pcm_audio = processor.convert_to_pcm(audio_bytes, validation["format"])

        # 6. 调用 ASR
        try:
            asr_result = await asr.transcribe(pcm_audio)
        except Exception as e:
            logger.error("asr_failed", request_id=request_id, error=str(e))
            raise HTTPException(status_code=503, detail="语音识别服务暂时不可用")

        asr_text = asr_result.text

        # 7. 缓存 ASR 结果
        await cache.set(audio_hash, asr_result)

    # 8. 文本规范化
    normalized_text = normalizer.normalize(asr_text)

    # 9. 意图识别
    intent_result = intent_engine.recognize(normalized_text)

    # 10. 风险控制
    risk_level, emergency_keywords = risk_controller.assess_risk(
        text=normalized_text,
        intent=intent_result.intent,
        confidence=intent_result.confidence,
    )

    total_ms = int((time.time() - start_time) * 1000)

    logger.info(
        "speech_recognized",
        request_id=request_id,
        intent=intent_result.intent,
        confidence=round(intent_result.confidence, 3),
        risk_level=risk_level,
        total_ms=total_ms,
        from_cache=from_cache,
    )

    return IntentResponse(
        intent=intent_result.intent,
        slots={},
        confidence=round(intent_result.confidence, 3),
        risk_level=risk_level,
        raw_text=asr_text,
        metadata={
            "request_id": request_id,
            "normalized_text": normalized_text,
            "matched_keywords": intent_result.matched_keywords,
            "emergency_keywords": emergency_keywords,
            "duration_ms": total_ms,
            "from_cache": from_cache,
        },
    )
