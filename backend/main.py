import asyncio
import json
import pathlib
import cancel
import tidalapi
import spotipy
from spotipy.oauth2 import SpotifyOAuth
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sync_engine import ArtistSyncer, TrackSyncer, AlbumSyncer

try:
    import config
    SPOTIFY_CLIENT_ID     = config.SPOTIFY_CLIENT_ID
    SPOTIFY_CLIENT_SECRET = config.SPOTIFY_CLIENT_SECRET
    SPOTIFY_REDIRECT_URI  = config.SPOTIFY_REDIRECT_URI
except ImportError:
    raise RuntimeError("config.py not found. Copy config.example.py -> config.py and fill in your credentials.")

TIDAL_SESSION_FILE = pathlib.Path("tidal_session.json")

app = FastAPI(title="MusicBridge Sync Engine")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

SYNCER_MAP = {
    "artists": ArtistSyncer,
    "tracks":  TrackSyncer,
    "albums":  AlbumSyncer,
}

SSE_HEADERS = {
    "X-Accel-Buffering": "no",
    "Cache-Control":     "no-cache",
    "Connection":        "keep-alive",
}


# ─── Глобальный PKCE state (один логин за раз) ────────────────────
_pkce_session: tidalapi.Session | None = None
_pkce_url:     str | None = None

# ─── Models ───────────────────────────────────────────────────────
class SyncPayload(BaseModel):
    source:      str
    destination: str
    type:        str
    strategy:    str = "skip"

class TidalCallbackPayload(BaseModel):
    oops_url: str  # URL страницы "Oops" после логина

# ─── Tidal Auth Helpers ───────────────────────────────────────────
def _load_tidal_session() -> tidalapi.Session | None:
    """Загружает сессию из файла. Возвращает None если файла нет или сессия протухла."""
    if not TIDAL_SESSION_FILE.exists():
        return None
    try:
        session = tidalapi.Session()
        session.load_session_from_file(TIDAL_SESSION_FILE)
        if session.check_login():
            return session
    except Exception:
        pass
    return None

def _save_tidal_session(session: tidalapi.Session):
    session.save_session_to_file(TIDAL_SESSION_FILE)

# ─── Auth Endpoints ───────────────────────────────────────────────
@app.get("/auth/tidal")
async def tidal_auth_start():
    """
    Возвращает PKCE URL для авторизации.
    Если сессия уже есть — сообщает об этом.
    """
    global _pkce_session, _pkce_url

    # Удаляем битый файл сессии если есть
    try:
        session = await asyncio.get_running_loop().run_in_executor(None, _load_tidal_session)
        if session:
            return JSONResponse({"status": "already_authorized", "user_id": session.user.id})
    except Exception as e:
        # Файл есть но битый — удаляем
        if TIDAL_SESSION_FILE.exists():
            TIDAL_SESSION_FILE.unlink()

    # Создаём новую PKCE сессию
    try:
        _pkce_session = tidalapi.Session()
        _pkce_url = _pkce_session.pkce_login_url()
        return JSONResponse({"status": "auth_required", "url": _pkce_url})
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to init Tidal session: {str(e)}")

