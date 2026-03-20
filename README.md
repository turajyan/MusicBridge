# MusicBridge 🎵

Cross-platform music library sync tool. Stream your favorites between **Tidal** and **Spotify** via a real-time SSE API.

## Stack

- **Backend**: FastAPI + uvicorn
- **Tidal**: tidalapi (OAuth device flow)
- **Spotify**: spotipy (OAuth2 PKCE)
- **Streaming**: Server-Sent Events (SSE)

## Setup

```bash
pip install -r requirements.txt
```

Set your Spotify credentials in `app/main.py`:

```python
SPOTIFY_CLIENT_ID     = "your_client_id"
SPOTIFY_CLIENT_SECRET = "your_client_secret"
SPOTIFY_REDIRECT_URI  = "http://localhost:8080"
```

## Run

```bash
python app/main.py
```

Server starts at `http://localhost:8000`

## API

### POST `/api/v1/sync/start`

```json
{
  "source": "tidal",
  "destination": "spotify",
  "type": "tracks"
}
```

Returns an SSE stream of sync progress events:

```json
{"msg": "TIDAL ACCESS GRANTED.", "level": "success"}
{"msg": "Extracted 120 tracks from TIDAL.", "level": "success"}
```

### Levels

| Level | Meaning |
|-------|---------|
| `info` | General progress |
| `success` | Step completed |
| `error` | Action required / failure |

## Supported Platforms

| Platform | Source | Destination |
|----------|--------|-------------|
| Tidal | ✅ | 🔜 |
| Spotify | ✅ | 🔜 |
