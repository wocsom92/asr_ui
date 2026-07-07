# ASR UI

ASR UI is a self-hosted transcription web app built around local ASR models. It provides private audio uploads, project-scoped transcription jobs, local Whisper/GigaAM model management, distributed workers, transcript review/editing, summaries, Telegram ingestion, and transcript downloads.

Version: `3.0.0`

## Features

- First-user admin setup with JWT cookie authentication.
- Per-user audio file isolation, project organization, and admin user management.
- Uploads for common audio formats with duration probing through `ffmpeg`.
- Whisper and GigaAM model catalog, install, cancel, and remove flows.
- Transcription queue with live progress, cancellation, transcript cleanup, and TXT/JSON/SRT/VTT downloads.
- Transcript segment review and editing, with output regeneration after edits.
- Optional distributed workers with admin approval, model install control, worker health, and split-job scheduling.
- Optional all-local transcript summarization through an Ollama service, with chunking tuned for Raspberry Pi 5.
- Telegram ingestion, user preferences, worker/model selection, split jobs, and optional summary delivery.
- Optional speaker diarization for completed single-worker transcripts.
- Worker scheduling uses per-model speed history so split jobs account for how fast each worker is with the selected ASR model.
- Responsive React interface with dashboard, files, jobs, transcriptions, projects, models, workers, users, and settings pages.

## What's New in 3.0.0

- Added local Ollama transcript summaries with manual, automatic, and Telegram-requested flows.
- Added projects, transcript editing, live updates, and output regeneration.
- Added summary chunking, bounded Ollama generation, serialized summary execution, and clearer summary failure messages for low-power hosts.
- Added GigaAM v3 support with local speech-aware audio chunking for long recordings.
- Added Telegram bot settings, allowed-user preferences, worker/model targeting, and summary notifications.
- Improved distributed worker scheduling by using per-model worker speed history.
- Added Raspberry Pi and remote-worker deployment settings, including PyTorch CPU thread limits for GigaAM.
- Added auth hardening settings for secure cookies, placeholder secret checks, and login rate limiting.

## Stack

- Frontend: React, Vite, TypeScript, Tailwind, shadcn-style UI primitives.
- Backend: FastAPI, async SQLAlchemy, SQLite, JWT cookies.
- Transcription: `ffmpeg` audio conversion, `whisper.cpp` GGML models, and GigaAM v3 Hugging Face snapshots.
- Summarization: local Ollama models, disabled until configured by an admin.
- Integrations: Telegram bot runtime with optional local egress proxy.
- Deployment: Docker Compose with frontend on `8824` and backend on `8825` by default.

## Quick Start

```bash
cp .env.example .env
docker compose up -d --build
```

Open `http://localhost:8824`, create the first admin account, install a model from the Models page, upload audio, and queue a transcription job.

## Configuration

Configuration is read from `.env`. Start from `.env.example` and set at least a production-safe `SECRET_KEY` before exposing the app beyond a trusted local network.

Useful settings:

