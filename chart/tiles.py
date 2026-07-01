import asyncio
import contextlib
import logging
import math
import os
import urllib.request

import pygame

_log = logging.getLogger("polarprism")

MIN_TILE_ZOOM = 7
MAX_TILE_ZOOM = 13
TILE_SIZE = 256
TILE_CACHE: dict[tuple[int, int, int], pygame.Surface] = {}
TILE_CACHE_MAX = 500

# OpenSeaMap / OSM tile-usage policies reject the default ``Python-urllib``
# User-Agent. Identify the app explicitly or downloads return 403/418.
TILE_USER_AGENT = "PolarPrism/0.1 (sailing navigation instrument)"
# Cap downloads per drain so a large pan doesn't fire hundreds of requests at
# the tile server in one burst; the rest carry over to the next drain.
TILE_FETCH_BATCH = 8

tile_dir: str = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tiles")
tile_online: bool = True
tile_url_template: str = "https://tiles.openseamap.org/seamark/{z}/{x}/{y}.png"

_pending_tiles: set[tuple[int, int, int]] = set()


def configure_tiles(config_tiles_dir: str, config_tile_online: bool, config_tile_url: str) -> None:
    global tile_dir, tile_online, tile_url_template
    tile_dir = config_tiles_dir
    tile_online = config_tile_online
    tile_url_template = config_tile_url


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


def _download_tile_sync(z: int, tx: int, ty: int) -> bool:
    """Blocking download of one tile to disk. Returns True on success.

    Runs on a worker thread (see :func:`process_pending_tiles`). Writes to a
    ``.part`` file and renames so a partial download can never be read back as
    a corrupt tile.
    """
    url = tile_url_template.format(z=z, x=tx, y=ty)
    dest_dir = os.path.join(tile_dir, str(z), str(tx))
    dest_path = os.path.join(dest_dir, f"{ty}.png")
    if os.path.exists(dest_path):
        return True
    tmp_path = dest_path + ".part"
    try:
        os.makedirs(dest_dir, exist_ok=True)
        req = urllib.request.Request(url, headers={"User-Agent": TILE_USER_AGENT})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = resp.read()
        with open(tmp_path, "wb") as f:
            f.write(data)
        os.replace(tmp_path, dest_path)
        return True
    except Exception as exc:
        _log.debug("tile download failed z%s/%s/%s: %s", z, tx, ty, exc)
        with contextlib.suppress(OSError):
            os.remove(tmp_path)
        return False


def _evict_cache() -> None:
    if len(TILE_CACHE) > TILE_CACHE_MAX:
        keys_to_remove = list(TILE_CACHE.keys())[: len(TILE_CACHE) - TILE_CACHE_MAX]
        for k in keys_to_remove:
            TILE_CACHE.pop(k, None)


def get_tile(z, tx, ty):
    key = (z, tx, ty)
    if key in TILE_CACHE:
        return TILE_CACHE[key]
    path = os.path.join(tile_dir, str(z), str(tx), f"{ty}.png")
    if os.path.exists(path):
        try:
            surf = pygame.image.load(path)
            TILE_CACHE[key] = surf
            _evict_cache()
            return surf
        except Exception:
            pass
    return None


def queue_tile_fetch(z: int, tx: int, ty: int) -> None:
    if not tile_online:
        return
    path = os.path.join(tile_dir, str(z), str(tx), f"{ty}.png")
    if os.path.exists(path):
        return
    key = (z, tx, ty)
    if key in _pending_tiles:
        return
    _pending_tiles.add(key)


def pending_tile_count() -> int:
    """Number of tiles queued for download (for the chart status indicator)."""
    return len(_pending_tiles)


def is_tile_online() -> bool:
    """Live online flag (set by :func:`configure_tiles` after startup)."""
    return tile_online


async def process_pending_tiles() -> int:
    """Download up to ``TILE_FETCH_BATCH`` queued tiles off the event loop.

    Each download runs on a worker thread so the render loop keeps ticking.
    Returns the number of tiles successfully fetched this drain; a fetched tile
    will appear on the chart the next time :func:`get_tile` reads it from disk.
    """
    if not tile_online or not _pending_tiles:
        return 0

    batch = list(_pending_tiles)[:TILE_FETCH_BATCH]
    fetched = 0
    for z, tx, ty in batch:
        _pending_tiles.discard((z, tx, ty))
        ok = await asyncio.to_thread(_download_tile_sync, z, tx, ty)
        if ok:
            fetched += 1
    return fetched
