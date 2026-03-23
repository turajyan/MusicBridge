import asyncio
import tidalapi
import cancel


def _run_sync(loop, fn, *args):
    """Запускает блокирующую функцию в executor, не блокируя event loop."""
    return loop.run_in_executor(None, fn, *args)


class BaseSyncer:
    def __init__(self, sp_client, td_session, strategy):
        self.sp   = sp_client
        self.td   = td_session
        self.strategy = strategy  # 'skip' или 'replace'
        self.loop = asyncio.get_event_loop()

    async def get_items(self, platform):
        raise NotImplementedError

    async def search_item(self, platform, query):
        raise NotImplementedError

    async def add_item(self, platform, item_id):
        raise NotImplementedError


class ArtistSyncer(BaseSyncer):

    async def get_items(self, platform):
        items = []
        if platform == 'spotify':
            def _fetch():
                results = self.sp.current_user_followed_artists(limit=50)
                out = []
                for art in results['artists']['items']:
                    cover = art['images'][0]['url'] if art['images'] else ''
                    out.append({'id': art['id'], 'name': art['name'], 'cover': cover})
                return out
            items = await self.loop.run_in_executor(None, _fetch)

        elif platform == 'tidal':
            def _fetch():
                out = []
                for art in self.td.user.favorites.artists():
                    try:
                        cover = art.image(320)
                    except Exception:
                        cover = ''
                    out.append({'id': art.id, 'name': art.name, 'cover': cover})
                return out
            items = await self.loop.run_in_executor(None, _fetch)
        return items

    async def search_item(self, platform, query):
        if platform == 'spotify':
            def _search():
                res = self.sp.search(q=query, type='artist', limit=1)
                if res['artists']['items']:
                    art = res['artists']['items'][0]
                    cover = art['images'][0]['url'] if art['images'] else ''
                    return {'id': art['id'], 'name': art['name'], 'cover': cover}
                return None
            return await self.loop.run_in_executor(None, _search)

        elif platform == 'tidal':
            def _search():
                res = self.td.search(query, models=[tidalapi.Artist])
                if res.get('artists'):
                    art = res['artists'][0]
                    try:
                        cover = art.image(320)
                    except Exception:
                        cover = ''
                    return {'id': art.id, 'name': art.name, 'cover': cover}
                return None
            return await self.loop.run_in_executor(None, _search)
        return None

    async def add_item(self, platform, item_id):
        try:
            if platform == 'spotify':
                await self.loop.run_in_executor(None, lambda: self.sp.user_follow_artists(ids=[item_id]))
            elif platform == 'tidal':
                await self.loop.run_in_executor(None, lambda: self.td.user.favorites.add_artist(item_id))
            return True, None
        except Exception as e:
            return False, str(e)

    async def run(self, source, dest, sse_yield):
        await sse_yield(f"Fetching artists from {source.upper()}...", "info")
        source_items = await self.get_items(source)
        await sse_yield(f"Found {len(source_items)} artists.", "success")

        await sse_yield(f"Fetching existing artists from {dest.upper()}...", "info")
        dest_items = await self.get_items(dest)
        dest_names = {item['name'].lower() for item in dest_items}

        for item in source_items:
            if cancel.is_cancelled():
                await sse_yield("Sync cancelled by user.", "error")
                return
            await asyncio.sleep(0.5)

            if self.strategy == 'skip' and item['name'].lower() in dest_names:
                await sse_yield(f"SKIPPED: {item['name']} (Already followed)", "log-info")
                continue

            match = await self.search_item(dest, item['name'])
            if not match:
                await sse_yield(f"NOT FOUND: {item['name']}", "error")
                continue

            await sse_yield({
                "action": "visualize",
                "data": {
                    "source": {"title": item['name'],  "artist": item['name'],  "cover": item['cover']},
                    "dest":   {"title": match['name'], "artist": match['name'], "cover": match['cover']}
                }
            }, "visualize")

            success, err = await self.add_item(dest, match['id'])
            if success:
                await sse_yield(f"FOLLOWED: {match['name']}", "success")
            else:
                await sse_yield(f"FAILED: {match['name']} ({err})", "error")


