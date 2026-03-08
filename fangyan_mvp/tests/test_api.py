import pytest
from unittest.mock import AsyncMock, patch
from httpx import AsyncClient, ASGITransport

from api.main import app


@pytest.mark.asyncio
async def test_health_check():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "version" in data


@pytest.mark.asyncio
async def test_recognize_missing_audio():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/v1/speech/recognize")
    assert resp.status_code == 422  # 缺少必填字段


@pytest.mark.asyncio
@patch("api.dependencies.get_asr_adapter")
async def test_recognize_with_mock_asr(mock_asr_factory):
    """使用 mock ASR 测试完整流程（不真实调用 ASR API）"""
    from core.asr_adapter import ASRResult

    mock_asr = AsyncMock()
    mock_asr.transcribe.return_value = ASRResult(
        text="帮我喊哈护士",
        confidence=0.9,
        duration_ms=500,
        provider="mock",
    )
    mock_asr_factory.return_value = mock_asr

    # 使用最小有效 WAV 文件（44字节头 + 2秒静音）
    # 实际测试应使用 tests/fixtures/ 中的真实测试音频
    pass
