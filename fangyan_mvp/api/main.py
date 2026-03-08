from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routers import health, speech
from core.logger import get_logger

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("app_started", version="1.0.0")
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="Elderly Dialect Speech Infrastructure",
        description="将四川方言老年人语音转换为结构化业务意图的 B2B 语音基础设施层",
        version="1.0.0",
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health.router, tags=["Health"])
    app.include_router(speech.router, prefix="/v1", tags=["Speech"])

    return app


app = create_app()
