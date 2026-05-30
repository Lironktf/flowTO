"""GTFS fetch + tagging for TTC / GO / UP (research/01 §, research/02).

Static GTFS needs no API key. TTC ships via CKAN; GO Transit and UP Express
ship from Metrolinx Open Data (separate URLs). We cache the zips with a fetch
date and tag each with ``agency``/``mode`` so P08 can build trajectories.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

# Mode follows GTFS route_type families; tagged at the feed level for the overlay.
TTC_PACKAGE = "ttc-routes-and-schedules"  # CKAN; resolve the GTFS zip by format.


@dataclass(frozen=True)
class GtfsFeed:
    key: str
    agency: str
    mode: str  # "subway"|"streetcar"|"bus"|"rail"|"air-rail" (display grouping)
    url: str | None  # direct zip URL (Metrolinx); None => resolve via CKAN
    ckan_package: str | None = None


FEEDS: dict[str, GtfsFeed] = {
    "ttc": GtfsFeed(
        key="ttc",
        agency="Toronto Transit Commission",
        mode="bus+streetcar+subway",
        url=None,
        ckan_package=TTC_PACKAGE,
    ),
    "go": GtfsFeed(
        key="go",
        agency="GO Transit (Metrolinx)",
        mode="rail",
        url="https://www.metrolinx.com/en/openData/files-gtfs-go/GO_GTFS.zip",
    ),
    "up": GtfsFeed(
        key="up",
        agency="UP Express (Metrolinx)",
        mode="air-rail",
        url="https://www.metrolinx.com/en/openData/files-gtfs-up/UP_GTFS.zip",
    ),
}


def feed_url(feed: GtfsFeed, *, get_json=None) -> str:
    """Resolve a feed's zip URL (direct, or via CKAN for TTC)."""
    if feed.url:
        return feed.url
    if feed.ckan_package:
        from . import ckan

        kwargs = {"get_json": get_json} if get_json is not None else {}
        res = ckan.resolve_resource(feed.ckan_package, "zip", **kwargs)
        return res["url"]
    raise ValueError(f"feed {feed.key} has no URL or CKAN package")


def fetch_feed(key: str, dest_dir: str, *, date_tag: str, session=None) -> dict:
    """Download one feed's zip into ``dest_dir`` and return tagged metadata.

    ``date_tag`` (e.g. "2026-05-30") is supplied by the caller so this stays
    deterministic / wall-clock-free.
    """
    from . import ckan

    feed = FEEDS[key]
    url = feed_url(feed)
    fn = f"gtfs_{feed.key}_{date_tag}.zip"
    dest = os.path.join(dest_dir, fn)
    ckan.download_file(url, dest, session=session)
    return {
        "key": feed.key,
        "agency": feed.agency,
        "mode": feed.mode,
        "url": url,
        "path": dest,
        "date_tag": date_tag,
    }


def list_feeds() -> list[str]:
    return list(FEEDS)
