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

app = FastAPI(title="MusicBridge Sync Engine")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID", "default_id")
SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET", "default_secret")
SPOTIFY_REDIRECT_URI = os.getenv("SPOTIFY_REDIRECT_URI", "http://localhost:8080")

class SyncPayload(BaseModel):
    source: str
    destination: str
    type: str

async def sync_streamer(payload: SyncPayload):
    def sse(msg: str, level: str = "info") -> str:
        return f"data: {json.dumps({'msg': msg, 'level': level})}\n\n"

    yield sse(f"SYSTEM BOOT: {payload.source.upper()} -> {payload.destination.upper()}", "info")
    loop = asyncio.get_running_loop()

    # --- ИНИЦИАЛИЗАЦИЯ КЛИЕНТОВ ---
    sp_client = None
    tidal_session = None

    if "spotify" in [payload.source, payload.destination]:
        yield sse("Awaiting Spotify Authorization in browser...", "error")
        def init_spotify():
            auth_manager = SpotifyOAuth(
                client_id=SPOTIFY_CLIENT_ID,
                client_secret=SPOTIFY_CLIENT_SECRET,
                redirect_uri=SPOTIFY_REDIRECT_URI,
                scope="user-library-read user-library-modify"
            )
            return spotipy.Spotify(auth_manager=auth_manager)
        try:
            sp_client = await loop.run_in_executor(None, init_spotify)
            await loop.run_in_executor(None, sp_client.current_user)
            yield sse("SPOTIFY READY.", "success")
        except Exception as e:
            yield sse(f"Spotify Auth Error: {str(e)}", "error")
            return

    if "tidal" in [payload.source, payload.destination]:
        tidal_session = tidalapi.Session()
        login, future = tidal_session.login_oauth()
        yield sse("===================================", "error")
        yield sse(f"TIDAL ACTION REQUIRED. Click link to authorize:", "error")
        yield sse(f"<a href='{login.verification_uri_complete}' target='_blank' style='color:#ccff00;'>{login.verification_uri_complete}</a>", "success")
        yield sse("===================================", "error")
        try:
            await loop.run_in_executor(None, future.result)
            if tidal_session.check_login():
                yield sse("TIDAL READY.", "success")
            else:
                raise Exception("Tidal session check failed.")
        except Exception as e:
            yield sse(f"Tidal Auth Error: {str(e)}", "error")
            return

    # --- СБОР ДАННЫХ ИЗ ИСТОЧНИКА ---
    yield sse(f"Reading library from {payload.source.upper()}...", "info")
    source_tracks = []  # Формат: {"artist": str, "title": str, "isrc": str}

    if payload.source == "spotify":
        def get_sp_tracks():
            results = sp_client.current_user_saved_tracks(limit=50)
            return [{"artist": item['track']['artists'][0]['name'], "title": item['track']['name'], "isrc": item['track']['external_ids'].get('isrc')} for item in results['items']]
        source_tracks = await loop.run_in_executor(None, get_sp_tracks)

    elif payload.source == "tidal":
        def get_td_tracks():
            return [{"artist": t.artist.name, "title": t.name, "isrc": t.isrc} for t in tidal_session.user.favorites.tracks()[:50]]
        source_tracks = await loop.run_in_executor(None, get_td_tracks)

    yield sse(f"Found {len(source_tracks)} tracks in Source.", "success")

    # --- СИНХРОНИЗАЦИЯ В НАЗНАЧЕНИЕ ---
    yield sse(f"Pushing to {payload.destination.upper()}...", "info")

    # 1. Загружаем текущую библиотеку назначения для логики "Skip if exists"
    dest_isrcs = set()
    if payload.destination == "spotify":
        def get_sp_dest():
            res = sp_client.current_user_saved_tracks(limit=50)
            return {item['track']['external_ids'].get('isrc') for item in res['items'] if item['track']['external_ids'].get('isrc')}
        dest_isrcs = await loop.run_in_executor(None, get_sp_dest)
    elif payload.destination == "tidal":
        def get_td_dest():
            return {t.isrc for t in tidal_session.user.favorites.tracks()[:50] if t.isrc}
        dest_isrcs = await loop.run_in_executor(None, get_td_dest)

    # 2. Матчинг и добавление
    for track in source_tracks:
        await asyncio.sleep(0.5)  # Пауза против Rate Limit

        if track["isrc"] and track["isrc"] in dest_isrcs:
            yield sse(f"SKIPPED: {track['artist']} - {track['title']} (Already exists)", "info")
            continue

        query = f"{track['artist']} {track['title']}"

        try:
            if payload.destination == "spotify":
                def search_and_add_sp():
                    res = sp_client.search(q=query, type='track', limit=1)
                    if res['tracks']['items']:
                        sp_id = res['tracks']['items'][0]['id']
                        sp_client.current_user_saved_tracks_add([sp_id])
                        return True
                    return False
                success = await loop.run_in_executor(None, search_and_add_sp)

            elif payload.destination == "tidal":
                def search_and_add_td():
                    res = tidal_session.search("track", query)
                    if res['tracks']:
                        td_id = res['tracks'][0].id
                        tidal_session.user.favorites.add_track(td_id)
                        return True
                    return False
                success = await loop.run_in_executor(None, search_and_add_td)

            if success:
                yield sse(f"ADDED: {track['artist']} - {track['title']}", "success")
            else:
                yield sse(f"NOT FOUND: {track['artist']} - {track['title']}", "error")

        except Exception as e:
            yield sse(f"FAILED: {track['title']} ({str(e)})", "error")

    yield sse("SYNC PROTOCOL COMPLETED.", "success")

@app.post("/api/v1/sync/start")
async def start_sync(payload: SyncPayload):
    return StreamingResponse(sync_streamer(payload), media_type="text/event-stream")
