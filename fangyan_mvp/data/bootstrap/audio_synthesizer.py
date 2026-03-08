"""
TTS 音频合成器
调用阿里云 TTS API 将四川方言文本合成为音频，
支持叠加背景噪声模拟真实养老院环境。

使用前需在 .env 中配置：
  ALIYUN_ACCESS_KEY / ALIYUN_ACCESS_SECRET
"""
import io
import os
import random
import struct
import time
import asyncio
import base64
import hashlib
import hmac
import urllib.parse
import uuid

import aiohttp

try:
    from pydub import AudioSegment
    from pydub.generators import WhiteNoise

    PYDUB_AVAILABLE = True
except ImportError:
    PYDUB_AVAILABLE = False


# 阿里云 TTS 可用的四川/老年友好音色
# 普通话音色（老年语速模拟，四川方言目前 TTS 支持有限，以普通话音色替代）
_VOICE_OPTIONS = [
    "xiaoyun",   # 小云（标准普通话女声）
    "xiaogang",  # 小刚（标准普通话男声）
    "ruoxi",     # 若溪（温柔女声）
    "xiaowei",   # 小威（男声）
]

# 阿里云 NLS TTS REST API
TTS_URL = "https://nls-gateway-cn-shanghai.aliyuncs.com/stream/v1/tts"
TOKEN_URL = "https://nls-meta.cn-shanghai.aliyuncs.com/"


class AudioSynthesizer:
    """
    将文本合成为 16kHz PCM WAV 音频。

    特性：
    - 调用阿里云 NLS TTS API（支持四川话语速调整）
    - 老年人语速：0.8x（speech_rate = -200，范围 -500~500）
    - 可选：叠加轻微背景噪声（SNR ≈ 20dB）
    - Token 自动缓存刷新
    """

    def __init__(
        self,
        access_key: str,
        access_secret: str,
        region: str = "cn-shanghai",
        voice: str = "xiaoyun",
        speech_rate: int = -200,  # -500(慢)~500(快)，老年人用 -200
        add_noise: bool = False,
        noise_level: float = 0.02,  # 噪声幅度（0=无噪声，0.05=明显噪声）
    ):
        self._access_key = access_key
        self._access_secret = access_secret
        self._region = region
        self._voice = voice
        self._speech_rate = speech_rate
        self._add_noise = add_noise
        self._noise_level = noise_level

        self._token: str | None = None
        self._token_expire_time: float = 0.0

    async def synthesize(self, text: str) -> bytes:
        """
        将文本合成为 16kHz 单声道 PCM WAV bytes。

        Args:
            text: 待合成文本

        Returns:
            WAV 音频字节
        """
        token = await self._get_token()
        audio_bytes = await self._call_tts(text, token)

        if self._add_noise and PYDUB_AVAILABLE:
            audio_bytes = self._overlay_noise(audio_bytes)

        return audio_bytes

    async def _call_tts(self, text: str, token: str) -> bytes:
        """调用阿里云 TTS API"""
        params = {
            "appkey": self._access_key,
            "token": token,
            "text": text,
            "voice": self._voice,
            "format": "wav",
            "sample_rate": 16000,
            "speech_rate": self._speech_rate,
            "pitch_rate": 0,
            "volume": 50,
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    TTS_URL,
                    params=params,
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.content_type == "audio/mpeg" or resp.content_type.startswith(
                        "audio/"
                    ):
                        return await resp.read()
                    # 错误时返回 JSON
                    error = await resp.json()
                    raise RuntimeError(f"TTS API 错误: {error}")
        except Exception as e:
            raise RuntimeError(f"TTS 合成失败: {e}") from e

    def _overlay_noise(self, audio_bytes: bytes) -> bytes:
        """
        叠加轻微白噪声，模拟养老院背景环境（走廊声、空调声）。
        SNR ≈ 20dB（barely perceptible）
        """
        if not PYDUB_AVAILABLE:
            return audio_bytes

        audio = AudioSegment.from_wav(io.BytesIO(audio_bytes))
        noise = WhiteNoise().to_audio_segment(duration=len(audio))
        # 降低噪声音量：主音量 - 降低量
        noise = noise - (noise.dBFS - audio.dBFS + 20)  # 20dB 低于主音
        mixed = audio.overlay(noise)

        buf = io.BytesIO()
        mixed.export(buf, format="wav")
        return buf.getvalue()

    async def _get_token(self) -> str:
        """获取并缓存阿里云 NLS Token"""
        if self._token and time.time() < self._token_expire_time - 60:
            return self._token

        params = self._build_token_params()
        query_string = urllib.parse.urlencode(sorted(params.items()))
        string_to_sign = (
            f"GET&{urllib.parse.quote('/', safe='')}"
            f"&{urllib.parse.quote(query_string, safe='')}"
        )
        signing_key = self._access_secret + "&"
        signature = base64.b64encode(
            hmac.new(
                signing_key.encode("utf-8"),
                string_to_sign.encode("utf-8"),
                hashlib.sha1,
            ).digest()
        ).decode("utf-8")
        params["Signature"] = signature
        url = TOKEN_URL + "?" + urllib.parse.urlencode(params)

        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                data = await resp.json()

        if "Token" not in data:
            raise RuntimeError(f"Token 获取失败: {data}")

        self._token = data["Token"]["Id"]
        self._token_expire_time = float(data["Token"]["ExpireTime"])
        return self._token

    def _build_token_params(self) -> dict:
        return {
            "AccessKeyId": self._access_key,
            "Action": "CreateToken",
            "Format": "JSON",
            "RegionId": self._region,
            "SignatureMethod": "HMAC-SHA1",
            "SignatureNonce": str(uuid.uuid4()),
            "SignatureVersion": "1.0",
            "Timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "Version": "2019-02-28",
        }


def generate_silent_wav(duration_ms: int = 3000, sample_rate: int = 16000) -> bytes:
    """
    生成指定时长的静音 WAV（用于离线测试，无需调用 TTS API）。

    Args:
        duration_ms: 时长（毫秒）
        sample_rate: 采样率

    Returns:
        WAV 字节
    """
    num_samples = int(sample_rate * duration_ms / 1000)
    audio_data = b"\x00\x00" * num_samples  # 16-bit 静音

    buf = io.BytesIO()
    # WAV header
    data_size = len(audio_data)
    buf.write(b"RIFF")
    buf.write(struct.pack("<I", 36 + data_size))
    buf.write(b"WAVE")
    buf.write(b"fmt ")
    buf.write(struct.pack("<I", 16))          # chunk size
    buf.write(struct.pack("<H", 1))           # PCM
    buf.write(struct.pack("<H", 1))           # mono
    buf.write(struct.pack("<I", sample_rate))
    buf.write(struct.pack("<I", sample_rate * 2))  # byte rate
    buf.write(struct.pack("<H", 2))           # block align
    buf.write(struct.pack("<H", 16))          # bits per sample
    buf.write(b"data")
    buf.write(struct.pack("<I", data_size))
    buf.write(audio_data)
    return buf.getvalue()
