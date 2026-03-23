"""
MusicBridge — тест с реальными токенами.
Запускать локально: python3 test_real.py
"""
import asyncio
import json
import tidalapi
import spotipy
from spotipy.oauth2 import SpotifyOAuth
from sync_engine import TrackSyncer, ArtistSyncer, AlbumSyncer

# ─── НАСТРОЙКИ ────────────────────────────────────────────────────
SPOTIFY_CLIENT_ID     = "ВАШ_CLIENT_ID"
SPOTIFY_CLIENT_SECRET = "ВАШ_CLIENT_SECRET"
SPOTIFY_REDIRECT_URI  = "http://127.0.0.1:8080"

# Что тестируем
SOURCE      = "tidal"    # "tidal" или "spotify"
DESTINATION = "spotify"  # "tidal" или "spotify"
SYNC_TYPE   = "tracks"   # "tracks", "artists", "albums"
STRATEGY    = "skip"     # "skip" или "replace"
DRY_RUN     = True       # True = только читаем, не добавляем
LIMIT       = 5          # сколько треков обрабатываем в тесте
# ──────────────────────────────────────────────────────────────────

GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
RESET  = "\033[0m"

def log(msg, level="info"):
    colors = {"info": CYAN, "success": GREEN, "error": RED, "log-info": YELLOW, "visualize": ""}
    color = colors.get(level, "")
    prefix = {"info": "►", "success": "✓", "error": "✗", "log-info": "~", "visualize": "🖼"}.get(level, "•")
    if level == "visualize" and isinstance(msg, dict):
        d = msg.get("data", {})
        src  = d.get("source", {})
        dest = d.get("dest", {})
        print(f"  🖼  {src.get('artist')} — {src.get('title')}  →  {dest.get('artist')} — {dest.get('title')}")
        print(f"      cover: {src.get('cover', 'n/a')[:60]}...")
    else:
        print(f"{color}{prefix} [{level}] {msg}{RESET}")

async def sse_print(msg, level="info"):
    log(msg, level)

async def init_tidal():
    print(f"\n{CYAN}── Tidal Auth ──{RESET}")
    session = tidalapi.Session()
    login, future = session.login_oauth()
    print(f"{YELLOW}Открой в браузере:{RESET} {login.verification_uri_complete}\n")
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, future.result)
    if session.check_login():
        print(f"{GREEN}✓ Tidal OK — User ID: {session.user.id}{RESET}")
        return session
    raise Exception("Tidal login failed")

async def init_spotify():
    print(f"\n{CYAN}── Spotify Auth ──{RESET}")
    loop = asyncio.get_running_loop()
    def _auth():
        sp = spotipy.Spotify(auth_manager=SpotifyOAuth(
            client_id=SPOTIFY_CLIENT_ID,
            client_secret=SPOTIFY_CLIENT_SECRET,
            redirect_uri=SPOTIFY_REDIRECT_URI,
            scope="user-library-read user-library-modify user-follow-read user-follow-modify"
        ))
        user = sp.current_user()
        return sp, user
    sp, user = await loop.run_in_executor(None, _auth)
    print(f"{GREEN}✓ Spotify OK — {user['display_name']} ({user.get('email', user['id'])}){RESET}")
    return sp

async def main():
    print(f"\n{'='*55}")
    print(f"  MusicBridge Real Token Test")
    print(f"  {SOURCE.upper()} → {DESTINATION.upper()} | type={SYNC_TYPE} | dry_run={DRY_RUN}")
    print(f"{'='*55}")

    # Auth
    sp_client     = None
    tidal_session = None
    platforms = [SOURCE, DESTINATION]

    if "spotify" in platforms:
        sp_client = await init_spotify()
    if "tidal" in platforms:
        tidal_session = await init_tidal()

    # Синкер
    SYNCER_MAP = {"tracks": TrackSyncer, "artists": ArtistSyncer, "albums": AlbumSyncer}
    syncer = SYNCER_MAP[SYNC_TYPE](sp_client, tidal_session, STRATEGY)

    # Читаем source
    print(f"\n{CYAN}── Source Library ({SOURCE.upper()}) ──{RESET}")
    source_items = await syncer.get_items(SOURCE)
    print(f"  Найдено: {len(source_items)} {SYNC_TYPE}")

    if not source_items:
        print(f"{RED}  Пусто — проверь авторизацию и библиотеку{RESET}")
        return

    # Показываем первые LIMIT
    print(f"\n  Первые {min(LIMIT, len(source_items))} записей:")
    for item in source_items[:LIMIT]:
        isrc = item.get('isrc', 'n/a')
        cover = '✓' if item.get('cover') else '✗'
        preview = '✓' if item.get('preview_url') else '✗'
        artist = item.get('artist', item.get('name', '?'))
        name   = item.get('name', '')
        print(f"    • {artist} — {name}")
        print(f"      isrc={isrc}  cover={cover}  preview={preview}")

    # Читаем dest
    print(f"\n{CYAN}── Dest Library ({DESTINATION.upper()}) ──{RESET}")
    dest_items = await syncer.get_items(DESTINATION)
    print(f"  Найдено: {len(dest_items)} {SYNC_TYPE}")

    # Dry-run: поиск без добавления
    print(f"\n{CYAN}── Search Test (первые {LIMIT} треков) ──{RESET}")
    for item in source_items[:LIMIT]:
        artist = item.get('artist', item.get('name', ''))
        name   = item.get('name', '')
        query  = f"{artist} {name}".strip()
        match  = await syncer.search_item(DESTINATION, query)
        if match:
            print(f"  {GREEN}✓{RESET} {query[:45]:<45} → {match['name'][:30]}")
        else:
            print(f"  {RED}✗{RESET} {query[:45]:<45} → NOT FOUND")

    if not DRY_RUN:
        print(f"\n{CYAN}── Full Sync ──{RESET}")
        await syncer.run(SOURCE, DESTINATION, sse_print)
    else:
        print(f"\n{YELLOW}DRY_RUN=True — добавление пропущено.{RESET}")
        print(f"Установи DRY_RUN=False для реального sync.\n")

asyncio.run(main())
