import aiohttp
from aioresponses import aioresponses

from prefetch.mediaserver import jellyfin_emby
from prefetch.mediaserver.base import Series


async def test_extract_session_with_tvdb_and_library():
    with aioresponses() as m:
        m.get(
            "http://jf/Sessions",
            payload=[
                {
                    "Id": "sess-1",
                    "UserId": "u1",
                    "UserName": "user",
                    "NowPlayingItem": {
                        "SeriesId": "a",
                        "SeasonId": "b",
                        "IndexNumber": 5,
                        "Path": "/media/tv/show/s01e05.mkv",
                    },
                }
            ],
        )
        m.get("http://jf/Users/u1/Items/b", payload={"IndexNumber": 3})
        m.get("http://jf/Users/u1/Items/a", payload={"Name": "Test Show", "ProviderIds": {"Tvdb": "1234"}})
        m.get(
            "http://jf/Library/VirtualFolders",
            payload=[{"Name": "TV Shows", "Locations": ["/media/tv"]}],
        )

        async with aiohttp.ClientSession() as session:
            client = jellyfin_emby.Client("http://jf", "secret", jellyfin_emby.JELLYFIN, session)
            sessions = await client.sessions()
            assert len(sessions) == 1
            np = await client.extract(sessions[0])

    assert np.series == Series.tvdb(1234)
    assert np.episode == 5
    assert np.season == 3
    assert np.library == "TV Shows"
    assert np.session_id == "sess-1"


async def test_malformed_sessions_are_skipped():
    with aioresponses() as m:
        m.get(
            "http://jf/Sessions",
            payload=[
                {"invalid": "session"},
                {
                    "UserId": "u1",
                    "UserName": "user",
                    "NowPlayingItem": {
                        "SeriesId": "a",
                        "SeasonId": "b",
                        "IndexNumber": 5,
                        "Path": "/x",
                    },
                },
            ],
        )

        async with aiohttp.ClientSession() as session:
            client = jellyfin_emby.Client("http://jf", "secret", jellyfin_emby.JELLYFIN, session)
            sessions = await client.sessions()

    assert len(sessions) == 1
