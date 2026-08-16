"""In-memory fake Sonarr backend for prefetch actor tests. Implements the
same method surface as `sonarr.client.Client` (duck-typed -- Actor only
calls methods, never isinstance-checks) plus the same
PUT-series-propagates-season-monitored-flip behavior real Sonarr has, since
several prefetch behaviors depend on it.
"""

import copy

from sonarr.client import episode_can_prefetch, find_season


def make_series(id, title, tvdb_id, seasons):
    return {
        "id": id,
        "title": title,
        "tvdbId": tvdb_id,
        "monitored": False,
        "monitorNewItems": "all",
        "seasons": [copy.deepcopy(s) for s in seasons],
    }


def make_season(number, monitored, fully_aired):
    return {
        "seasonNumber": number,
        "monitored": monitored,
        "statistics": {
            "sizeOnDisk": 9000,
            "episodeCount": 8,
            "episodeFileCount": 8,
            "totalEpisodeCount": 8,
            "nextAiring": None if fully_aired else "2025-06-01T00:00:00Z",
        },
    }


def make_episode(id, series_id, season, episode, has_file):
    return make_episode_with_airdate(id, series_id, season, episode, has_file, None)


def make_episode_with_airdate(id, series_id, season, episode, has_file, air_date):
    e = {
        "id": id,
        "seriesId": series_id,
        "seasonNumber": season,
        "episodeNumber": episode,
        "hasFile": has_file,
        "monitored": False,
    }
    if air_date is not None:
        e["airDate"] = air_date
    return e


class FakeSonarr:
    def __init__(self):
        self.series_list: dict = {}
        self.episodes: dict = {}
        self.tags: list = []
        self.commands: list = []

    def add_series(self, series):
        self.series_list[series["id"]] = copy.deepcopy(series)

    def add_episodes(self, episodes):
        for e in episodes:
            self.episodes[e["id"]] = copy.deepcopy(e)

    def add_tag(self, id, label):
        self.tags.append({"id": id, "label": label})

    def series_state(self, id):
        return self.series_list.get(id)

    def episode(self, id):
        return self.episodes.get(id)

    async def probe(self):
        return None

    async def series(self):
        return [copy.deepcopy(s) for s in self.series_list.values()]

    async def put_series(self, series):
        sid = series["id"]
        old = self.series_list.get(sid)
        newly_monitored_seasons = []
        if old is not None:
            old_by_num = {s["seasonNumber"]: s for s in old.get("seasons", [])}
            for new_season in series.get("seasons", []):
                if not new_season.get("monitored"):
                    continue
                sn = new_season["seasonNumber"]
                was_monitored = old_by_num.get(sn, {}).get("monitored", False)
                if not was_monitored:
                    newly_monitored_seasons.append(sn)

        for sn in newly_monitored_seasons:
            for e in self.episodes.values():
                if e["seriesId"] == sid and e["seasonNumber"] == sn:
                    e["monitored"] = True

        self.series_list[sid] = copy.deepcopy(series)
        return {}

    async def resolve_tag(self, label):
        for t in self.tags:
            if t["label"] == label:
                return t["id"]
        return None

    async def update_tag(self, tag):
        if tag.get("id") is not None:
            return
        resolved = await self.resolve_tag(tag["label"])
        if resolved is not None:
            tag["id"] = resolved

    async def episodes_of(self, series_id, season_number=None):
        out = [
            copy.deepcopy(e)
            for e in self.episodes.values()
            if e["seriesId"] == series_id and (season_number is None or e["seasonNumber"] == season_number)
        ]
        return out

    async def episodes_season(self, series_id, season_number):
        return await self.episodes_of(series_id, season_number)

    async def episode_range(self, series, season_start, episode_start, num):
        from sonarr.client import episode_window

        episodes = await self.episodes_of(series["id"])
        return episode_window(season_start, episode_start, num, episodes)

    async def _set_monitored_episodes(self, episode_ids, monitored):
        for eid in episode_ids:
            if eid in self.episodes:
                self.episodes[eid]["monitored"] = monitored

    async def update_episode_monitoring(self, episodes):
        monitored_ids = [e["id"] for e in episodes if e.get("monitored")]
        unmonitored_ids = [e["id"] for e in episodes if not e.get("monitored")]
        await self._set_monitored_episodes(monitored_ids, True)
        await self._set_monitored_episodes(unmonitored_ids, False)

    async def monitor_unannounced_episodes(self, series, check_aired):
        series["monitored"] = True
        series["monitorNewItems"] = "all"

        seasons = series.get("seasons", [])
        if not seasons:
            await self.put_series(series)
            return

        last_season = seasons[-1]
        last_season["monitored"] = True

        original_episodes = await self.episodes_of(series["id"], last_season["seasonNumber"])
        for e in original_episodes:
            e["monitored"] = episode_can_prefetch(e, check_aired) if check_aired else True

        await self.put_series(series)
        await self.update_episode_monitoring(original_episodes)

    async def search_episodes(self, episodes):
        episode_ids = [e["id"] for e in episodes]
        self.commands.append({"name": "EpisodeSearch", "episodeIds": episode_ids})
        return {}

    async def search_season(self, series, season_num, check_aired):
        season = find_season(series, season_num)
        if season is None:
            raise ValueError(f"there is no season {season_num}")

        if season["monitored"]:
            season_episodes = await self.episodes_of(series["id"], season_num)
            for e in season_episodes:
                if not check_aired or episode_can_prefetch(e, True):
                    e["monitored"] = True
            await self.update_episode_monitoring(season_episodes)
        else:
            season["monitored"] = True
            await self.put_series(series)

        # Mirror real Sonarr: SeasonSearch requires the series and every
        # episode in the season to already be monitored.
        stored_series = self.series_list[series["id"]]
        assert stored_series.get("monitored") is True, "SeasonSearch requires the series to be monitored"
        unmonitored = [
            e["episodeNumber"]
            for e in self.episodes.values()
            if e["seriesId"] == series["id"] and e["seasonNumber"] == season_num and not e.get("monitored")
        ]
        assert not unmonitored, f"SeasonSearch for season {season_num} would be rejected: {unmonitored} not monitored"

        cmd = {"name": "SeasonSearch", "seriesId": series["id"], "seasonNumber": season_num}
        self.commands.append(cmd)
        return {}
