"""
MusicBridge — тест с реальными токенами.
Запускать локально: python3 test_real.py
Настройки — в test_config.py (не попадает в git).
"""
import asyncio
import pathlib
from sync_engine import TrackSyncer, ArtistSyncer, AlbumSyncer

try:
    import test_config as cfg
except ImportError:
    print("ERROR: test_config.py не найден.")
    print("Скопируй: cp test_config.example.py test_config.py и заполни токены.")
    exit(1)

import tidalapi, spotipy
from spotipy.oauth2 import SpotifyOAuth

GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
RESET  = "\033[0m"

TIDAL_SESSION_FILE = pathlib.Path("tidal_session.json")

def log(msg, level="info"):
    colors = {"info": CYAN, "success": GREEN, "error": RED, "log-info": YELLOW}
    prefix = {"info": "►", "success": "✓", "error": "✗", "log-info": "~", "visualize": "🖼"}.get(level, "•")
    if level == "visualize" and isinstance(msg, dict):
        d    = msg.get("data", {})
        src  = d.get("source", {})
        dest = d.get("dest", {})
        print(f"  🖼  {src.get('artist')} — {src.get('title')}  →  {dest.get('artist')} — {dest.get('title')}")
        print(f"      cover: {src.get('cover', 'n/a')[:60]}...")
    else:
        color = colors.get(level, "")
        print(f"{color}{prefix} [{level}] {msg}{RESET}")

async def sse_print(msg, level="info"):
    log(msg, level)

async def init_tidal():
    """
    Использует PKCE flow через login_session_file(do_pkce=True):
    - Если tidal_session.json существует и валиден — логинится без браузера
    - Если нет — показывает PKCE URL, ждёт вставки redirect URL ("Oops" страница)
    - Сохраняет сессию автоматически
    """
    print(f"\n{CYAN}── Tidal Auth (PKCE) ──{RESET}")
    session = tidalapi.Session()
    loop    = asyncio.get_running_loop()

    def _do_login():
        # fn_print — перехватываем вывод библиотеки для красивого отображения
        def fn_print(msg):
            if "http" in msg.lower():
                print(f"\n{YELLOW}Открой в браузере:{RESET}")
                print(f"  {msg}")
                print(f"\n{YELLOW}После логина браузер перейдёт на страницу с ошибкой ('Oops').")
                print(f"Скопируй URL этой страницы и вставь ниже.{RESET}\n")
            else:
                print(f"  {msg}")

        return session.login_session_file(TIDAL_SESSION_FILE, do_pkce=True, fn_print=fn_print)

    result = await loop.run_in_executor(None, _do_login)

    if result and session.check_login():
        print(f"{GREEN}✓ Tidal OK — User ID: {session.user.id}{RESET}")
        return session

    raise Exception("Tidal login failed")

async def init_spotify():
    print(f"\n{CYAN}── Spotify Auth ──{RESET}")
    loop = asyncio.get_running_loop()
    def _auth():
        sp   = spotipy.Spotify(auth_manager=SpotifyOAuth(
            client_id=cfg.SPOTIFY_CLIENT_ID,
            client_secret=cfg.SPOTIFY_CLIENT_SECRET,
            redirect_uri=cfg.SPOTIFY_REDIRECT_URI,
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
    print(f"  {cfg.SOURCE.upper()} → {cfg.DESTINATION.upper()} | type={cfg.SYNC_TYPE} | dry_run={cfg.DRY_RUN}")
    print(f"{'='*55}")

    sp_client     = None
    tidal_session = None
    platforms     = [cfg.SOURCE, cfg.DESTINATION]

    if "spotify" in platforms:
        sp_client = await init_spotify()
    if "tidal" in platforms:
        tidal_session = await init_tidal()

    SYNCER_MAP = {"tracks": TrackSyncer, "artists": ArtistSyncer, "albums": AlbumSyncer}
    syncer = SYNCER_MAP[cfg.SYNC_TYPE](sp_client, tidal_session, cfg.STRATEGY)

    # Читаем source
    print(f"\n{CYAN}── Source Library ({cfg.SOURCE.upper()}) ──{RESET}")
    source_items = await syncer.get_items(cfg.SOURCE)
    print(f"  Найдено: {len(source_items)} {cfg.SYNC_TYPE}")

    if not source_items:
        print(f"{RED}  Пусто — проверь авторизацию и библиотеку{RESET}")
        return

    print(f"\n  Первые {min(cfg.LIMIT, len(source_items))} записей:")
    for item in source_items[:cfg.LIMIT]:
        artist  = item.get('artist', item.get('name', '?'))
        name    = item.get('name', '')
        isrc    = item.get('isrc', 'n/a')
        cover   = '✓' if item.get('cover') else '✗'
        preview = '✓' if item.get('preview_url') else '✗'
        print(f"    • {artist} — {name}")
        print(f"      isrc={isrc}  cover={cover}  preview={preview}")

    # Читаем dest
    print(f"\n{CYAN}── Dest Library ({cfg.DESTINATION.upper()}) ──{RESET}")
    dest_items = await syncer.get_items(cfg.DESTINATION)
    print(f"  Найдено: {len(dest_items)} {cfg.SYNC_TYPE}")

    # Тест поиска
    print(f"\n{CYAN}── Search Test (первые {cfg.LIMIT}) ──{RESET}")
    for item in source_items[:cfg.LIMIT]:
        artist = item.get('artist', item.get('name', ''))
        name   = item.get('name', '')
        query  = f"{artist} {name}".strip()
        match  = await syncer.search_item(cfg.DESTINATION, query)
        if match:
            print(f"  {GREEN}✓{RESET} {query[:45]:<45} → {match['name'][:30]}")
        else:
            print(f"  {RED}✗{RESET} {query[:45]:<45} → NOT FOUND")

    if not cfg.DRY_RUN:
        print(f"\n{CYAN}── Full Sync ──{RESET}")
        await syncer.run(cfg.SOURCE, cfg.DESTINATION, sse_print)
    else:
        print(f"\n{YELLOW}DRY_RUN=True — добавление пропущено.{RESET}")
        print(f"Установи DRY_RUN=False в test_config.py для реального sync.\n")

asyncio.run(main())
