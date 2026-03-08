from fastapi import APIRouter
from api.schemas import HealthResponse
from config.settings import get_settings

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """服务健康检查接口"""
    settings = get_settings()
    return HealthResponse(
        status="ok",
        version=settings.VERSION,
        asr_provider=settings.ASR_PROVIDER,
    )
