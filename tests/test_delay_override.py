from datetime import timedelta

from unmonitor.radarr_job import _get_delay_override as radarr_delay_override
from unmonitor.sonarr_job import _get_delay_override as sonarr_delay_override


def id_to_label(labels):
    return {i + 1: label for i, label in enumerate(labels)}


def test_single_match_returns_timedelta():
    labels = id_to_label(["delayby_120"])
    assert sonarr_delay_override([1], labels, "Test") == timedelta(minutes=120)
    assert radarr_delay_override([1], labels, "Test") == timedelta(minutes=120)


def test_negative_value():
    labels = id_to_label(["delayby_-60"])
    assert sonarr_delay_override([1], labels, "Test") == timedelta(minutes=-60)


def test_no_match_returns_none():
    labels = id_to_label(["auto-unmonitored", "ignore"])
    assert sonarr_delay_override([1, 2], labels, "Test") is None


def test_empty_tags_returns_none():
    assert radarr_delay_override([], {}, "Test") is None


def test_multiple_matches_returns_none(caplog):
    labels = id_to_label(["delayby_60", "delayby_120"])
    assert sonarr_delay_override([1, 2], labels, "Test") is None


def test_case_insensitive():
    labels = id_to_label(["DELAYBY_90"])
    assert sonarr_delay_override([1], labels, "Test") == timedelta(minutes=90)


def test_non_numeric_ignored():
    labels = id_to_label(["delayby_abc"])
    assert sonarr_delay_override([1], labels, "Test") is None


def test_zero_delay():
    labels = id_to_label(["delayby_0"])
    assert sonarr_delay_override([1], labels, "Test") == timedelta(minutes=0)
