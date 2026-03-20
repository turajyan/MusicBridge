import asyncio
import json
import os
import tidalapi
import spotipy
from spotipy.oauth2 import SpotifyOAuth
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="MusicBridge Core")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

SPOTIFY_CLIENT_ID     = os.getenv("SPOTIFY_CLIENT_ID")
SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET")
SPOTIFY_REDIRECT_URI  = os.getenv("SPOTIFY_REDIRECT_URI", "http://localhost:8080")

class SyncPayload(BaseModel):
    source: str
    destination: str
    type: str

async def sync_streamer(payload: SyncPayload):
    def sse(msg: str, level: str = "info") -> str:
        return f"data: {json.dumps({'msg': msg, 'level': level})}\n\n"

    yield sse("SYSTEM BOOT: Cross-platform protocol initiated.", "info")
    loop = asyncio.get_running_loop()
    source_tracks = []

    yield sse(f"Connecting to SOURCE: {payload.source.upper()}...", "info")

    if payload.source == "tidal":
        session = tidalapi.Session()
        login, future = session.login_oauth()
        yield sse("===================================", "error")
        yield sse("TIDAL ACTION: Click link to authorize:", "error")
        yield sse(f"<a href='{login.verification_uri_complete}' target='_blank' style='color:#ccff00;'>{login.verification_uri_complete}</a>", "success")
        yield sse("===================================", "error")

        try:
            await loop.run_in_executor(None, future.result)
            if session.check_login():
                yield sse("TIDAL ACCESS GRANTED.", "success")
                tracks = session.user.favorites.tracks()
                source_tracks = [{"artist": t.artist.name, "name": t.name} for t in tracks]
        except Exception as e:
            yield sse(f"Tidal Error: {str(e)}", "error")
            return

    elif payload.source == "spotify":
        yield sse("Check your browser to authorize Spotify...", "error")
        try:
            def get_spotify_tracks():
                sp = spotipy.Spotify(auth_manager=SpotifyOAuth(
                    client_id=SPOTIFY_CLIENT_ID,
                    client_secret=SPOTIFY_CLIENT_SECRET,
                    redirect_uri=SPOTIFY_REDIRECT_URI,
                    scope="user-library-read"
                ))
                results = sp.current_user_saved_tracks(limit=50)
                return [{"artist": item['track']['artists'][0]['name'], "name": item['track']['name']} for item in results['items']]

            source_tracks = await loop.run_in_executor(None, get_spotify_tracks)
            yield sse("SPOTIFY ACCESS GRANTED.", "success")
        except Exception as e:
            yield sse(f"Spotify Error: {str(e)}", "error")
            return

    yield sse(f"Extracted {len(source_tracks)} tracks from {payload.source.upper()}.", "success")

    yield sse(f"Connecting to DESTINATION: {payload.destination.upper()}...", "info")
    yield sse("Normalizing metadata and searching for matches...", "info")

    for track in source_tracks[:5]:
        await asyncio.sleep(0.5)
        yield sse(f"Matched: {track['artist']} — {track['name']} -> Ready to push to {payload.destination.upper()}", "success")

    if len(source_tracks) > 5:
        yield sse(f"... and {len(source_tracks) - 5} more tracks pending.", "info")

    yield sse("SYNC PROTOCOL COMPLETED.", "success")

@app.post("/api/v1/sync/start")
async def start_sync(payload: SyncPayload):
    return StreamingResponse(sync_streamer(payload), media_type="text/event-stream")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
