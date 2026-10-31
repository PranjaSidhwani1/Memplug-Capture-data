"""Report how many conversations are stored. Hooks write them directly."""

from memplug_capture.store import counts


def drain() -> dict[str, int]:
    return counts()
