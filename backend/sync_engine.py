import asyncio

class BaseSyncer:
    def __init__(self, sp_client, td_session, strategy):
        self.sp = sp_client
        self.td = td_session
        self.strategy = strategy # 'skip' или 'replace'

    async def run(self, source, dest, sse_yield):
        """Главный цикл синхронизации"""
        await sse_yield(f"Fetching library from {source.upper()}...", "info")
        source_items = await self.get_items(source)
        await sse_yield(f"Found {len(source_items)} items.", "success")

        await sse_yield(f"Fetching existing library from {dest.upper()}...", "info")
        dest_items = await self.get_items(dest)
        dest_names = {item['name'].lower() for item in dest_items}

        for item in source_items:
            await asyncio.sleep(0.5) # Защита от Rate Limit

            # Логика пропуска (Skip)
            if self.strategy == 'skip' and item['name'].lower() in dest_names:
                await sse_yield(f"SKIPPED: {item['name']} (Already followed)", "log-info")
                continue

            # Поиск на платформе назначения
            match = await self.search_item(dest, item['name'])

            if not match:
                await sse_yield(f"NOT FOUND: {item['name']}", "error")
                continue

            # Отправляем данные для визуализации на фронтенд (картинки!)
            visual_payload = {
                "action": "visualize",
                "data": {
                    "source": {"title": item['name'], "artist": "Artist", "cover": item['cover']},
                    "dest": {"title": match['name'], "artist": "Match Found", "cover": match['cover']}
                }
            }
            await sse_yield(visual_payload, "visualize")

            # Выполняем подписку
            success = await self.add_item(dest, match['id'])
            if success:
                await sse_yield(f"FOLLOWED: {match['name']}", "success")
            else:
                await sse_yield(f"FAILED to follow: {match['name']}", "error")


class ArtistSyncer(BaseSyncer):

    async def get_items(self, platform):
        """Получает список подписок с картинками"""
        items = []
        if platform == 'spotify':
            results = self.sp.current_user_followed_artists(limit=50)
            for art in results['artists']['items']:
                cover = art['images'][0]['url'] if art['images'] else ''
                items.append({'id': art['id'], 'name': art['name'], 'cover': cover})

        elif platform == 'tidal':
            results = self.td.user.favorites.artists()
            for art in results:
                cover = art.image(320) if hasattr(art, 'image') else ''
                items.append({'id': art.id, 'name': art.name, 'cover': cover})
        return items

    async def search_item(self, platform, query):
        """Ищет артиста по имени и возвращает лучший результат"""
        if platform == 'spotify':
            res = self.sp.search(q=query, type='artist', limit=1)
            if res['artists']['items']:
                art = res['artists']['items'][0]
                cover = art['images'][0]['url'] if art['images'] else ''
                return {'id': art['id'], 'name': art['name'], 'cover': cover}

        elif platform == 'tidal':
            res = self.td.search("artist", query)
            if res['artists']:
                art = res['artists'][0]
                cover = art.image(320) if hasattr(art, 'image') else ''
                return {'id': art.id, 'name': art.name, 'cover': cover}
        return None

    async def add_item(self, platform, item_id):
        """Оформляет подписку на артиста"""
        try:
            if platform == 'spotify':
                self.sp.user_follow_artists(ids=[item_id])
            elif platform == 'tidal':
                self.td.user.favorites.add_artist(item_id)
            return True
        except Exception:
            return False


class TrackSyncer(BaseSyncer):

    async def get_items(self, platform):
        """Получает треки с обложками и ISRC"""
        items = []
        if platform == 'spotify':
            results = self.sp.current_user_saved_tracks(limit=50)
            for item in results['items']:
                t = item['track']
                images = t['album'].get('images', [])
                cover = images[1]['url'] if len(images) > 1 else (images[0]['url'] if images else '')
                items.append({
                    'id':          t['id'],
                    'name':        t['name'],
                    'artist':      t['artists'][0]['name'],
                    'isrc':        t['external_ids'].get('isrc'),
                    'cover':       cover,
                    'preview_url': t.get('preview_url'),
                })

        elif platform == 'tidal':
            for t in self.td.user.favorites.tracks()[:50]:
                try:
                    cover = t.album.image(320)
                except Exception:
                    cover = ''
                items.append({
                    'id':          t.id,
                    'name':        t.name,
                    'artist':      t.artist.name,
                    'isrc':        t.isrc,
                    'cover':       cover,
                    'preview_url': None,
                })
        return items

    async def run(self, source, dest, sse_yield):
        """Цикл синхронизации треков с ISRC-дедупликацией"""
        await sse_yield(f"Fetching library from {source.upper()}...", "info")
        source_items = await self.get_items(source)
        await sse_yield(f"Found {len(source_items)} tracks.", "success")

        await sse_yield(f"Fetching existing library from {dest.upper()}...", "info")
        dest_items = await self.get_items(dest)
        # ISRC как primary key, fallback на "artist - name"
        dest_isrcs = {item['isrc'] for item in dest_items if item['isrc']}
        dest_names = {f"{item['artist'].lower()} {item['name'].lower()}" for item in dest_items}

        for item in source_items:
            await asyncio.sleep(0.5)

            # Дедупликация по ISRC (100% точность)
            if self.strategy == 'skip':
                if item['isrc'] and item['isrc'] in dest_isrcs:
                    await sse_yield(f"SKIPPED: {item['artist']} - {item['name']} (ISRC match)", "log-info")
                    continue
                if f"{item['artist'].lower()} {item['name'].lower()}" in dest_names:
                    await sse_yield(f"SKIPPED: {item['artist']} - {item['name']} (name match)", "log-info")
                    continue

            match = await self.search_item(dest, f"{item['artist']} {item['name']}")

            if not match:
                await sse_yield(f"NOT FOUND: {item['artist']} - {item['name']}", "error")
                continue

            visual_payload = {
                "action": "visualize",
                "data": {
                    "source": {"title": item['name'], "artist": item['artist'], "cover": item['cover']},
                    "dest":   {"title": match['name'], "artist": match['artist'], "cover": match['cover']}
                }
            }
            await sse_yield(visual_payload, "visualize")

            success = await self.add_item(dest, match['id'])
            if success:
                await sse_yield(f"ADDED: {item['artist']} - {item['name']}", "success")
            else:
                await sse_yield(f"FAILED: {item['artist']} - {item['name']}", "error")

    async def search_item(self, platform, query):
        if platform == 'spotify':
            res = self.sp.search(q=query, type='track', limit=1)
            if res['tracks']['items']:
                t = res['tracks']['items'][0]
                images = t['album'].get('images', [])
                cover = images[1]['url'] if len(images) > 1 else (images[0]['url'] if images else '')
                return {'id': t['id'], 'name': t['name'], 'artist': t['artists'][0]['name'], 'cover': cover}

        elif platform == 'tidal':
            res = self.td.search("track", query)
            if res['tracks']:
                t = res['tracks'][0]
                try:
                    cover = t.album.image(320)
                except Exception:
                    cover = ''
                return {'id': t.id, 'name': t.name, 'artist': t.artist.name, 'cover': cover}
        return None

    async def add_item(self, platform, item_id):
        try:
            if platform == 'spotify':
                self.sp.current_user_saved_tracks_add([item_id])
            elif platform == 'tidal':
                self.td.user.favorites.add_track(item_id)
            return True
        except Exception:
            return False


