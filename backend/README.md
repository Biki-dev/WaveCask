# WaveCask Backend

WaveCask backend is the ingestion, classification, enrichment, and playlist orchestration service for the browser extension. It accepts raw user listening events, turns them into track records, classifies music vs non-music content, computes audio embeddings, enriches metadata, and produces recommendation playlists.

## 1. What this service does

At a high level the backend performs the following:

1. Receive raw events from the extension.
2. Upsert normalized track stubs in PostgreSQL.
3. Run a three-layer classifier pipeline on pending tracks.
4. Download a short audio clip for confirmed music tracks.
5. Compute a 512-dim OpenL3 embedding and store it in `pgvector`.
6. Refresh implicit engagement signals from raw event history.
7. Enrich metadata through Gemini/OpenRouter fallback providers.
8. Generate mood, mix, and context playlists from the processed track graph.

---

## 2. Runtime architecture

The application is a FastAPI service bootstrapped from [backend/src/main.py](src/main.py). Startup happens through a FastAPI `lifespan` handler that:

- ensures the `vector` Postgres extension exists,
- creates the ORM tables if missing,
- normalizes the `tracks.audio_embedding` column to `vector(512)` when needed,
- ensures analytics columns exist on `raw_events` and `tracks`,
- registers the nightly APScheduler jobs.

Main runtime entry:

- [backend/src/main.py](src/main.py)

Core runtime dependencies:

- [backend/src/database.py](src/database.py) – SQLAlchemy engine, session factory, DB bootstrap helpers
- [backend/src/models.py](src/models.py) – ORM schema for events, sessions, tracks, playlists, and metadata
- [backend/src/schemas.py](src/schemas.py) – request/response Pydantic contracts
- [backend/src/jobs.py](src/jobs.py) – nightly background workflows

---

## 3. Directory map

### Application boot and config

- [backend/src/main.py](src/main.py) – FastAPI app creation, CORS, router registration, scheduler startup/shutdown
- [backend/src/database.py](src/database.py) – engine/session configuration and DB migration helpers
- [backend/src/models.py](src/models.py) – SQLAlchemy model declarations
- [backend/src/schemas.py](src/schemas.py) – API models

### Route layer

The route package stays thin and exposes endpoints to the service layer:

- [backend/src/api/routes/events.py](src/api/routes/events.py) – `POST /api/rawevents`
- [backend/src/api/routes/sessions.py](src/api/routes/sessions.py) – session listing and detail read endpoints
- [backend/src/api/routes/tracks.py](src/api/routes/tracks.py) – track listing, single-track read, and manual triggering endpoints
- [backend/src/api/routes/playlists.py](src/api/routes/playlists.py) – playlist read endpoints and mix playlist creation
- [backend/src/api/routes/system.py](src/api/routes/system.py) – manual job triggers and health check

### Service layer

The service layer contains the business logic that routes call into:

- [backend/src/services/track_service.py](src/services/track_service.py) – track upsert, classification, embedding, enrichment, implicit score refresh
- [backend/src/services/playlist_service.py](src/services/playlist_service.py) – public playlist orchestration API
- [backend/src/services/playlist_mix.py](src/services/playlist_mix.py) – mix-window SQL and label computation
- [backend/src/services/playlist_context.py](src/services/playlist_context.py) – context playlist builders
- [backend/src/services/playlist_mood.py](src/services/playlist_mood.py) – mood clustering, profile scoring, and merge logic

### Classifier pipeline

- [backend/src/classifier/pipeline.py](src/classifier/pipeline.py) – unified three-stage classification pipeline
- [backend/src/classifier/layer1_heuristics.py](src/classifier/layer1_heuristics.py) – quick heuristics-based detection
- [backend/src/classifier/layer2_youtube.py](src/classifier/layer2_youtube.py) – YouTube metadata enrichment path
- [backend/src/classifier/layer3_model.py](src/classifier/layer3_model.py) – model inference entrypoint
- [backend/src/classifier/audio_embedding.py](src/classifier/audio_embedding.py) – audio download + OpenL3 embedding storage
- [backend/src/classifier/audio_utils.py](src/classifier/audio_utils.py) – shared audio download/config helpers
- [backend/src/classifier/metadata_enrichment.py](src/classifier/metadata_enrichment.py) – provider-based metadata enrichment and fallback parsing

---

## 4. Main data flow

```mermaid
flowchart LR
    A[Extension sends raw events] --> B[POST /api/rawevents]
    B --> C[RawEvent persisted]
    C --> D[upsert_track_from_event]
    D --> E[Track stub created/updated in tracks]
    E --> F[classify_pending_tracks]
    F --> G[Classifier pipeline: L1 -> L2 -> L3]
    G --> H[Track marked is_music + classification_source]
    H --> I[embed_classified_tracks]
    I --> J[Download short clip + OpenL3 embedding]
    J --> K[Store pgvector in tracks.audio_embedding]
    K --> L[refresh_implicit_track_scores]
    L --> M[Implicit score computed from watch behavior]
    M --> N[enrich_completed_tracks]
    N --> O[Gemini/OpenRouter/fallback metadata]
    O --> P[Track + metadata table updated]
    P --> Q[Playlist generators]
    Q --> R[Mix / mood / context playlists]
```

---

## 5. Processing lifecycle for a track

Each `Track` row moves through a simple status pipeline:

- `pending_classification`
- `classified`
- `embedding_done`
- `completed`
- `failed`

Status transitions are driven by service functions:

- `upsert_track_from_event()` creates the initial stub from raw event history.
- `classify_pending_tracks()` applies the classifier and writes `is_music`, metadata, and `classification_source`.
- `embed_classified_tracks()` downloads short clips, creates OpenL3 embeddings, and updates `audio_embedding`.
- `refresh_implicit_track_scores()` reads `raw_events` to compute engagement signals.
- `enrich_completed_tracks()` writes artist/song/genre/year metadata into `tracks` and `metadata`.

---

## 6. Database model summary

### `raw_events`

Stores individual event payloads from the extension, such as play/pause/seek/end operations. It is the raw source for session aggregation and engagement scoring.

### `sessions`

Aggregation table generated nightly from `raw_events` by `sync_sessions_nightly()`. It stores session boundaries and duration metrics.

### `tracks`

Canonical track-level record. The model stores:

- `video_id` as the primary key
- `raw_title`, `channel`, and other title metadata
- classification outputs such as `is_music`, `genre`, `release_year`, `classification_source`
- the vector column `audio_embedding`
- implicit engagement metrics like `implicit_score`, `replay_count`, and `total_watch_seconds`
- the current `processing_status`

### `playlists` and `playlist_tracks`

Playlist records are persisted as named windows, and each playlist contains ordered tracks with their scoring metadata.

### `metadata`

Cached metadata results are stored here keyed by `cache_key` to avoid repeated LLM calls for the same title normalization.

---

## 7. API surface

### Event ingestion

- `POST /api/rawevents`
  - Accepts a `RawEventCreate` payload.
  - Persists the event and immediately upserts a track stub if a `video_id` is present.

### Track endpoints

- `GET /api/tracks`
- `GET /api/tracks/{video_id}`
- `POST /api/tracks/embed`
- `POST /api/tracks/{video_id}/embed`
- `POST /api/tracks/enrich`

### Session endpoints

- `GET /api/sessions`
- `GET /api/sessions/{session_id}`
- `POST /api/sessions/sync`

### Playlist endpoints

- `GET /api/playlists`
- `GET /api/playlists/{playlist_id}`
- `POST /api/playlists/mix`

### System endpoints

- `POST /api/tracks/classify`
- `POST /api/tracks/{video_id}/enrich`
- `GET /health`

---

## 8. Scheduled jobs

The backend registers two main scheduled jobs in the app lifespan startup:

1. `sync_sessions_nightly()`
   - Aggregates `raw_events` into the `sessions` table.
2. `classify_tracks_nightly()`
   - Backfills any missing track stubs.
   - Runs classification on pending tracks.
   - Embeds confirmed music tracks.
   - Refreshes implicit scores.
   - Creates mood playlists.
   - Enriches metadata.
   - Builds nightly mix and context playlists.

These jobs are registered in [backend/src/main.py](src/main.py) and implemented in [backend/src/jobs.py](src/jobs.py).

---

## 9. Environment and deployment

### Runtime requirements

- Python `>=3.11`
- PostgreSQL with `pgvector` extension support
- `ffmpeg` installed for audio clipping
- `yt-dlp` for YouTube audio retrieval
- AI provider credentials for metadata enrichment (`GEMINI_API_KEY`, `OPENROUTER_API_KEY`)

### Environment variables

Recommended values used by the backend:

- `DATABASE_URL`
- `GEMINI_API_KEY`
- `GEMINI_MODEL`
- `OPENROUTER_API_KEY`
- `OPENROUTER_MODEL`
- `OPENROUTER_HTTP_REFERER`
- `OPENROUTER_APP_TITLE`
- `METADATA_PROVIDERS`

### Docker / Compose

The backend ships with:

- [backend/Dockerfile](Dockerfile) – Python 3.11 container image
- [backend/docker-compose.yml](docker-compose.yml) – API, database, and pgAdmin services

The API container exposes:

- `8000` for FastAPI

The database container uses:

- `pgvector/pgvector:pg15`

---

## 10. Notes on the classifier stack

The classifier is intentionally layered:

- `layer1_heuristics` is quick and cheap, providing a first-pass answer.
- `layer2_youtube` adds external metadata context from YouTube topics/categories.
- `layer3_model` is the heavier model inference layer and is the most runtime-sensitive part.

The pipeline wrapper in [backend/src/classifier/pipeline.py](src/classifier/pipeline.py) standardizes the result shape and keeps the service layer from depending on any one implementation detail.

---

## 11. Important operational caveats

- The backend is expected to run under the repository-local Python 3.11 environment, not just any system interpreter.
- Audio embedding depends on OpenL3 and `ffmpeg` and can be sensitive to environment configuration.
- Metadata enrichment is provider-driven; if provider keys are missing, the code falls back into heuristics.
- Playlist generation is data-driven and depends on a non-empty set of `tracks` with `audio_embedding` and implicit scoring available.

---

## 12. How to extend safely

When adding a feature or fixing a bug, keep the same structure:

1. Put API-facing entrypoints in the route package.
2. Keep business orchestration in the service package.
3. Push SQL-heavy or domain-specific calculations into focused helper modules.
4. Let the classifier package remain the only place that knows about the model pipeline details.
5. Keep database schema changes isolated in `models.py` and the `database.py` bootstrap helpers.

For a clean change, prefer:

- route changes only if a new endpoint needs to be exposed,
- service changes when the logic belongs to the backend workflow,
- helper module extraction when a function is becoming too large or specialized.

---

## 13. Clean architecture summary

The current backend layout is intentionally organized into clear responsibility boundaries:

- `routes` handle request/response surface
- `services` handle business orchestration
- `classifier` handles inference and audio embedding
- `models` and `database` are the source of truth for persistent data
- `jobs` defines scheduled batch execution

That structure makes it easier to read, test, and extend without breaking the endpoint contract.