- `FRONTEND_PORT` and `BACKEND_PORT`: published Docker Compose ports.
- `SECRET_KEY`: JWT signing secret. Replace the placeholder for any non-local deployment.
- `COOKIE_SECURE`, `COOKIE_SAMESITE`, and `REQUIRE_SECURE_SECRET_KEY`: browser cookie and startup safety controls.
- `LOGIN_RATE_LIMIT_ATTEMPTS` and `LOGIN_RATE_LIMIT_WINDOW_SECONDS`: basic login throttling per client and username.
- `MAX_UPLOAD_MB`: upload size limit.
- `WHISPER_THREADS`: number of CPU threads passed to whisper.cpp.
- `WHISPER_MAX_CONTEXT`: max previous text tokens passed between windows. The default `0` prevents hallucinations from repeating through a long file.
- `WHISPER_USE_GPU` and `WHISPER_FLASH_ATTN`: disabled by default for CPU-only Docker reliability.
- `TRANSCRIPT_FILTER_REGEX`: optional regex removed from generated transcript text. Leave it empty to disable cleanup.
- `GIGAAM_CHUNK_MAX_SECONDS`: hard maximum WAV chunk length passed to GigaAM. Default `24.0`.
- `GIGAAM_CHUNK_TARGET_SECONDS` and `GIGAAM_CHUNK_OVERLAP_SECONDS`: speech-aware chunk core target and local context overlap. Defaults `22.0` and `1.0`.
- `GIGAAM_VAD_ENABLED`, `GIGAAM_VAD_MODE`, `GIGAAM_VAD_MERGE_SILENCE_MS`, and `GIGAAM_VAD_PAD_MS`: local WebRTC VAD settings used to prefer silence/low-energy GigaAM chunk boundaries.
- `GIGAAM_TORCH_THREADS` and `GIGAAM_TORCH_INTEROP_THREADS`: PyTorch CPU thread limits for GigaAM inference. Raspberry Pi 5 deploys use `3` and `1`; the MacBook worker target uses `4` and `1`.
- `SUMMARIZATION_OLLAMA_BASE_URL`: local Ollama endpoint used for transcript summaries. Docker Compose defaults to `http://ollama:11434`.
- `DIARIZATION_ENABLED`, `DIARIZATION_MODEL`, and `HUGGINGFACE_TOKEN`: optional pyannote-based diarization settings.
- `ASR_WORKER_*` and `ASR_SPLIT_*`: local/remote worker identity, authentication, heartbeat, concurrency, and split-job sizing.
- `TELEGRAM_PROXY_URL` and `ASR_TELEGRAM_EGRESS_PROXY_*`: Telegram proxy and optional egress binding settings.
- `BACKEND_PYTHON_IMAGE`, `FRONTEND_NODE_IMAGE`, and `FRONTEND_NGINX_IMAGE`: optional Docker base image overrides. Defaults use Docker Hub official images; set these to `public.ecr.aws/docker/library/...` if Docker Hub is unavailable in your network.

## Projects And Transcripts

Projects group files and transcription jobs for each user. Admins can inspect user activity and manage users, while regular users only see their own files, projects, and jobs.

Finished jobs expose generated transcript files and editable transcript segments. Segment edits can be saved back through the Transcriptions page, then downloads are regenerated from the edited segment data.

## Local Summarization

Summarization never calls cloud APIs. Docker Compose includes an `ollama` service with a persistent `ollama_data` volume. Admins can enable summaries, pull an Ollama model, choose the active model, and optionally enable automatic summaries from Settings.

Recommended Raspberry Pi 5 models:

- `qwen2.5:3b`: better summary quality on an 8 GB Pi 5.
- `qwen2.5:1.5b`: lighter fallback for lower memory or faster responses.
- `llama3.2:3b`: general-purpose fallback.

Manual summaries are available from the Transcriptions page after a job succeeds. Long transcripts are summarized in chunks and then merged into one final summary.

## Telegram Bot

Telegram support is configured from Settings by an admin. The bot can accept audio from allowed Telegram users, map them to app users/projects, apply default model and worker preferences, optionally split jobs, and send completion or summary messages.

When direct Telegram access is blocked, `telegram-egress-proxy` can route Telegram API traffic through a local proxy or a bound network interface. Docker Compose includes this service and exposes its settings through `.env`.

## Deploy

Edit `scripts/deploy.targets.env` with your host, user, SSH key, and destination path, then run:

```bash
scripts/deploy.sh --target raspi5
```

To start the example local worker target from `scripts/deploy.targets.env.example`, copy it to `scripts/deploy.targets.env`, adjust the hostnames/tokens, then run:

```bash
scripts/deploy.sh --target macbook_worker
```

The backend container builds `whisper.cpp` and includes `ffmpeg`. Model files are stored in the `model_data` Docker volume. Uploads, transcripts, and SQLite data live in `db_data`.

## GigaAM v3

GigaAM v3 models are available from the Models page alongside Whisper models. The app supports the CTC, RNN-T, E2E CTC, and E2E RNN-T variants from `ai-sage/GigaAM-v3`.

GigaAM runs through Hugging Face `transformers` with remote model code and downloads model snapshots into `/models`. Rebuild the backend and worker images after updating so the added ML dependencies are installed. GigaAM models are Russian-only in the app.

The app does not call GigaAM's pyannote-based `transcribe_longform` path, so transcription does not require an `HF_TOKEN`. Audio longer than GigaAM's short-form limit is split locally and transcribed with the regular local `transcribe` method.