class AlbumSyncer(BaseSyncer):

    async def get_items(self, platform):
        """Получает сохранённые альбомы с обложками"""
        items = []
        if platform == 'spotify':
            results = self.sp.current_user_saved_albums(limit=50)
            for item in results['items']:
                a = item['album']
                images = a.get('images', [])
                cover = images[1]['url'] if len(images) > 1 else (images[0]['url'] if images else '')
                items.append({
                    'id':     a['id'],
                    'name':   a['name'],
                    'artist': a['artists'][0]['name'],
                    'cover':  cover,
                })

        elif platform == 'tidal':
            for a in self.td.user.favorites.albums()[:50]:
                try:
                    cover = a.image(320)
                except Exception:
                    cover = ''
                items.append({
                    'id':     a.id,
                    'name':   a.name,
                    'artist': a.artist.name,
                    'cover':  cover,
                })
        return items

    async def search_item(self, platform, query):
        if platform == 'spotify':
            res = self.sp.search(q=query, type='album', limit=1)
            if res['albums']['items']:
                a = res['albums']['items'][0]
                images = a.get('images', [])
                cover = images[1]['url'] if len(images) > 1 else (images[0]['url'] if images else '')
                return {'id': a['id'], 'name': a['name'], 'artist': a['artists'][0]['name'], 'cover': cover}

        elif platform == 'tidal':
            res = self.td.search("album", query)
            if res['albums']:
                a = res['albums'][0]
                try:
                    cover = a.image(320)
                except Exception:
                    cover = ''
                return {'id': a.id, 'name': a.name, 'artist': a.artist.name, 'cover': cover}
        return None

    async def add_item(self, platform, item_id):
        try:
            if platform == 'spotify':
                self.sp.current_user_saved_albums_add([item_id])
            elif platform == 'tidal':
                self.td.user.favorites.add_album(item_id)
            return True
        except Exception:
            return False

    async def run(self, source, dest, sse_yield):
        await sse_yield(f"Fetching albums from {source.upper()}...", "info")
        source_items = await self.get_items(source)
        await sse_yield(f"Found {len(source_items)} albums.", "success")

        await sse_yield(f"Fetching existing albums from {dest.upper()}...", "info")
        dest_items = await self.get_items(dest)
        dest_names = {f"{item['artist'].lower()} {item['name'].lower()}" for item in dest_items}

        for item in source_items:
            await asyncio.sleep(0.5)

            if self.strategy == 'skip':
                key = f"{item['artist'].lower()} {item['name'].lower()}"
                if key in dest_names:
                    await sse_yield(f"SKIPPED: {item['artist']} - {item['name']} (Already saved)", "log-info")
                    continue

            query = f"{item['artist']} {item['name']}"
            match = await self.search_item(dest, query)

            if not match:
                await sse_yield(f"NOT FOUND: {item['artist']} - {item['name']}", "error")
                continue

            visual_payload = {
                "action": "visualize",
                "data": {
                    "source": {"title": item['name'],  "artist": item['artist'],  "cover": item['cover']},
                    "dest":   {"title": match['name'], "artist": match['artist'], "cover": match['cover']}
                }
            }
            await sse_yield(visual_payload, "visualize")

            success = await self.add_item(dest, match['id'])
            if success:
                await sse_yield(f"SAVED: {item['artist']} - {item['name']}", "success")
            else:
                await sse_yield(f"FAILED: {item['artist']} - {item['name']}", "error")