class TrackSyncer(BaseSyncer):

    async def get_items(self, platform):
        if platform == 'spotify':
            def _fetch():
                results = self.sp.current_user_saved_tracks(limit=50)
                out = []
                for item in results['items']:
                    t = item['track']
                    images = t['album'].get('images', [])
                    cover = images[1]['url'] if len(images) > 1 else (images[0]['url'] if images else '')
                    out.append({
                        'id':          t['id'],
                        'name':        t['name'],
                        'artist':      t['artists'][0]['name'],
                        'isrc':        t['external_ids'].get('isrc'),
                        'cover':       cover,
                        'preview_url': t.get('preview_url'),
                    })
                return out
            return await self.loop.run_in_executor(None, _fetch)

        elif platform == 'tidal':
            def _fetch():
                out = []
                for t in self.td.user.favorites.tracks()[:50]:
                    try:
                        cover = t.album.image(320)
                    except Exception:
                        cover = ''
                    out.append({
                        'id':          t.id,
                        'name':        t.name,
                        'artist':      t.artist.name,
                        'isrc':        t.isrc,
                        'cover':       cover,
                        'preview_url': None,
                    })
                return out
            return await self.loop.run_in_executor(None, _fetch)
        return []

    async def search_item(self, platform, query):
        if platform == 'spotify':
            def _search():
                res = self.sp.search(q=query, type='track', limit=1)
                if res['tracks']['items']:
                    t = res['tracks']['items'][0]
                    images = t['album'].get('images', [])
                    cover = images[1]['url'] if len(images) > 1 else (images[0]['url'] if images else '')
                    return {'id': t['id'], 'name': t['name'], 'artist': t['artists'][0]['name'], 'cover': cover}
                return None
            return await self.loop.run_in_executor(None, _search)

        elif platform == 'tidal':
            def _search():
                res = self.td.search(query, models=[tidalapi.Track])
                if res.get('tracks'):
                    t = res['tracks'][0]
                    try:
                        cover = t.album.image(320)
                    except Exception:
                        cover = ''
                    return {'id': t.id, 'name': t.name, 'artist': t.artist.name, 'cover': cover}
                return None
            return await self.loop.run_in_executor(None, _search)
        return None

    async def add_item(self, platform, item_id):
        try:
            if platform == 'spotify':
                await self.loop.run_in_executor(None, lambda: self.sp.current_user_saved_tracks_add([item_id]))
            elif platform == 'tidal':
                await self.loop.run_in_executor(None, lambda: self.td.user.favorites.add_track(item_id))
            return True, None
        except Exception as e:
            return False, str(e)

    async def run(self, source, dest, sse_yield):
        await sse_yield(f"Fetching library from {source.upper()}...", "info")
        source_items = await self.get_items(source)
        await sse_yield(f"Found {len(source_items)} tracks.", "success")

        await sse_yield(f"Fetching existing library from {dest.upper()}...", "info")
        dest_items = await self.get_items(dest)
        dest_isrcs = {item['isrc'] for item in dest_items if item['isrc']}
        dest_names = {f"{item['artist'].lower()} {item['name'].lower()}" for item in dest_items}

        for item in source_items:
            if cancel.is_cancelled():
                await sse_yield("Sync cancelled by user.", "error")
                return
            await asyncio.sleep(0.5)

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

            await sse_yield({
                "action": "visualize",
                "data": {
                    "source": {"title": item['name'],  "artist": item['artist'],  "cover": item['cover']},
                    "dest":   {"title": match['name'], "artist": match['artist'], "cover": match['cover']}
                }
            }, "visualize")

            success, err = await self.add_item(dest, match['id'])
            if success:
                await sse_yield(f"ADDED: {item['artist']} - {item['name']}", "success")
            else:
                await sse_yield(f"FAILED: {item['artist']} - {item['name']} ({err})", "error")


