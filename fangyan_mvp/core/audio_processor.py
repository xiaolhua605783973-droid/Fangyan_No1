import hashlib
import io
from typing import Optional

from pydub import AudioSegment
from pydub.exceptions import CouldntDecodeError

from core.logger import get_logger

logger = get_logger(__name__)

ALLOWED_FORMATS = {"wav", "mp3", "m4a", "ogg", "flac"}
MIN_DURATION_SEC = 2.0
MAX_DURATION_SEC = 8.0


def _detect_format(filename: str) -> Optional[str]:
    """从文件名推断音频格式"""
    if not filename:
        return None
    ext = filename.rsplit(".", 1)[-1].lower()
    return ext if ext in ALLOWED_FORMATS else None


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
            audio = AudioSegment.from_file(io.BytesIO(audio_bytes), format=fmt)
        except CouldntDecodeError:
            return {"valid": False, "error": "无法解析音频文件，请上传 WAV/MP3/M4A 格式"}
        except Exception as e:
            return {"valid": False, "error": f"音频解析失败: {e}"}

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
        """
        audio = AudioSegment.from_file(io.BytesIO(audio_bytes), format=fmt)
        audio = audio.set_frame_rate(16000).set_channels(1).set_sample_width(2)
        buf = io.BytesIO()
        audio.export(buf, format="wav")
        return buf.getvalue()

    def compute_hash(self, audio_bytes: bytes) -> str:
        """计算音频 SHA-256 哈希，用于缓存去重"""
        return hashlib.sha256(audio_bytes).hexdigest()
