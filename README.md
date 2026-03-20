# MusicBridge 🎵

Cross-platform music library sync tool. Streams your favorites between **Tidal** and **Spotify** via a real-time SSE API.

## Stack

- **Backend**: FastAPI + uvicorn
- **Frontend**: nginx (reverse proxy + static)
- **Tidal**: tidalapi (OAuth device flow)
- **Spotify**: spotipy (OAuth2)
- **Streaming**: Server-Sent Events (SSE)

## Sync Algorithm

```
For each track in source library:
  1. Has ISRC?
     ├── YES → check if ISRC exists in destination
     │         ├── EXISTS  → SKIP (100% accurate duplicate detection)
     │         └── MISSING → search by "Artist + Title" → ADD
     └── NO  → search by "Artist + Title" → ADD
```

**ISRC** (International Standard Recording Code) is a unique global identifier per recording. Using it as the primary key guarantees zero false duplicates — no mismatches from title variations, reissues, or regional differences.

Fallback to `"Artist + Title"` search handles edge cases where ISRC metadata is absent.

## Setup

```bash
git clone https://github.com/turajyan/MusicBridge.git
cd MusicBridge
cp .env.example .env
# Fill in your Spotify credentials in .env
docker-compose up --build
```

## Endpoints

- **UI**: `http://localhost:80`
- **API**: `http://localhost:80/api/`
- **Spotify callback**: `http://localhost:8080`

## API

### POST `/api/v1/sync/start`

```json
{
  "source": "tidal",
  "destination": "spotify",
  "type": "tracks"
}
```

Returns an SSE stream:

```
data: {"msg": "TIDAL READY.", "level": "success"}
data: {"msg": "Found 120 tracks in Source.", "level": "success"}
data: {"msg": "SKIPPED: Pink Floyd - Comfortably Numb (Already exists)", "level": "info"}
data: {"msg": "ADDED: Radiohead - Creep", "level": "success"}
data: {"msg": "NOT FOUND: Some Obscure Track", "level": "error"}
```

### SSE Levels

| Level | Meaning |
|-------|---------|
| `info` | Progress / skipped |
| `success` | Step completed / track added |
| `error` | Action required / not found / failure |

## Supported Directions

| Source | Destination | Status |
|--------|-------------|--------|
| Tidal | Spotify | ✅ |
| Spotify | Tidal | ✅ |
