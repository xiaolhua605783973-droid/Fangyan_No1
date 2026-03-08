from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class ASRResult:
    """ASR 转写结果"""
    text: str
    confidence: float
    duration_ms: int
    provider: str


class ASRAdapter(ABC):
    """ASR 适配器抽象基类，所有具体实现必须继承此类"""

    @abstractmethod
    async def transcribe(self, audio_bytes: bytes) -> ASRResult:
        """
        将音频字节流转写为文本。

        Args:
            audio_bytes: 16kHz 单声道 PCM WAV 音频字节

        Returns:
            ASRResult 转写结果

        Raises:
            Exception: ASR 服务调用失败时抛出
        """
