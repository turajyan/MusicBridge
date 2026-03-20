import os
import asyncio
import json
import tidalapi
import spotipy
from spotipy.oauth2 import SpotifyOAuth
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sync_engine import ArtistSyncer, TrackSyncer, AlbumSyncer

app = FastAPI(title="MusicBridge Sync Engine")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

SPOTIFY_CLIENT_ID     = os.getenv("SPOTIFY_CLIENT_ID", "default_id")
SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET", "default_secret")
SPOTIFY_REDIRECT_URI  = os.getenv("SPOTIFY_REDIRECT_URI", "http://localhost:8080")

SYNCER_MAP = {
    "artists": ArtistSyncer,
    "tracks":  TrackSyncer,
    "albums":  AlbumSyncer,
}

class SyncPayload(BaseModel):
    source:      str
    destination: str
    type:        str
    strategy:    str = "skip"  # 'skip' или 'replace'

async def sync_streamer(payload: SyncPayload):
    def sse_sync(msg, level: str = "info") -> str:
        return f"data: {json.dumps({'msg': msg, 'level': level})}\n\n"

    # async-обёртка для передачи в engine.run()
    async def sse(msg, level: str = "info"):
        pass  # используется только как сигнатура — yield ниже

    yield sse_sync(f"SYSTEM BOOT: {payload.source.upper()} -> {payload.destination.upper()}", "info")
    loop = asyncio.get_running_loop()

    # --- ИНИЦИАЛИЗАЦИЯ КЛИЕНТОВ ---
    sp_client     = None
    tidal_session = None

    if "spotify" in [payload.source, payload.destination]:
        yield sse_sync("Awaiting Spotify Authorization in browser...", "error")
        def init_spotify():
            return spotipy.Spotify(auth_manager=SpotifyOAuth(
                client_id=SPOTIFY_CLIENT_ID,
                client_secret=SPOTIFY_CLIENT_SECRET,
                redirect_uri=SPOTIFY_REDIRECT_URI,
                scope="user-library-read user-library-modify user-follow-read user-follow-modify"
            ))
        try:
            sp_client = await loop.run_in_executor(None, init_spotify)
            await loop.run_in_executor(None, sp_client.current_user)
            yield sse_sync("SPOTIFY READY.", "success")
        except Exception as e:
            yield sse_sync(f"Spotify Auth Error: {str(e)}", "error")
            return

    if "tidal" in [payload.source, payload.destination]:
        tidal_session = tidalapi.Session()
        login, future = tidal_session.login_oauth()
        yield sse_sync("===================================", "error")
        yield sse_sync("TIDAL ACTION REQUIRED. Click link to authorize:", "error")
        yield sse_sync(f"<a href='{login.verification_uri_complete}' target='_blank' style='color:#ccff00;'>{login.verification_uri_complete}</a>", "success")
        yield sse_sync("===================================", "error")
        try:
            await loop.run_in_executor(None, future.result)
            if tidal_session.check_login():
                yield sse_sync("TIDAL READY.", "success")
            else:
                raise Exception("Tidal session check failed.")
        except Exception as e:
            yield sse_sync(f"Tidal Auth Error: {str(e)}", "error")
            return

    # --- ВЫБОР И ЗАПУСК ДВИЖКА ---
    syncer_class = SYNCER_MAP.get(payload.type)
    if not syncer_class:
        yield sse_sync(f"Unknown sync type: '{payload.type}'. Supported: {list(SYNCER_MAP.keys())}", "error")
        return

    engine = syncer_class(sp_client, tidal_session, payload.strategy)

    # Буфер SSE-сообщений из engine, т.к. движок async но не генератор
    queue = asyncio.Queue()

    async def sse_bridge(msg, level="info"):
        await queue.put(sse_sync(msg, level))

    async def run_engine():
        await engine.run(payload.source, payload.destination, sse_bridge)
        await queue.put(None)  # сигнал завершения

    engine_task = asyncio.create_task(run_engine())

    while True:
        item = await queue.get()
        if item is None:
            break
        yield item

    await engine_task
    yield sse_sync("SYNC PROTOCOL COMPLETED.", "success")

@app.post("/api/v1/sync/start")
async def start_sync(payload: SyncPayload):
    return StreamingResponse(sync_streamer(payload), media_type="text/event-stream")
