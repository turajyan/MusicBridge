# MusicBridge 🎵

Cross-platform music library sync — Tidal ↔ Spotify.

## Stack

- **Backend + Frontend**: FastAPI (Python)
- **Tidal**: tidalapi (PKCE auth)
- **Spotify**: spotipy (OAuth2)
- **Streaming**: Server-Sent Events (SSE)

## Setup

```bash
cd backend
python -m venv venv

# Windows
venv\Scripts\activate

# macOS/Linux
source venv/bin/activate

pip install -r requirements.txt
```

## Run

```bash
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

- **UI**: http://localhost:8000
- **API docs**: http://localhost:8000/docs

## Tidal Auth

First time:
1. `GET /auth/tidal` → получаешь PKCE URL
2. Открываешь в браузере, логинишься
3. Копируешь URL страницы "Oops"
4. `POST /auth/tidal/callback` → вставляешь Oops URL
5. Сессия сохраняется в `tidal_session.json` — следующий запуск без авторизации

## Spotify Auth

Автоматически через браузер при первом запросе.

## API

### POST `/api/v1/sync/start`
```json
{
  "source": "tidal",
  "destination": "spotify",
  "type": "tracks",
  "strategy": "skip"
}
```

Типы: `tracks`, `artists`, `albums`
Стратегии: `skip` (пропускать существующие), `replace`

### Auth endpoints
| Method | Path | Description |
|--------|------|-------------|
| GET | `/auth/tidal` | Получить PKCE URL |
| POST | `/auth/tidal/callback` | Завершить авторизацию |
| GET | `/auth/tidal/status` | Проверить статус |
| DELETE | `/auth/tidal` | Выйти |

## Sync Algorithm

```
For each track:
  1. ISRC match in dest? → SKIP
  2. Name match in dest? → SKIP  
  3. Search by "Artist + Title" → ADD
```
