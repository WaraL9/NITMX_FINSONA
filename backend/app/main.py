from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.ai import gateway
from fastapi import Depends

from app.api import analysis, cases, compliance, documents, field, memo, review, sandbox, session
from app.api.deps import scope_guard
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
# Public: health, login, SME pre-qualification, and the sandbox stand-ins for external APIs.
app.include_router(session.public)
app.include_router(field.public)
app.include_router(sandbox.router)
# Everything else requires a session and passes the role/case-scope guard (E14-01).
_guarded = [Depends(scope_guard)]
for r in (session.router, compliance.router, cases.router, documents.router, analysis.router, review.router, memo.router, field.router):
    app.include_router(r, dependencies=_guarded)


@app.get("/api/health", response_model=Health, tags=["system"])
def health() -> Health:
    return Health(
        status="ok",
        version=VERSION,
        connector_mode=settings.connector_mode,
        live_ocr=settings.use_live_ocr,
        live_llm=gateway.status()["live"],
        demo_mode=settings.demo_mode,
    )
