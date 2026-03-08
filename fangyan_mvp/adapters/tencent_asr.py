import asyncio
import base64
import time
from typing import Any

from fastapi import HTTPException

from core.asr_adapter import ASRAdapter, ASRResult
from core.logger import get_logger

logger = get_logger(__name__)


class TencentASRAdapter(ASRAdapter):
    """
    腾讯云一句话识别适配器（阿里云 ASR 的备份方案）。
    使用 EngSerViceType="16k_zh_dialect" 支持方言识别。
    文档：https://cloud.tencent.com/document/api/1093/35799
    """

    def __init__(self, secret_id: str, secret_key: str, region: str = "ap-guangzhou"):
        self._secret_id = secret_id
        self._secret_key = secret_key
        self._region = region

    def _call_tencent_asr(self, audio_bytes: bytes) -> dict[str, Any]:
        """
        同步调用腾讯云 ASR SDK（供 run_in_executor 包装）。

        Args:
            audio_bytes: 16kHz 单声道 PCM WAV 音频字节

        Returns:
            腾讯云 SDK 返回的 Response 对象转字典
        """
        # 延迟导入，避免未安装 SDK 时影响整体启动
        from tencentcloud.asr.v20190614 import asr_client, models
        from tencentcloud.common import credential
        from tencentcloud.common.exception.tencent_cloud_sdk_exception import (
            TencentCloudSDKException,
        )
        from tencentcloud.common.profile.client_profile import ClientProfile
        from tencentcloud.common.profile.http_profile import HttpProfile

        cred = credential.Credential(self._secret_id, self._secret_key)

        http_profile = HttpProfile()
        http_profile.endpoint = "asr.tencentcloudapi.com"

        client_profile = ClientProfile()
        client_profile.httpProfile = http_profile

        client = asr_client.AsrClient(cred, self._region, client_profile)

        req = models.SentenceRecognitionRequest()
        req.ProjectId = 0
        req.SubServiceType = 2  # 一句话识别
        req.EngSerViceType = "16k_zh_dialect"  # 方言模型
        req.SourceType = 1  # 音频数据直传
        req.VoiceFormat = "wav"
        req.UsrAudioKey = f"fangyan_{int(time.time())}"
        req.Data = base64.b64encode(audio_bytes).decode("utf-8")
        req.DataLen = len(audio_bytes)

        resp = client.SentenceRecognition(req)
        return resp

    async def transcribe(self, audio_bytes: bytes) -> ASRResult:
        """
        调用腾讯云 ASR API 转写音频。

        Args:
            audio_bytes: 16kHz 单声道 PCM WAV

        Returns:
            ASRResult
        """
        start = time.time()

        try:
            loop = asyncio.get_event_loop()
            resp = await loop.run_in_executor(
                None, self._call_tencent_asr, audio_bytes
            )

            text: str = resp.Result or ""
            # 腾讯云一句话识别返回词级置信度列表，取平均值；无则默认 0.9
            confidence: float = 0.9
            if hasattr(resp, "WordList") and resp.WordList:
                scores = [
                    w.StableFlag if hasattr(w, "StableFlag") else 1
                    for w in resp.WordList
                ]
                confidence = round(sum(scores) / len(scores), 4)

            duration_ms = int((time.time() - start) * 1000)

            logger.info(
                "tencent_asr_success",
                text=text,
                duration_ms=duration_ms,
                confidence=confidence,
            )

            return ASRResult(
                text=text,
                confidence=confidence,
                duration_ms=duration_ms,
                provider="tencent",
            )

        except Exception as e:
            logger.error("tencent_asr_failed", error=str(e))
            raise HTTPException(
                status_code=503,
                detail="腾讯云语音识别服务暂时不可用",
            ) from e
