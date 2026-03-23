# Скопируй этот файл в test_config.py и заполни своими данными:
# cp test_config.example.py test_config.py

SPOTIFY_CLIENT_ID     = "ВАШ_CLIENT_ID"
SPOTIFY_CLIENT_SECRET = "ВАШ_CLIENT_SECRET"
SPOTIFY_REDIRECT_URI  = "http://127.0.0.1:8080"

SOURCE      = "tidal"
DESTINATION = "spotify"
SYNC_TYPE   = "tracks"
STRATEGY    = "skip"
DRY_RUN     = True
LIMIT       = 5
