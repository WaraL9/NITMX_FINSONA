from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import cases
from app.config import settings
from app.db import create_all
from app.schemas import Health

VERSION = "0.1.0"


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings.storage_dir.mkdir(parents=True, exist_ok=True)
    create_all()
    yield


app = FastAPI(title="Finsona AI", version=VERSION, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(cases.router)


@app.get("/api/health", response_model=Health, tags=["system"])
def health() -> Health:
    return Health(
        status="ok",
        version=VERSION,
        connector_mode=settings.connector_mode,
        live_ocr=settings.use_live_ocr,
        live_llm=settings.use_live_llm,
    )
