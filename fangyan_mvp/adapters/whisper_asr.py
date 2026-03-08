import io
import tempfile
import time
from pathlib import Path

from core.asr_adapter import ASRAdapter, ASRResult
from core.logger import get_logger

logger = get_logger(__name__)

# Month 3 预研：faster-whisper CPU 推理
# 安装：pip install faster-whisper
# 推荐配置：medium 模型 + INT8 量化，CPU 推理约 1-2 秒


class WhisperASRAdapter(ASRAdapter):
    """
    faster-whisper CPU 推理适配器（Month 3 预研）。
    使用 INT8 量化降低内存占用和推理延迟。
    """

    def __init__(self, model_size: str = "medium", num_workers: int = 4):
        try:
            from faster_whisper import WhisperModel
        except ImportError:
            raise ImportError("请安装 faster-whisper: pip install faster-whisper")

        logger.info("loading_whisper_model", model_size=model_size)
        self._model = WhisperModel(
            model_size,
            device="cpu",
            compute_type="int8",
            num_workers=num_workers,
            download_root="models/",
        )
        logger.info("whisper_model_loaded", model_size=model_size)

    async def transcribe(self, audio_bytes: bytes) -> ASRResult:
        """
        使用 faster-whisper 转写音频。
        注意：faster-whisper 不支持从内存流直接读取，需要临时文件。
        """
        start = time.time()

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            f.write(audio_bytes)
            tmp_path = f.name

        try:
            segments, info = self._model.transcribe(
                tmp_path,
                language="zh",
                beam_size=5,
                vad_filter=True,
            )
            text = "".join(seg.text for seg in segments).strip()
            duration_ms = int((time.time() - start) * 1000)

            logger.info(
                "whisper_asr_success",
                duration_ms=duration_ms,
                language_prob=round(info.language_probability, 3),
            )

            return ASRResult(
                text=text,
                confidence=info.language_probability,
                duration_ms=duration_ms,
                provider="whisper",
            )
        finally:
            Path(tmp_path).unlink(missing_ok=True)
