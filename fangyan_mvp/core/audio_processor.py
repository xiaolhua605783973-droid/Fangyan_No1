import hashlib
import io
import tempfile
import os
from typing import Optional

from pydub import AudioSegment
from pydub.exceptions import CouldntDecodeError

from core.logger import get_logger

logger = get_logger(__name__)

ALLOWED_FORMATS = {"wav", "mp3", "m4a", "ogg", "flac", "webm"}
MIN_DURATION_SEC = 2.0
MAX_DURATION_SEC = 8.0


def _detect_format(filename: str) -> Optional[str]:
    """从文件名推断音频格式"""
    if not filename:
        return None
    ext = filename.rsplit(".", 1)[-1].lower()
    return ext if ext in ALLOWED_FORMATS else None


def _load_audio(audio_bytes: bytes, fmt: Optional[str] = None) -> AudioSegment:
    """
    将音频字节加载为 AudioSegment。
    先尝试内存流；若失败（WebM/Matroska 等需要 seek 的格式），
    回退到临时文件（ffmpeg 从文件读取，支持 seek）。
    """
    # 1. 内存流 + 指定格式
    if fmt:
        try:
            return AudioSegment.from_file(io.BytesIO(audio_bytes), format=fmt)
        except Exception:
            pass

    # 2. 内存流 + 自动检测
    try:
        return AudioSegment.from_file(io.BytesIO(audio_bytes))
    except Exception:
        pass

    # 3. 写临时文件后读取（解决 WebM/Matroska 需要 seek 的问题）
    suffix = f".{fmt}" if fmt else ".audio"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(audio_bytes)
        tmp_path = tmp.name
    try:
        return AudioSegment.from_file(tmp_path)
    finally:
        os.unlink(tmp_path)


class AudioProcessor:
    """音频预处理：验证、格式转换、哈希计算"""

    def validate(self, audio_bytes: bytes, filename: str = "") -> dict:
        """
        验证音频格式和时长。

        Returns:
            {valid: bool, format: str, duration: float, error: str}
        """
        fmt = _detect_format(filename)

        try:
            audio = _load_audio(audio_bytes, fmt)
        except Exception as e:
            return {"valid": False, "error": "无法解析音频文件，请上传 WAV/MP3/M4A/WebM 格式"}

        duration = len(audio) / 1000.0  # 毫秒 → 秒

        if duration < MIN_DURATION_SEC:
            return {
                "valid": False,
                "error": f"音频时长过短（{duration:.1f}s），最短 {MIN_DURATION_SEC}s",
            }
        if duration > MAX_DURATION_SEC:
            return {
                "valid": False,
                "error": f"音频时长超出限制（{duration:.1f}s），最长 {MAX_DURATION_SEC}s",
            }

        detected_fmt = fmt or audio.channels and "wav"
        return {"valid": True, "format": detected_fmt or "wav", "duration": round(duration, 2)}

    def convert_to_pcm(self, audio_bytes: bytes, fmt: Optional[str] = None) -> bytes:
        """
        转换为 16kHz 单声道 PCM WAV（ASR API 标准格式）。
        支持 WebM/Matroska 等需要 seek 的格式。
        """
        audio = _load_audio(audio_bytes, fmt)
        audio = audio.set_frame_rate(16000).set_channels(1).set_sample_width(2)
        buf = io.BytesIO()
        audio.export(buf, format="wav")
        return buf.getvalue()

    def compute_hash(self, audio_bytes: bytes) -> str:
        """计算音频 SHA-256 哈希，用于缓存去重"""
        return hashlib.sha256(audio_bytes).hexdigest()
