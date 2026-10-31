"""Fetch stats from the deployed Capture API."""

from memplug_capture.stats_client import fetch_stats


def drain() -> dict:
    return fetch_stats()
