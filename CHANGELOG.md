# Changelog

## 3.0.0

Range: `285acc9b007d506ba68f7db633493b1d645bbc67` to `2fc1091fc6f73655bdffb2d682f555a8e9d9ebfc`

Dates: 2026-04-26 to 2026-07-07

Summary: this range evolves ASR UI from the first self-hosted Whisper-focused version into a broader local ASR platform with projects, distributed workers, GigaAM support, Telegram ingestion, local summaries, live updates, transcript editing, and expanded administration.

### Added

- Added project management, including project ownership, file/job assignment, project badges, project filtering, and a new Projects page.
- Added distributed worker support with worker registration, admin approval, heartbeats, model install/uninstall actions, job claiming, progress reporting, and worker management UI.
- Added split transcription jobs, chunk-level tracking, per-worker/model speed history, and scheduling that can distribute long jobs across available workers.
- Added GigaAM v3 model catalog entries and local inference support, including speech-aware chunking, VAD-assisted cut points, overlap handling, and deduplication at chunk joins.
- Added Telegram bot integration with allowed-user settings, upload ingestion, worker/model selection, split-job preferences, summary preferences, status handling, and optional egress proxy support.
- Added local transcript summarization through Ollama, with admin settings, model pulling, manual summaries, automatic summaries, Telegram-triggered summaries, and long-transcript chunk/merge behavior.
- Added optional speaker diarization plumbing for completed single-worker transcripts.
- Added live server-sent event updates for frontend job/file state.
- Added transcript segment APIs and an editable transcript UI for reviewing and saving segment text/timing changes.
- Added transcript output management, including segment-derived output regeneration and richer download behavior.
- Added cleanup settings and job cleanup service for managing old files/jobs.
- Added Whisper CLI settings in the system settings API/UI.
- Added theme persistence and UI support for switching theme state.
- Added confirmation dialogs, summary panels, debounced inputs, project badges, worker pages, and broader mobile navigation coverage.
- Added `.env.example` with the main runtime, worker, GigaAM, Telegram, Ollama, Docker image, and deployment settings.
- Added architecture and analytics documentation.
- Added broader backend tests for auth/file isolation, project isolation, workers, Telegram settings, summaries, model stats, and GigaAM chunking.

### Changed

- Updated the app version from `1.0.0` to `2.0.0`.
- Generalized the app from Whisper-only wording to local ASR model management across Whisper and GigaAM.
- Expanded the dashboard, jobs, files, models, settings, transcriptions, and user management pages for the new project, worker, summary, Telegram, and editing workflows.
- Reworked transcription queue/runtime behavior to support local and remote workers, split jobs, chunk progress, cancellation, model availability checks, and persisted runtime metrics.
- Improved model installation flows with catalog metadata, install cancellation, worker-local installs, and model statistics.
- Improved file APIs with project updates, bulk delete, bulk transcribe, audio streaming, and safer file/job isolation.
- Improved auth/session configuration with cookie security settings, SameSite configuration, secure secret enforcement option, and login rate limiting.
- Improved Docker Compose to include Ollama, a Telegram egress proxy service, a worker profile, persistent worker/model/Ollama volumes, and configurable base images.
- Updated deployment scripts and target examples for remote workers, local worker mode, stable worker names, Docker sudo use, purge modes, and GigaAM thread limits.
- Expanded README documentation for summaries, GigaAM, remote workers, deployment settings, and configuration.

### Fixed

- Fixed wrong transcription behavior by disabling cross-window Whisper context by default (`WHISPER_MAX_CONTEXT=0`) to avoid hallucinated text poisoning later windows.
- Improved long GigaAM transcription reliability by avoiding the model's token-gated longform path and splitting audio locally into short chunks.
- Improved summary failure handling and bounded/serialized summary execution for low-power hosts.
- Improved worker scheduling so split jobs use speed history for the selected model instead of mixing unrelated model speeds.
- Improved cancellation and cleanup paths for jobs, chunks, model installs, and summary runs.

### API And Data Model

- Added backend routers for projects, workers, and events.
- Added models for projects, transcription workers, and transcription job chunks.
- Added schemas and services for cleanup settings, summarization settings, Telegram settings, Whisper settings, worker runtime, event bus, segment outputs, diarization, summaries, and job cleanup.
- Extended transcription jobs with project, summary, split/chunk, worker, and segment-output related fields.
- Extended users/files with project-aware and statistics-related fields.
- Added endpoints for:
  - project CRUD
  - worker administration and worker runtime protocol
  - SSE events
  - summary create/cancel
  - transcript segment read/update
  - bulk file/job actions
  - cleanup, summarization, Whisper CLI, and Telegram bot settings

### Configuration And Deployment Notes

- New deployments should start from `.env.example` and set real values for `SECRET_KEY` and `ASR_WORKER_TOKEN`.
- Summarization uses the local `ollama` service and is disabled until configured by an admin.
- GigaAM uses Hugging Face model snapshots and PyTorch CPU settings; tune `GIGAAM_TORCH_THREADS` and `GIGAAM_TORCH_INTEROP_THREADS` per host.
- Remote workers use `ASR_WORKER_NAME`, `ASR_SERVER_URL`, and `ASR_WORKER_TOKEN`; new workers appear as pending until accepted.
- Telegram can use the included egress proxy when direct Telegram access is blocked or needs VPN-bound routing.

### Commits Included

- `a8ba78c` - fixed wrong transcriptions
- `91277ba` - added projects
- `5a5c4d1` - added workers and GIGAAM models
- `cb86c51` - v2
- `2fc1091` - v3
