from __future__ import annotations

import asyncio
import os
import tempfile

import chart.tiles as tiles
from chart.tiles import LAYER_BASE, LAYER_SEAMARK


def _reset_tiles(tmp: str, online: bool, overlay: str | None = "") -> None:
    tiles._pending.clear()
    tiles._retry_after.clear()
    tiles.configure_tiles(
        tmp,
        online,
        base_url="https://example.invalid/{z}/{x}/{y}.png",
        overlay_url=overlay if overlay is not None else "",
    )


class TestQueueTileFetch:
    def test_offline_queues_nothing(self):
        with tempfile.TemporaryDirectory() as d:
            _reset_tiles(d, online=False)
            tiles.queue_tile_fetch(LAYER_BASE, 9, 1, 2)
            assert tiles.pending_tile_count() == 0

    def test_online_queues_and_dedups(self):
        with tempfile.TemporaryDirectory() as d:
            _reset_tiles(d, online=True)
            tiles.queue_tile_fetch(LAYER_BASE, 9, 1, 2)
            tiles.queue_tile_fetch(LAYER_BASE, 9, 1, 2)  # duplicate
            tiles.queue_tile_fetch(LAYER_BASE, 9, 3, 4)
            assert tiles.pending_tile_count() == 2

    def test_layers_are_independent(self):
        with tempfile.TemporaryDirectory() as d:
            _reset_tiles(d, online=True, overlay="https://example.invalid/s/{z}/{x}/{y}.png")
            tiles.queue_tile_fetch(LAYER_BASE, 9, 1, 2)
            tiles.queue_tile_fetch(LAYER_SEAMARK, 9, 1, 2)
            assert tiles.pending_tile_count() == 2
            assert tiles.pending_tile_count(LAYER_BASE) == 1
            assert tiles.pending_tile_count(LAYER_SEAMARK) == 1

    def test_overlay_disabled_when_no_url(self):
        with tempfile.TemporaryDirectory() as d:
            _reset_tiles(d, online=True, overlay="")  # overlay disabled
            assert tiles.has_overlay() is False
            tiles.queue_tile_fetch(LAYER_SEAMARK, 9, 1, 2)
            assert tiles.pending_tile_count() == 0

    def test_cached_tile_not_queued(self):
        with tempfile.TemporaryDirectory() as d:
            _reset_tiles(d, online=True)
            tile_path = os.path.join(d, LAYER_BASE, "9", "1", "2.png")
            os.makedirs(os.path.dirname(tile_path), exist_ok=True)
            with open(tile_path, "wb") as f:
                f.write(b"not-a-real-png")
            tiles.queue_tile_fetch(LAYER_BASE, 9, 1, 2)
            assert tiles.pending_tile_count() == 0


class TestIsTileOnline:
    def test_reflects_configure(self):
        with tempfile.TemporaryDirectory() as d:
            _reset_tiles(d, online=False)
            assert tiles.is_tile_online() is False
            _reset_tiles(d, online=True)
            assert tiles.is_tile_online() is True


class TestProcessPendingTiles:
    def test_offline_is_noop(self):
        with tempfile.TemporaryDirectory() as d:
            _reset_tiles(d, online=False)
            tiles._pending.add((LAYER_BASE, 9, 1, 2))
            assert asyncio.run(tiles.process_pending_tiles()) == 0

    def test_failed_download_backs_off_before_requeue(self):
        # Online but the URL host is unresolvable, so downloads fail fast.
        with tempfile.TemporaryDirectory() as d:
            _reset_tiles(d, online=True)
            tiles.queue_tile_fetch(LAYER_BASE, 9, 1, 2)
            fetched = asyncio.run(tiles.process_pending_tiles())
            assert fetched == 0
            assert tiles.pending_tile_count() == 0
            # A failed tile is not immediately re-queued (retry backoff).
            tiles.queue_tile_fetch(LAYER_BASE, 9, 1, 2)
            assert tiles.pending_tile_count() == 0