@app.post("/auth/tidal/callback")
async def tidal_auth_callback(payload: TidalCallbackPayload):
    """
    Принимает URL страницы 'Oops' после логина в Tidal.
    Завершает PKCE авторизацию и сохраняет сессию.
    """
    global _pkce_session

    if not _pkce_session:
        raise HTTPException(status_code=400, detail="Auth not started. Call GET /auth/tidal first.")

    loop = asyncio.get_running_loop()

    try:
        token = await loop.run_in_executor(
            None, lambda: _pkce_session.pkce_get_auth_token(payload.oops_url)
        )
        await loop.run_in_executor(
            None, lambda: _pkce_session.process_auth_token(token, is_pkce_token=True)
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Tidal auth failed: {str(e)}")

    if not _pkce_session.check_login():
        raise HTTPException(status_code=401, detail="Tidal session invalid after auth.")

    await loop.run_in_executor(None, lambda: _save_tidal_session(_pkce_session))

    user_id = _pkce_session.user.id
    _pkce_session = None  # сбрасываем state
    return JSONResponse({"status": "authorized", "user_id": user_id})

@app.delete("/auth/tidal")
async def tidal_auth_logout():
    """Удаляет сохранённую сессию Tidal."""
    if TIDAL_SESSION_FILE.exists():
        TIDAL_SESSION_FILE.unlink()
    return JSONResponse({"status": "logged_out"})

@app.get("/debug/spotify")
async def debug_spotify():
    """Показывает текущий токен и скоупы Spotify."""
    import spotipy
    from spotipy.oauth2 import SpotifyOAuth
    try:
        sp = spotipy.Spotify(auth_manager=SpotifyOAuth(
            client_id=SPOTIFY_CLIENT_ID,
            client_secret=SPOTIFY_CLIENT_SECRET,
            redirect_uri=SPOTIFY_REDIRECT_URI,
            scope="user-library-read user-library-modify user-follow-read user-follow-modify"
        ))
        token_info = sp.auth_manager.get_cached_token()
        user = sp.current_user()
        return JSONResponse({
            "user": user.get("display_name"),
            "user_id": user.get("id"),
            "scope": token_info.get("scope") if token_info else "no cached token",
            "token_type": token_info.get("token_type") if token_info else None,
        })
    except Exception as e:
        return JSONResponse({"error": str(e)})

@app.post("/api/v1/sync/stop")
async def stop_sync():
    cancel.stop()
    return JSONResponse({"status": "stopping"})

@app.get("/auth/tidal/status")
async def tidal_auth_status():
    """Проверяет статус авторизации Tidal."""
    session = await asyncio.get_running_loop().run_in_executor(None, _load_tidal_session)
    if session:
        return JSONResponse({"authorized": True, "user_id": session.user.id})
    return JSONResponse({"authorized": False})

# ─── Sync ─────────────────────────────────────────────────────────
async def sync_streamer(payload: SyncPayload):
    def sse(msg, level: str = "info") -> str:
        return f"data: {json.dumps({'msg': msg, 'level': level})}\n\n"

    cancel.reset()

    yield sse(f"SYSTEM BOOT: {payload.source.upper()} -> {payload.destination.upper()}", "info")

    # Ранняя валидация типа
    syncer_class = SYNCER_MAP.get(payload.type)
    if not syncer_class:
        yield sse(f"Unknown sync type: '{payload.type}'. Supported: {list(SYNCER_MAP.keys())}", "error")
        yield sse("TERMINATED.", "error")
        return

    loop = asyncio.get_running_loop()
    sp_client     = None
    tidal_session = None

    # ── Spotify ──
    if "spotify" in [payload.source, payload.destination]:
        yield sse("Awaiting Spotify Authorization in browser...", "error")
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
            yield sse("SPOTIFY READY.", "success")
        except Exception as e:
            yield sse(f"Spotify Auth Error: {str(e)}", "error")
            yield sse("TERMINATED.", "error")
            return

    # ── Tidal: файл → иначе просим авторизоваться ──
    if "tidal" in [payload.source, payload.destination]:
        tidal_session = await loop.run_in_executor(None, _load_tidal_session)
        if tidal_session:
            yield sse(f"TIDAL READY (saved session). User: {tidal_session.user.id}", "success")
        else:
            yield sse("TIDAL NOT AUTHORIZED.", "error")
            yield sse("Открой /auth/tidal в браузере, авторизуйся и передай Oops-URL на /auth/tidal/callback", "error")
            yield sse("TERMINATED.", "error")
            return

    # ── Запуск движка ──
    engine = syncer_class(sp_client, tidal_session, payload.strategy)
    queue  = asyncio.Queue()

    async def sse_bridge(msg, level="info"):
        await queue.put(sse(msg, level))

    async def run_engine():
        try:
            await engine.run(payload.source, payload.destination, sse_bridge)
        except Exception as e:
            await queue.put(sse(f"Engine error: {str(e)}", "error"))
        finally:
            await queue.put(None)

    engine_task = asyncio.create_task(run_engine())
    while True:
        if cancel.is_cancelled():
            engine_task.cancel()
            yield sse("Sync cancelled by user.", "error")
            yield sse("TERMINATED.", "error")
            break
        try:
            item = await asyncio.wait_for(queue.get(), timeout=1.0)
        except asyncio.TimeoutError:
            continue
        if item is None:
            break
        yield item

    if not _sync_cancelled:
        await engine_task
        yield sse("SYNC PROTOCOL COMPLETED.", "success")

@app.post("/api/v1/sync/start")
async def start_sync(payload: SyncPayload):
    return StreamingResponse(sync_streamer(payload), media_type="text/event-stream", headers=SSE_HEADERS)


# ─── Static Frontend ──────────────────────────────────────────────
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import pathlib
import cancel

_static_dir = pathlib.Path(__file__).parent / "static"
if _static_dir.exists():
    app.mount("/static", StaticFiles(directory=_static_dir), name="static")

    @app.get("/")
    async def root():
        return FileResponse(_static_dir / "index.html")