GigaAM chunking is separate from distributed split jobs. Before GigaAM inference, the worker converts the input to 16 kHz mono PCM WAV with `ffmpeg`. If the WAV is longer than `GIGAAM_CHUNK_MAX_SECONDS`, the worker writes local WAV chunks under the transcript output directory in `gigaam_chunks/`, runs `transcribe()` on each chunk, then merges the chunk texts into normal TXT, JSON, SRT, and VTT outputs.

By default, GigaAM chunking uses local WebRTC VAD to prefer silence or low-energy cut points near a 22-second core target. Each chunk can include up to 1 second of local overlap/context, but the actual WAV sent to GigaAM never exceeds the 24-second hard maximum. Final timestamps use the non-overlap core range, and repeated words at chunk joins are deduplicated. If VAD is disabled, unavailable, or finds no speech, the worker falls back to fixed 24-second chunks. This avoids GigaAM's "Too long wav file, use transcribe_longform" error while staying tokenless and fully local.

The practical limit is time-based: 24 seconds per GigaAM WAV chunk by default. It is not a fixed 24 MB upload limit; the byte size of a 24-second WAV depends on the converted sample rate, sample width, and channel count.

GigaAM inference runs through PyTorch. Set `GIGAAM_TORCH_THREADS` to cap the number of intra-op CPU threads used by PyTorch and `GIGAAM_TORCH_INTEROP_THREADS` to cap inter-op scheduling threads. These settings are applied before the GigaAM model is loaded in each backend or worker process. `scripts/deploy.targets.env` sets `3/1` for `raspi5` and `4/1` for `macbook_worker`.

## Remote Workers

The Raspberry Pi backend can keep its local worker enabled with `ASR_WORKER_ENABLED=true`.
Keep `ASR_WORKER_NAME` stable across redeploys, for example `raspi5`, so the same worker
database row and id are reused.
To run a worker on another machine, point it at the Pi backend and use the same
`ASR_WORKER_TOKEN`:

```bash
ASR_WORKER_NAME=macbook \
ASR_SERVER_URL=http://raspi5.local:8825 \
ASR_WORKER_TOKEN=change-me-worker-token \
docker compose --profile worker up --build worker
```

Remote workers install missing Whisper or GigaAM models into their local `/models` volume automatically.
Use `ASR_WORKER_NAME` for the stable worker identity; admins can set a friendlier display
name from the Workers page. New remote workers appear as pending on the Workers page and
must be accepted before they can install models or claim jobs. Removed workers are hidden;
if a removed worker starts heartbeating again with the same `ASR_WORKER_NAME`, it reappears
as pending.
Split transcription is optional per job from the Run transcription dialog.
Split chunks are sized from each selected worker's measured speed for the chosen model variant. If exact job history for that model is not available yet, the scheduler uses the worker's persisted per-model speed samples instead of mixing speeds from unrelated models.

## Optional Diarization

Speaker diarization is disabled by default because it adds heavy PyTorch/pyannote dependencies and uses a gated Hugging Face model. To enable it, install any optional dependencies required by your deployment image, set `DIARIZATION_ENABLED=true`, choose `DIARIZATION_MODEL`, and provide `HUGGINGFACE_TOKEN` with access to the selected model.

When enabled, completed single-worker transcripts can receive speaker labels per segment. Distributed split jobs are kept separate from diarization so chunk merging stays predictable.

## Development

Backend tests:

```bash
PYTHONPATH=backend pytest
```

Frontend build:

```bash
cd frontend
npm run build
```

## API

All API routes are under `/api/v1`.

- `/api/v1/auth`: first admin registration, login, refresh, logout, password changes, and current user.
- `/api/v1/files`: upload, list, update, stream, delete, bulk delete, and bulk transcribe audio files.
- `/api/v1/transcriptions`: list jobs, stats, details, cancel, summarize, delete, bulk delete, edit segments, and download outputs.
- `/api/v1/projects`: create, list, rename, and delete projects.
- `/api/v1/models`: installed models, catalog, stats, install/cancel, and remove.
- `/api/v1/workers`: admin worker management plus worker heartbeat, claim, progress, finish, audio, and catalog endpoints.
- `/api/v1/users`: admin user management and user stats.
- `/api/v1/system`: health, cleanup, summarization, Whisper CLI, and Telegram bot settings.
- `/api/v1/events`: server-sent events for live frontend updates.
