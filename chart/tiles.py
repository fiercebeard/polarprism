import asyncio
import contextlib
import logging
import math
import os
import time
import urllib.request

import pygame

_log = logging.getLogger("polarprism")

MIN_TILE_ZOOM = 7
MAX_TILE_ZOOM = 13
TILE_SIZE = 256

# Two layers make a usable nautical chart: an opaque base map (land/water/
# coastline) with the transparent OpenSeaMap seamark overlay (buoys, marks) on
# top. The seamark tiles alone are ~transparent, which is why a base layer is
# required — without it the chart is just blank water.
LAYER_BASE = "base"
LAYER_SEAMARK = "seamark"

DEFAULT_BASE_URL = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
DEFAULT_SEAMARK_URL = "https://tiles.openseamap.org/seamark/{z}/{x}/{y}.png"

# OpenSeaMap / OSM tile-usage policies reject the default ``Python-urllib``
# User-Agent. Identify the app explicitly or downloads return 403/418.
TILE_USER_AGENT = "PolarPrism/0.1 (sailing navigation instrument)"
# Cap downloads per drain so a large pan doesn't fire hundreds of requests at
# the tile server in one burst; the rest carry over to the next drain.
TILE_FETCH_BATCH = 8
# After a failed download, wait before re-queuing the same tile — otherwise the
# renderer re-queues it every frame and hammers an unreachable server forever.
RETRY_BACKOFF_S = 30.0

TileKey = tuple[str, int, int, int]  # (layer, z, tx, ty)

TILE_CACHE: dict[TileKey, pygame.Surface] = {}
TILE_CACHE_MAX = 800

tile_dir: str = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tiles")
tile_online: bool = True
tile_urls: dict[str, str] = {
    LAYER_BASE: DEFAULT_BASE_URL,
    LAYER_SEAMARK: DEFAULT_SEAMARK_URL,
}

_pending: set[TileKey] = set()
_retry_after: dict[TileKey, float] = {}


def configure_tiles(
    config_tiles_dir: str,
    config_tile_online: bool,
    base_url: str | None = None,
    overlay_url: str | None = None,
) -> None:
    """Point the tile system at its cache dir, online flag, and layer URLs.

    ``base_url`` is the opaque base map; ``overlay_url`` is the transparent
    seamark overlay. Pass an empty string for ``overlay_url`` to disable the
    overlay layer. ``None`` keeps the current default for that layer.
    """
    global tile_dir, tile_online
    tile_dir = config_tiles_dir
    tile_online = config_tile_online
    if base_url:
        tile_urls[LAYER_BASE] = base_url
    if overlay_url is not None:
        tile_urls[LAYER_SEAMARK] = overlay_url


def latlon_to_tile_xy(lat, lon, z):
    n = 2**z
    x = (lon + 180.0) / 360.0 * n
    lat_rad = math.radians(lat)
    y = (1.0 - math.log(math.tan(lat_rad) + 1.0 / math.cos(lat_rad)) / math.pi) / 2.0 * n
    return x, y


def tile_xy_to_latlon(x, y, z):
    n = 2**z
    lon = x / n * 360.0 - 180.0
    lat_rad = math.atan(math.sinh(math.pi * (1.0 - 2.0 * y / n)))
    lat = math.degrees(lat_rad)
    return lat, lon


def _tile_path(layer: str, z: int, tx: int, ty: int) -> str:
    return os.path.join(tile_dir, layer, str(z), str(tx), f"{ty}.png")


def _download_tile_sync(layer: str, z: int, tx: int, ty: int) -> bool:
    """Blocking download of one tile to disk. Returns True on success.

    Runs on a worker thread (see :func:`process_pending_tiles`). Writes to a
    ``.part`` file and renames so a partial download can never be read back as
    a corrupt tile.
    """
    template = tile_urls.get(layer)
    if not template:
        return False
    url = template.format(z=z, x=tx, y=ty)
    dest_path = _tile_path(layer, z, tx, ty)
    if os.path.exists(dest_path):
        return True
    tmp_path = dest_path + ".part"
    try:
        os.makedirs(os.path.dirname(dest_path), exist_ok=True)
        req = urllib.request.Request(url, headers={"User-Agent": TILE_USER_AGENT})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = resp.read()
        with open(tmp_path, "wb") as f:
            f.write(data)
        os.replace(tmp_path, dest_path)
        return True
    except Exception as exc:
        _log.debug("tile download failed %s z%s/%s/%s: %s", layer, z, tx, ty, exc)
        with contextlib.suppress(OSError):
            os.remove(tmp_path)
        return False


def _evict_cache() -> None:
    if len(TILE_CACHE) > TILE_CACHE_MAX:
        keys_to_remove = list(TILE_CACHE.keys())[: len(TILE_CACHE) - TILE_CACHE_MAX]
        for k in keys_to_remove:
            TILE_CACHE.pop(k, None)


def get_tile(layer: str, z: int, tx: int, ty: int) -> pygame.Surface | None:
    key = (layer, z, tx, ty)
    if key in TILE_CACHE:
        return TILE_CACHE[key]
    path = _tile_path(layer, z, tx, ty)
    if os.path.exists(path):
        try:
            surf = pygame.image.load(path).convert_alpha()
            TILE_CACHE[key] = surf
            _evict_cache()
            return surf
        except Exception:
            return None
    return None


def queue_tile_fetch(layer: str, z: int, tx: int, ty: int) -> None:
    if not tile_online or not tile_urls.get(layer):
        return
    if os.path.exists(_tile_path(layer, z, tx, ty)):
        return
    key = (layer, z, tx, ty)
    if key in _pending:
        return
    retry_at = _retry_after.get(key)
    if retry_at is not None and time.monotonic() < retry_at:
        return
    _pending.add(key)


def pending_tile_count(layer: str | None = None) -> int:
    """Tiles queued for download, optionally filtered to one ``layer``."""
    if layer is None:
        return len(_pending)
    return sum(1 for k in _pending if k[0] == layer)


def is_tile_online() -> bool:
    """Live online flag (set by :func:`configure_tiles` after startup)."""
    return tile_online


def has_overlay() -> bool:
    """Whether a seamark overlay URL is configured."""
    return bool(tile_urls.get(LAYER_SEAMARK))


async def process_pending_tiles() -> int:
    """Download up to ``TILE_FETCH_BATCH`` queued tiles off the event loop.

    Each download runs on a worker thread so the render loop keeps ticking.
    Returns the number of tiles successfully fetched this drain; a fetched tile
    will appear on the chart the next time :func:`get_tile` reads it from disk.
    Failed tiles get a retry-backoff so a down server isn't hammered every frame.
    """
    if not tile_online or not _pending:
        return 0

    batch = list(_pending)[:TILE_FETCH_BATCH]
    fetched = 0
    for key in batch:
        _pending.discard(key)
        ok = await asyncio.to_thread(_download_tile_sync, *key)
        if ok:
            _retry_after.pop(key, None)
            fetched += 1
        else:
            _retry_after[key] = time.monotonic() + RETRY_BACKOFF_S
    return fetched
