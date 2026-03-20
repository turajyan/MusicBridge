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
