from __future__ import annotations

import asyncio
import os
import tempfile

import chart.tiles as tiles


def _reset_tiles(tmp: str, online: bool) -> None:
    tiles._pending_tiles.clear()
    tiles.configure_tiles(tmp, online, "https://example.invalid/{z}/{x}/{y}.png")


class TestQueueTileFetch:
    def test_offline_queues_nothing(self):
        with tempfile.TemporaryDirectory() as d:
            _reset_tiles(d, online=False)
            tiles.queue_tile_fetch(9, 1, 2)
            assert tiles.pending_tile_count() == 0

    def test_online_queues_and_dedups(self):
        with tempfile.TemporaryDirectory() as d:
            _reset_tiles(d, online=True)
            tiles.queue_tile_fetch(9, 1, 2)
            tiles.queue_tile_fetch(9, 1, 2)  # duplicate
            tiles.queue_tile_fetch(9, 3, 4)
            assert tiles.pending_tile_count() == 2

    def test_cached_tile_not_queued(self):
        with tempfile.TemporaryDirectory() as d:
            _reset_tiles(d, online=True)
            # Pre-create the on-disk tile so it should be skipped.
            tile_path = os.path.join(d, "9", "1", "2.png")
            os.makedirs(os.path.dirname(tile_path), exist_ok=True)
            with open(tile_path, "wb") as f:
                f.write(b"not-a-real-png")
            tiles.queue_tile_fetch(9, 1, 2)
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
            tiles._pending_tiles.add((9, 1, 2))
            assert asyncio.run(tiles.process_pending_tiles()) == 0

    def test_failed_download_returns_zero_and_drains(self):
        # Online but the URL host is unresolvable, so downloads fail fast.
        with tempfile.TemporaryDirectory() as d:
            _reset_tiles(d, online=True)
            tiles.queue_tile_fetch(9, 1, 2)
            fetched = asyncio.run(tiles.process_pending_tiles())
            assert fetched == 0
            # The attempted tile is removed from the queue even on failure.
            assert tiles.pending_tile_count() == 0
