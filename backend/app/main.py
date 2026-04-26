from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.__version__ import __version__
from app.config import settings
from app.database import init_db
from app.services.transcription_queue import (
    start_transcription_queue,
    stop_transcription_queue,
)
from app.services.model_installer import resume_interrupted_installs


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    await resume_interrupted_installs()
    await start_transcription_queue()
    yield
    await stop_transcription_queue()


app = FastAPI(title="ASR UI", version=__version__, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from app.routers import auth, files, models, system, transcriptions, users  # noqa: E402

app.include_router(auth.router)
app.include_router(system.router)
app.include_router(files.router)
app.include_router(transcriptions.router)
app.include_router(models.router)
app.include_router(users.router)
