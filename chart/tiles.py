import math
import os
import pygame

TILE_SIZE = 256
TILE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tiles")
TILE_CACHE = {}
MIN_TILE_ZOOM = 7
MAX_TILE_ZOOM = 13


def latlon_to_tile_xy(lat, lon, z):
    n = 2 ** z
    x = (lon + 180.0) / 360.0 * n
    lat_rad = math.radians(lat)
    y = (1.0 - math.log(math.tan(lat_rad) + 1.0 / math.cos(lat_rad)) / math.pi) / 2.0 * n
    return x, y


def tile_xy_to_latlon(x, y, z):
    n = 2 ** z
    lon = x / n * 360.0 - 180.0
    lat_rad = math.atan(math.sinh(math.pi * (1.0 - 2.0 * y / n)))
    lat = math.degrees(lat_rad)
    return lat, lon


def get_tile(z, tx, ty):
    key = (z, tx, ty)
    if key in TILE_CACHE:
        return TILE_CACHE[key]
    path = os.path.join(TILE_DIR, str(z), str(tx), f"{ty}.png")
    if os.path.exists(path):
        try:
            surf = pygame.image.load(path)
            TILE_CACHE[key] = surf
            return surf
        except Exception:
            pass
    return None