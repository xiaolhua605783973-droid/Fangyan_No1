import asyncio
import base64
import hashlib
import hmac
import io
import json
import time
import urllib.parse
import uuid

import aiohttp

from core.asr_adapter import ASRAdapter, ASRResult
from core.logger import get_logger

logger = get_logger(__name__)


class AliyunASRAdapter(ASRAdapter):
    """
    阿里云智能语音一句话识别适配器。
    支持四川方言模型（customization_id: sichuan）。
    文档：https://help.aliyun.com/zh/isi/developer-reference/api-nls-cloud-meta-2019-02-28
    """

    # 阿里云一句话识别 REST API
    ASR_URL = "https://nls-gateway-cn-shanghai.aliyuncs.com/stream/v1/asr"
    # 阿里云 NLS Token API
    TOKEN_URL = "https://nls-meta.cn-shanghai.aliyuncs.com/"

    def __init__(self, access_key: str, access_secret: str, region: str = "cn-shanghai"):
        self._access_key = access_key
        self._access_secret = access_secret
        self._region = region
        # Token 缓存（避免每次请求都获取）
        self._token: str | None = None
        self._token_expire_time: float = 0.0

    async def transcribe(self, audio_bytes: bytes) -> ASRResult:
        """
        调用阿里云 ASR API 转写音频。

        Args:
            audio_bytes: 16kHz 单声道 PCM WAV

        Returns:
            ASRResult
        """
        start = time.time()
        token = await self._get_token()

        params = {
            "appkey": self._access_key,
            "token": token,
            "format": "pcm",
            "sample_rate": 16000,
            "enable_punctuation_prediction": True,
            "enable_inverse_text_normalization": True,
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.ASR_URL,
                    params=params,
                    data=audio_bytes,
                    headers={"Content-Type": "application/octet-stream"},
                    timeout=aiohttp.ClientTimeout(total=5),
                ) as resp:
                    result = await resp.json()

            if result.get("status") != 20000000:
                raise RuntimeError(f"阿里云 ASR 错误: {result.get('message')}")

            text = result.get("result", "")
            duration_ms = int((time.time() - start) * 1000)

            logger.info("aliyun_asr_success", duration_ms=duration_ms, text_len=len(text))

            return ASRResult(
                text=text,
                confidence=0.9,  # 阿里云不返回置信度，固定高置信度
                duration_ms=duration_ms,
                provider="aliyun",
            )

        except asyncio.TimeoutError:
            logger.error("aliyun_asr_timeout")
            raise RuntimeError("阿里云 ASR 请求超时")
        except Exception as e:
            logger.error("aliyun_asr_failed", error=str(e))
            raise

    async def _get_token(self) -> str:
        """
        获取阿里云 NLS 访问 Token。
        Token 有效期通常为 24 小时，内部缓存避免重复请求。
        参考：https://help.aliyun.com/zh/isi/obtaining-a-token
        """
        # 提前 60 秒刷新，防止临界过期
        if self._token and time.time() < self._token_expire_time - 60:
            return self._token

        params = self._build_token_params()
        query_string = urllib.parse.urlencode(sorted(params.items()))
        string_to_sign = f"GET&{urllib.parse.quote('/', safe='')}&{urllib.parse.quote(query_string, safe='')}"
        signing_key = self._access_secret + "&"
        signature = base64.b64encode(
            hmac.new(
                signing_key.encode("utf-8"),
                string_to_sign.encode("utf-8"),
                hashlib.sha1,
            ).digest()
        ).decode("utf-8")

        params["Signature"] = signature
        url = self.TOKEN_URL + "?" + urllib.parse.urlencode(params)

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url, timeout=aiohttp.ClientTimeout(total=5)
                ) as resp:
                    data = await resp.json()

            if "Token" not in data:
                raise RuntimeError(f"Token 获取失败: {data}")

            self._token = data["Token"]["Id"]
            self._token_expire_time = float(data["Token"]["ExpireTime"])
            logger.info("aliyun_token_refreshed")
            return self._token

        except Exception as e:
            logger.error("aliyun_token_failed", error=str(e))
            raise RuntimeError(f"阿里云 Token 获取失败: {e}") from e

    def _build_token_params(self) -> dict:
        """构造获取 Token 所需的请求参数（待签名）"""
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

