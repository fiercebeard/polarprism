from __future__ import annotations

import json
import os
import tempfile

from config import Config, load_config, ws_url_to_rest_url
from polars.parser import (
    build_sail_groups,
    build_sail_to_polar,
    compute_polar_display_names,
    discover_saildef,
    discover_sailselect,
)


class TestWsUrlToRestUrl:
    def test_default_url(self):
        result = ws_url_to_rest_url("ws://localhost:3000/signalk/v1/stream")
        assert result == "http://localhost:3000/signalk/v1/api"

    def test_custom_host(self):
        result = ws_url_to_rest_url("ws://192.168.1.100:3000/signalk/v1/stream")
        assert result == "http://192.168.1.100:3000/signalk/v1/api"

    def test_wss_url(self):
        result = ws_url_to_rest_url("wss://myserver.com/signalk/v1/stream")
        assert result == "https://myserver.com/signalk/v1/api"


class TestConfig:
    def test_defaults(self):
        cfg = Config()
        assert cfg.signalk_url == "ws://localhost:3000/signalk/v1/stream"
        assert cfg.signalk_rest_url == "http://localhost:3000/signalk/v1/api"
        assert cfg.chart_lat == 41.49
        assert cfg.chart_lon == -81.73
        assert cfg.chart_zoom == 9
        assert cfg.fps == 30

    def test_load_config_missing_file(self):
        cfg = load_config("/nonexistent/path.toml")
        assert cfg.signalk_url == "ws://localhost:3000/signalk/v1/stream"

    def test_load_config_from_file(self):
        with tempfile.NamedTemporaryFile(suffix=".json", mode="w", delete=False) as f:
            json.dump(
                {
                    "signalk": {"url": "ws://192.168.1.50:3000/signalk/v1/stream"},
                    "chart": {"default_lat": 42.0, "default_lon": -70.5, "default_zoom": 10},
                },
                f,
            )
            f.flush()
            path = f.name
        try:
            cfg = load_config(path)
            assert cfg.signalk_url == "ws://192.168.1.50:3000/signalk/v1/stream"
            assert cfg.chart_lat == 42.0
            assert cfg.chart_lon == -70.5
            assert cfg.chart_zoom == 10
        finally:
            os.unlink(path)


class TestDiscoverSaildef:
    def test_empty_dir(self):
        with tempfile.TemporaryDirectory() as d:
            result = discover_saildef(d)
            assert result == {}

    def test_single_saildef(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "MyBoat.saildef"), "w") as f:
                f.write("1;Jib\n2;Asym\n")
            result = discover_saildef(d)
            assert result == {1: "Jib", 2: "Asym"}

    def test_multiple_saildef_uses_first_polar(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "MyBoat.saildef"), "w") as f:
                f.write("1;Jib\n")
            with open(os.path.join(d, "Other.saildef"), "w") as f:
                f.write("1;Code0\n")
            result = discover_saildef(d, polar_names=["MyBoat"])
            assert result == {1: "Jib"}


class TestDiscoverSailselect:
    def test_empty_dir(self):
        with tempfile.TemporaryDirectory() as d:
            result = discover_sailselect(d)
            assert result is None


class TestBuildSailToPolar:
    def test_exact_match(self):
        saildef = {1: "Jib", 2: "Asym"}
        polar_names = ["Jib", "Asym"]
        result = build_sail_to_polar(saildef, polar_names)
        assert result["Jib"] == "Jib"
        assert result["Asym"] == "Asym"

    def test_suffix_match(self):
        saildef = {1: "Jib", 2: "Asym"}
        polar_names = ["example_J105_Jib", "example_J105_Asym"]
        result = build_sail_to_polar(saildef, polar_names)
        assert "Jib" in result
        assert result["Jib"] == "example_J105_Jib"

    def test_empty_saildef(self):
        result = build_sail_to_polar({}, [])
        assert result == {}


class TestBuildSailGroups:
    def test_from_config(self):
        result = build_sail_groups(
            {}, config_groups=[("headsail", ["Jib", "Code0"]), ("downwind", ["Asym"])]
        )
        assert result == [("headsail", ["Jib", "Code0"]), ("downwind", ["Asym"])]

    def test_from_saildef(self):
        saildef = {1: "Jib", 2: "Code0", 3: "Asym"}
        result = build_sail_groups(saildef)
        assert len(result) == 1
        assert "Jib" in result[0][1]

    def test_empty(self):
        result = build_sail_groups({})
        assert result == []


class TestComputePolarDisplayNames:
    def test_with_saildef_mapping(self):
        sail_to_polar = {"Jib": "example_J105_Jib", "Asym": "example_J105_Asym"}
        saildef = {1: "Jib", 2: "Asym"}
        result = compute_polar_display_names(
            ["example_J105_Jib", "example_J105_Asym"], sail_to_polar, saildef
        )
        assert result["example_J105_Jib"] == "Jib"
        assert result["example_J105_Asym"] == "Asym"

    def test_with_prefix_stripping(self):
        sail_to_polar = {}
        saildef = {}
        result = compute_polar_display_names(
            ["example_J105_Jib", "example_J105_Asym"], sail_to_polar, saildef
        )
        assert "example_J105_Jib" in result
        assert result["example_J105_Jib"] != "example_J105_Jib"

    def test_single_polar(self):
        result = compute_polar_display_names(["MyPolar"], {}, {})
        assert result["MyPolar"] == "MyPolar"
