# ASR UI

ASR UI is a self-hosted transcription web app built around `whisper.cpp`. It provides private audio uploads, per-user transcription jobs, local Whisper model management, transcript review, and transcript downloads.

Version: `1.0.0`

## Features

- First-user admin setup with JWT cookie authentication.
- Per-user audio file isolation and admin user management.
- Uploads for common audio formats with duration probing through `ffmpeg`.
- Whisper model catalog, install, cancel, and remove flows.
- Transcription queue with progress, cancellation, transcript cleanup, and download outputs.
- Responsive React interface for desktop and mobile use.

## Stack

- Frontend: React, Vite, TypeScript, Tailwind, shadcn-style UI primitives.
- Backend: FastAPI, async SQLAlchemy, SQLite, JWT cookies.
- Transcription: `ffmpeg` audio conversion and `whisper.cpp` GGML models.
- Deployment: Docker Compose with frontend on `8824` and backend on `8825` by default.

## Quick Start

```bash
cp .env.example .env
docker compose up -d --build
```

Open `http://localhost:8824`, create the first admin account, install a Whisper model from the Models page, upload audio, and queue a transcription job.

## Configuration

Configuration is read from `.env`. Start from `.env.example` and set at least a production-safe `SECRET_KEY` before exposing the app beyond a trusted local network.

Useful settings:

- `FRONTEND_PORT` and `BACKEND_PORT`: published Docker Compose ports.
- `MAX_UPLOAD_MB`: upload size limit.
- `WHISPER_THREADS`: number of CPU threads passed to whisper.cpp.
- `WHISPER_MAX_CONTEXT`: max previous text tokens passed between windows. The default `0` prevents hallucinations from repeating through a long file.
- `WHISPER_USE_GPU` and `WHISPER_FLASH_ATTN`: disabled by default for CPU-only Docker reliability.
- `TRANSCRIPT_FILTER_REGEX`: optional regex removed from generated transcript text. Leave it empty to disable cleanup.

## Deploy

Edit `scripts/deploy.targets.env` with your host, user, SSH key, and destination path, then run:

```bash
scripts/deploy.sh --target raspi5
```

The backend container builds `whisper.cpp` and includes `ffmpeg`. Model files are stored in the `model_data` Docker volume. Uploads, transcripts, and SQLite data live in `db_data`.

## Development

Backend tests:

```bash
pytest
```

Frontend build:

```bash
cd frontend
npm run build
```

## API

All API routes are under `/api/v1`, including `/api/v1/auth`, `/api/v1/files`, `/api/v1/transcriptions`, `/api/v1/models`, `/api/v1/users`, and `/api/v1/system/health`.