class AlbumSyncer(BaseSyncer):

    async def get_items(self, platform):
        if platform == 'spotify':
            def _fetch():
                results = self.sp.current_user_saved_albums(limit=50)
                out = []
                for item in results['items']:
                    a = item['album']
                    images = a.get('images', [])
                    cover = images[1]['url'] if len(images) > 1 else (images[0]['url'] if images else '')
                    out.append({'id': a['id'], 'name': a['name'], 'artist': a['artists'][0]['name'], 'cover': cover})
                return out
            return await self.loop.run_in_executor(None, _fetch)

        elif platform == 'tidal':
            def _fetch():
                out = []
                for a in self.td.user.favorites.albums()[:50]:
                    try:
                        cover = a.image(320)
                    except Exception:
                        cover = ''
                    out.append({'id': a.id, 'name': a.name, 'artist': a.artist.name, 'cover': cover})
                return out
            return await self.loop.run_in_executor(None, _fetch)
        return []

    async def search_item(self, platform, query):
        if platform == 'spotify':
            def _search():
                res = self.sp.search(q=query, type='album', limit=1)
                if res['albums']['items']:
                    a = res['albums']['items'][0]
                    images = a.get('images', [])
                    cover = images[1]['url'] if len(images) > 1 else (images[0]['url'] if images else '')
                    return {'id': a['id'], 'name': a['name'], 'artist': a['artists'][0]['name'], 'cover': cover}
                return None
            return await self.loop.run_in_executor(None, _search)

        elif platform == 'tidal':
            def _search():
                res = self.td.search(query, models=[tidalapi.Album])
                if res.get('albums'):
                    a = res['albums'][0]
                    try:
                        cover = a.image(320)
                    except Exception:
                        cover = ''
                    return {'id': a.id, 'name': a.name, 'artist': a.artist.name, 'cover': cover}
                return None
            return await self.loop.run_in_executor(None, _search)
        return None

    async def add_item(self, platform, item_id):
        try:
            if platform == 'spotify':
                await self.loop.run_in_executor(None, lambda: self.sp.current_user_saved_albums_add([item_id]))
            elif platform == 'tidal':
                await self.loop.run_in_executor(None, lambda: self.td.user.favorites.add_album(item_id))
            return True, None
        except Exception as e:
            return False, str(e)

    async def run(self, source, dest, sse_yield):
        await sse_yield(f"Fetching albums from {source.upper()}...", "info")
        source_items = await self.get_items(source)
        await sse_yield(f"Found {len(source_items)} albums.", "success")

        await sse_yield(f"Fetching existing albums from {dest.upper()}...", "info")
        dest_items = await self.get_items(dest)
        dest_names = {f"{item['artist'].lower()} {item['name'].lower()}" for item in dest_items}

        for item in source_items:
            if cancel.is_cancelled():
                await sse_yield("Sync cancelled by user.", "error")
                return
            await asyncio.sleep(0.5)

            if self.strategy == 'skip':
                if f"{item['artist'].lower()} {item['name'].lower()}" in dest_names:
                    await sse_yield(f"SKIPPED: {item['artist']} - {item['name']} (Already saved)", "log-info")
                    continue

            match = await self.search_item(dest, f"{item['artist']} {item['name']}")
            if not match:
                await sse_yield(f"NOT FOUND: {item['artist']} - {item['name']}", "error")
                continue

            await sse_yield({
                "action": "visualize",
                "data": {
                    "source": {"title": item['name'],  "artist": item['artist'],  "cover": item['cover']},
                    "dest":   {"title": match['name'], "artist": match['artist'], "cover": match['cover']}
                }
            }, "visualize")

            success, err = await self.add_item(dest, match['id'])
            if success:
                await sse_yield(f"SAVED: {item['artist']} - {item['name']}", "success")
            else:
                await sse_yield(f"FAILED: {item['artist']} - {item['name']} ({err})", "error")
