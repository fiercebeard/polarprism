import asyncio
import math
import os

import pygame

MIN_TILE_ZOOM = 7
MAX_TILE_ZOOM = 13
TILE_SIZE = 256
TILE_CACHE: dict[tuple[int, int, int], pygame.Surface] = {}
TILE_CACHE_MAX = 500

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


async def _fetch_tile(z: int, tx: int, ty: int) -> None:
    import urllib.request

    url = tile_url_template.format(z=z, x=tx, y=ty)
    dest_dir = os.path.join(tile_dir, str(z), str(tx))
    dest_path = os.path.join(dest_dir, f"{ty}.png")
    if os.path.exists(dest_path):
        return
    try:
        os.makedirs(dest_dir, exist_ok=True)
        urllib.request.urlretrieve(url, dest_path)
    except Exception:
        pass


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


async def process_pending_tiles() -> None:
    if not tile_online:
        return
    import urllib.request

    batch = list(_pending_tiles)
    _pending_tiles.clear()
    for z, tx, ty in batch:
        dest_dir = os.path.join(tile_dir, str(z), str(tx))
        dest_path = os.path.join(dest_dir, f"{ty}.png")
        if os.path.exists(dest_path):
            continue
        url = tile_url_template.format(z=z, x=tx, y=ty)
        try:
            os.makedirs(dest_dir, exist_ok=True)
            urllib.request.urlretrieve(url, dest_path)
        except Exception:
            continue
        await asyncio.sleep(0)
