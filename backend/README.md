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
3. Push SQL-heavy or domain-specific calculations into focused repositories or helpers.
4. Let the classifier package remain the only place that knows about the model pipeline details.
5. Keep database schema changes isolated in `models.py` and the `database.py` bootstrap helpers.

For a clean change, prefer:

- route changes only if a new endpoint needs to be exposed,
- service changes when the logic belongs to the backend workflow,
- helper module extraction when a function is becoming too large or specialized.

---

## 13. Clean architecture summary

The current backend layout is organized into clear responsibility boundaries:

- `routes` handle request/response surface
- `repositories` handle data access and query building
- `services` handle business orchestration and scoring logic
- `classifier` handles inference and audio embedding
- `models` and `database` are the source of truth for persistent data
- `jobs` defines scheduled batch execution

---

## 14. How to Run the Project

The backend is configured to run locally using Docker Compose, which packages the FastAPI application, a PostgreSQL database with `pgvector`, and pgAdmin.

### Step 1: Set up Environment Variables
Ensure you have a `.env` file in the root of the `backend` directory (copy from `.env.example`). Adjust the keys if you want to use external classification/enrichment APIs (e.g. `GEMINI_API_KEY`, `YOUTUBE_API_KEY`).

### Step 2: Build and Start Containers
From the `backend` directory, run:
```bash
docker compose up -d --build
```
This command builds the FastAPI container, runs the database with pgvector, and exposes the services:
- **FastAPI API**: [http://localhost:8000](http://localhost:8000)
- **pgAdmin**: [http://localhost:5050](http://localhost:5050) (Login: `admin@example.com` / `admin123`)
- **PostgreSQL**: `localhost:5432`

### Step 3: Monitor Logs
To inspect startup progress, check migration application, and see print/debug logs:
```bash
docker compose logs -f api
```

---

## 15. How to Test the Recommendation Engine Manually

Since recommendation generation is data-driven, you need tracks, user watch sessions, and models in the database to generate meaningful playlists. Follow this step-by-step procedure to test the system manually:

### Step A: Ingest Simulation Data (User Behavior)
Simulate a user listening history by posting raw events to the ingestion endpoint:

```bash
# 1. User starts listening to Track A
curl -X POST http://localhost:8000/api/rawevents \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "test-session-123",
    "video_id": "dQw4w9WgXcQ",
    "event_type": "play",
    "position": 0.0,
    "timestamp": "2026-08-29T12:00:00Z"
  }'

# 2. User plays the track to completion (reaches end)
curl -X POST http://localhost:8000/api/rawevents \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "test-session-123",
    "video_id": "dQw4w9WgXcQ",
    "event_type": "end",
    "position": 210.0,
    "timestamp": "2026-08-29T12:03:30Z"
  }'

# 3. User plays another Track B in the same session
curl -X POST http://localhost:8000/api/rawevents \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "test-session-123",
    "video_id": "9bZkp7q19f0",
    "event_type": "play",
    "position": 0.0,
    "timestamp": "2026-08-29T12:03:40Z"
  }'
```

### Step B: Sync Sessions
Synchronize raw events into session aggregates (typically a nightly background job):
```bash
curl -X POST http://localhost:8000/api/sessions/sync
```

### Step C: Classify and Embed Ingested Tracks
Trigger track classification and embedding calculations to mark the stubs as confirmed music and populate `audio_embedding` values:
```bash
# 1. Run classifier
curl -X POST http://localhost:8000/api/tracks/classify

# 2. Run audio downloads & OpenL3 embedding generation
curl -X POST http://localhost:8000/api/tracks/embed
```

### Step D: Trigger Recommendation Model Refresh
Train the MiniBatchKMeans clusters, rebuild user taste profiles, and compute co-occurrence lift:
```bash
curl -X POST http://localhost:8000/api/playlists/recommendation-models/refresh
```
**Expected Response:**
```json
{
  "clusters_version": "5a4d1b3c9e2f4a08",
  "engagement_tracks": 2,
  "cooccurrence_pairs": 1,
  "taste_profile_tracks": 1
}
```

### Step E: Query and Verify Recommendations
Now that models are computed, request recommendation playlists and check the results:

#### 1. Discover Weekly
```bash
curl -X POST http://localhost:8000/api/playlists/discover-weekly \
  -H "Content-Type: application/json" \
  -d '{"limit": 5}'
```
*Verification:*
- Verify response contains the tracks.
- Check the explainability details: each track in `tracks` should have a `reason` (e.g. `"discover_weekly: vector=0.912, metadata=0.500, engagement=0.750"`) and a detailed `score_components` JSON map listing the weights.

#### 2. Song Radio
```bash
curl -X POST http://localhost:8000/api/playlists/radio \
  -H "Content-Type: application/json" \
  -d '{"seed_video_id": "dQw4w9WgXcQ", "limit": 5}'
```
*Verification:*
- Check that the returned tracks are similar in sound/metadata, and the seed track itself is omitted.

#### 3. Listeners Also Liked
```bash
curl -X POST http://localhost:8000/api/playlists/also-liked \
  -H "Content-Type: application/json" \
  -d '{"seed_video_ids": ["dQw4w9WgXcQ"], "limit": 5}'
```

---

## 16. Audio Embeddings and Mood/Cluster Playlists

### Legacy Mood Playlists
In the legacy mood playlist system (`create_mood_playlists` in `src/services/playlist_service.py`), **audio embeddings are NOT used to cluster the tracks**.
- The tracks are grouped strictly by their metadata `genre` field (e.g. "Pop Mix" for genre "Pop").
- The embeddings are only verified to be present (non-null and valid dimension).
- A helper function `score_playlist_match` calculates cosine similarity between track embeddings and playlist centroids, but it is **imported but never used** in the actual generation loop.

### Recommendation Engine Clusters
In the new recommendation engine, **audio embeddings ARE used to cluster tracks**:
- A nightly job runs `fit_track_clusters` (in `src/jobs_recommendation.py`), which uses `MiniBatchKMeans` to cluster the 512-dimension OpenL3 audio embeddings.
- Every track is assigned a stable `cluster_id` and has its `distance_to_centroid` calculated.
- These clusters serve as the partition source for the **Daily Mix / Mood Cluster** algorithm, ranking tracks within the cluster based on centroid distance, engagement score, and novelty/diversity constraints.

---

## 17. Detailed API and Nightly Job Flow

For a comprehensive guide on the data flow lifecycle, refer to the [wavecask_api_flow.md](.gemini/antigravity/brain/33d0aad6-e189-438b-a66c-7075fed218bc/artifacts/wavecask_api_flow.md) artifact, which describes the flow from user event ingestion to weekly discovery playlist builds.

### Nightly Job Summary
The system executes three primary background processes sequentially:
1. **`sync_sessions_nightly`** (at `02:00 UTC`): Aggregates raw log entries into session boundaries.
2. **`classify_tracks_nightly`** (at `02:05 UTC`): Runs classification, downloads audio, computes 512-dimensional OpenL3 vectors, refreshes engagement metrics, and runs LLM-based metadata enrichment.
3. **`recommendation_models_nightly`** (at `04:00 UTC`): Rebuilds user profiles, updates `MiniBatchKMeans` centroids/clusters, and builds the weekly **Discover Weekly** recommendations.

### Manual triggers
To bypass the nightly job schedule for debugging or testing, you can trigger these phases immediately via POST requests to the following system APIs:
* **Session Sync:** `POST /api/sessions/sync`
* **Full Processing (Classification/Embedding/Enrichment):** `POST /api/tracks/classify`
* **Embeddings (All/Single):** `POST /api/tracks/embed` or `POST /api/tracks/{video_id}/embed`
* **Enrichment (All/Single):** `POST /api/tracks/enrich` or `POST /api/tracks/{video_id}/enrich`
* **Rebuild Recommendation Models:** `POST /api/playlists/recommendation-models/refresh`
* **On-Demand Discover Weekly:** `POST /api/playlists/discover-weekly`


