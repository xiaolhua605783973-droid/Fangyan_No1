import hashlib
import io
import subprocess
import tempfile
import os
from typing import Optional

from pydub import AudioSegment
from pydub.exceptions import CouldntDecodeError

from core.logger import get_logger

logger = get_logger(__name__)

ALLOWED_FORMATS = {"wav", "mp3", "m4a", "mp4", "ogg", "flac", "webm"}
MIN_DURATION_SEC = 2.0
MAX_DURATION_SEC = 8.0


def _detect_format(filename: str) -> Optional[str]:
    """从文件名推断音频格式"""
    if not filename:
        return None
    ext = filename.rsplit(".", 1)[-1].lower()
    return ext if ext in ALLOWED_FORMATS else None


def _ffmpeg_decode(tmp_path: str, input_fmt: Optional[str] = None) -> AudioSegment:
    """
    直接调用 ffmpeg subprocess，以文件路径为输入（支持 seek），
    输出 WAV 到 stdout（WAV 不需要 seek），再包装为 AudioSegment。
    这是绕过 pydub 管道限制的唯一可靠方式。
    input_fmt 指定输入格式（如 webm/ogg/mp4），避免 ffmpeg 依赖文件扩展名猜测。
    """
    from pydub.utils import get_encoder_name
    ffmpeg_cmd = get_encoder_name()  # 'ffmpeg' 或 'avconv'
    cmd = [ffmpeg_cmd, "-y"]
    if input_fmt:
        # 显式告诉 ffmpeg 输入格式，webm/ogg 内容但扩展名错误时仍能正确解码
        fmt_map = {"webm": "webm", "ogg": "ogg", "mp4": "mp4", "m4a": "mp4",
                   "mp3": "mp3", "wav": "wav", "flac": "flac"}
        if input_fmt in fmt_map:
            cmd += ["-f", fmt_map[input_fmt]]
    cmd += ["-i", tmp_path, "-f", "wav", "-ar", "16000", "-ac", "1", "pipe:1"]
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode != 0:
        raise CouldntDecodeError(
            f"ffmpeg 无法解码: {result.stderr.decode(errors='replace')[-300:]}"
        )
    return AudioSegment.from_wav(io.BytesIO(result.stdout))


def _load_audio(audio_bytes: bytes, fmt: Optional[str] = None) -> AudioSegment:
    """
    将音频字节加载为 AudioSegment。
    策略：
    1. 内存流 + 指定格式（仅对 WAV/MP3 等不需要 seek 的格式有效）
    2. 写临时文件 → ffmpeg 直接从文件读取（支持 seek，解决 WebM/Matroska 问题）
    注意：pydub.from_file(path) 内部仍会 open()+pipe，所以必须绕过 pydub 调用 ffmpeg。
    """
    # 1. 内存流 + 指定格式（快速路径，对 WAV/MP3 有效）
    if fmt and fmt in ("wav", "mp3", "mp4", "m4a", "ogg", "flac"):
        try:
            return AudioSegment.from_file(io.BytesIO(audio_bytes), format=fmt)
        except Exception:
            pass

    # 2. 写临时文件 → ffmpeg 直接从文件路径读取（WebM/Matroska 等 seek-required 格式）
    if not audio_bytes:
        raise ValueError("音频数据为空")
    suffix = f".{fmt}" if fmt else ".webm"  # 默认 .webm（浏览器 MediaRecorder 输出）
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(audio_bytes)
            tmp_path = tmp.name
        return _ffmpeg_decode(tmp_path, input_fmt=fmt)
    finally:
        if tmp_path and os.path.exists(tmp_path):
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
            logger.error("audio_decode_failed", fmt=fmt, filename=filename, error=str(e))
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
