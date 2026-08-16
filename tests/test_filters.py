from prefetch.mediaserver.base import NowPlaying, Series, User, libraries_filter, users_filter


def np(**kw):
    base = dict(
        series=Series.tvdb(0),
        episode=0,
        season=0,
        user=User(name="", id=""),
        library=None,
        session_id=None,
    )
    base.update(kw)
    return NowPlaying(**base)


def test_users_unrestricted():
    assert users_filter([])(np()) is True


def test_users_accepted_by_name():
    f = users_filter(["Other", "User"])
    assert f(np(user=User(id="1", name="User"))) is True


def test_users_accepted_by_id():
    f = users_filter(["1", "2"])
    assert f(np(user=User(id="1", name="User"))) is True


def test_users_rejected():
    f = users_filter(["Nope"])
    assert f(np()) is False


def test_libraries_unrestricted():
    assert libraries_filter([])(np()) is True


def test_libraries_accepted():
    f = libraries_filter(["Movies", "TV"])
    assert f(np(library="TV")) is True


def test_libraries_unknown_rejected():
    f = libraries_filter(["Nope"])
    assert f(np(library=None)) is False


def test_libraries_rejected():
    f = libraries_filter(["TV"])
    assert f(np(library="Movies")) is False
