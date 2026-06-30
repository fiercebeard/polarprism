#!/usr/bin/env python3
import argparse
import asyncio
import contextlib
import logging
import os
import sys
import traceback

import pygame

import nav
import tabs
from config import (
    SAIL_COLOR_PALETTE,
    Config,
    load_config,
    load_state,
    save_state,
    ws_url_to_rest_url,
)
from logging_config import setup_logging
from pages import diagnostics, heading, navigation, polar_builder, sailing, settings
from pages import replay as replay_page
from polars.coverage import seed_groups_from_logs
from polars.parser import (
    build_sail_groups,
    build_sail_to_polar,
    compute_polar_display_names,
    discover_measured_polars,
    discover_polars,
    discover_saildef,
    discover_sailselect,
)
from replay.engine import ReplaySession
from routes.parser import discover_routes
from signalk.client import (
    fetch_device_names,
    fetch_multi_values,
    fetch_vessel_name,
    logger,
    perf_sampler,
    performance_logger,
    polar_builder_sampler,
    set_asyncio_sleep,
    set_log_paths,
    write_log_event,
    ws_reader,
)
from signalk.models import State, _refresh_route_cache
from theme import BG, NAV_WIDTH_RATIO, REPLAY_BAR_BG, REPLAY_COLOR, REPLAY_PROGRESS, TEXT_VALUE

_logger = logging.getLogger("polarprism")


def _set_default_polar(state: State, config: Config, theoretical_polars: list) -> None:
    """Choose the active polar: prefer config default, else first theoretical polar."""
    if config.default_polar and config.default_polar in state.polar_data:
        state.polar_active = config.default_polar
    elif theoretical_polars:
        state.polar_active = theoretical_polars[0].name


def _init_state(polars_dir: str, measured_dir: str, routes_dir: str, config: Config) -> State:
    state = State()

    # Track which CSVs fail to load (Phase 7: Setup checklist feedback)
    import glob as globmod

    csv_files = (
        sorted(globmod.glob(os.path.join(polars_dir, "*.csv"))) if os.path.isdir(polars_dir) else []
    )
    polars = discover_polars(polars_dir)
    loaded_names = {p.name for p in polars}
    for csv_path in csv_files:
        fname = os.path.splitext(os.path.basename(csv_path))[0]
        if fname not in loaded_names:
            state.polar_load_failures.append(os.path.basename(csv_path))
    if state.polar_load_failures:
        _logger.warning(
            "Failed to load %d polar(s): %s",
            len(state.polar_load_failures),
            state.polar_load_failures,
        )
    for p in polars:
        state.polar_data[p.name] = p
        state.polar_names.append(p.name)

    # Load measured polars separately if configured
    if config.load_measured:
        measured = discover_measured_polars(measured_dir)
        for p in measured:
            state.polar_data[p.name] = p
            state.polar_names.append(p.name)

    # Set active polar: prefer config default, then first theoretical polar
    _set_default_polar(state, config, polars)

    # Seed Polar Builder groups from on-disk sailing logs (auto-grouped by
    # polar + active-sail combo). load_state later restores any user-edited
    # groups from state.json, overriding the seed.
    state.polar_builder_groups = seed_groups_from_logs(config.log_dir, state.polar_names)

    saildef = discover_saildef(polars_dir, state.polar_names or None)
    state.saildef = saildef

    sailselect = discover_sailselect(polars_dir, state.polar_names or None)
    state.sailselect = sailselect

    sail_to_polar = (
        config.sail_to_polar
        if config.sail_to_polar
        else build_sail_to_polar(saildef, state.polar_names)
    )
    state.sail_to_polar = sail_to_polar

    sail_groups = build_sail_groups(
        saildef,
        config_groups=config.sail_groups if config.sail_groups else None,
    )
    state.sail_groups = sail_groups

    sail_colors = dict(config.sail_colors) if config.sail_colors else {}
    all_sail_names = sorted(saildef.values()) if saildef else []
    for i, sail_name in enumerate(all_sail_names):
        if sail_name not in sail_colors:
            sail_colors[sail_name] = SAIL_COLOR_PALETTE[i % len(SAIL_COLOR_PALETTE)]
    state.sail_colors = sail_colors

    state.available_sails = all_sail_names

    state.polar_display_names = compute_polar_display_names(
        state.polar_names, sail_to_polar, saildef
    )

    # Append '(measured)' suffix to display names of loaded measured polars
    if config.load_measured:
        for name, pol in state.polar_data.items():
            if pol.measured:
                state.polar_display_names[name] = name + " (measured)"

    routes = discover_routes(routes_dir)
    for r in routes:
        state.routes[r.name] = r
        state.route_names.append(r.name)
    if state.route_names:
        state.route_active = state.route_names[0]
        state.route_leg_index = 0
        _refresh_route_cache(state)

    state.chart_center_lat = config.chart_lat
    state.chart_center_lon = config.chart_lon
    state.chart_zoom = config.chart_zoom

    return state


def _spawn_tasks(state: State, config: Config) -> list:
    return [
        asyncio.ensure_future(fetch_vessel_name(state, config.signalk_rest_url)),
        asyncio.ensure_future(fetch_device_names(state, config.signalk_rest_url)),
        asyncio.ensure_future(fetch_multi_values(state, config.signalk_rest_url)),
        asyncio.ensure_future(ws_reader(state, config.signalk_url)),
        asyncio.ensure_future(logger(state)),
        asyncio.ensure_future(performance_logger(state)),
        asyncio.ensure_future(perf_sampler(state)),
        asyncio.ensure_future(polar_builder_sampler(state)),
    ]


def _auto_convert_raw(config: Config) -> None:
    """Import any new raw Signal K logs in config.raw_dir on startup."""
    from signalk.rawlog import auto_convert_raw_dir

    produced = auto_convert_raw_dir(
        config.raw_dir, config.log_dir, config.local_tz_offset, polars_dir=config.polars_dir
    )
    if produced:
        _logger.info("auto-converted %d raw log(s) into %s", len(produced), config.log_dir)


def _discover_log_files(log_dir: str) -> list[str]:
    """Find all .jsonl sailing log files in log_dir, sorted newest first."""
    if not os.path.isdir(log_dir):
        return []
    files = [f for f in os.listdir(log_dir) if f.startswith("sailing_") and f.endswith(".jsonl")]
    return sorted(files, reverse=True)


def _start_replay(state: State, log_path: str) -> None:
    """Helper called from replay hub click handler."""
    session = ReplaySession(log_path, polar_names_map=state.polar_data)
    state.replay_active = True
    state.replay_log_path = log_path
    state._replay_session = session
    state._replay_speed_index = 2
    state.connected = False
    state.polar_active = session.polar_name if session.polar_name else state.polar_active
    # Feed replay samples into the Polar Builder live buffer
    state.sailing_log_active = True
    state.polar_builder_live_buffer = []


def _stop_replay(state: State) -> None:
    """Exit replay mode and clean up session."""
    state.replay_active = False
    state.replay_log_path = ""
    state._replay_session = None
    state.connected = False
    # Stop feeding the Polar Builder live buffer
    state.sailing_log_active = False
    state.polar_builder_live_buffer = []


def _render_replay_bar(
    screen: pygame.Surface,
    font: pygame.font.Font,
    session: ReplaySession | None,
    win_w: int,
    win_h: int,
) -> None:
    """Draw the replay controls bar at the bottom of the screen."""
    if session is None:
        return

    bar_h = 32
    bar_y = win_h - bar_h
    pygame.draw.rect(screen, REPLAY_BAR_BG, (0, bar_y, win_w, bar_h))

    # Status
    status = "PAUSED" if session.is_paused else "PLAYING"
    status_color = (200, 200, 200) if session.is_paused else REPLAY_COLOR
    st = font.render(f"REPLAY  {status}", True, status_color)
    surface_x = max(st.get_width() + 20, 20)
    screen.blit(st, (surface_x, bar_y + bar_h // 2 - st.get_height() // 2))

    # Current time
    cur = font.render(session.wall_current, True, REPLAY_PROGRESS)
    screen.blit(cur, (surface_x + st.get_width() + 30, bar_y + bar_h // 2 - cur.get_height() // 2))

    # Speed label
    sp = font.render(session.speed_label, True, TEXT_VALUE)
    screen.blit(
        sp,
        (
            surface_x + st.get_width() + cur.get_width() + 30,
            bar_y + bar_h // 2 - sp.get_height() // 2,
        ),
    )

    # Progress bar
    progress_w = win_w - 40
    progress_rect = pygame.Rect(20, bar_y + bar_h - 10, progress_w, 4)
    pygame.draw.rect(screen, REPLAY_BAR_BG, progress_rect)
    fill_w = max(4, int(progress_rect.width * session.progress_ratio))
    fill_rect = pygame.Rect(progress_rect.x, progress_rect.y, fill_w, progress_rect.height)
    pygame.draw.rect(screen, REPLAY_PROGRESS, fill_rect)


def _render_frame(
    screen: pygame.Surface,
    state: State,
    font: pygame.font.Font,
    font_sm: pygame.font.Font,
    win_w: int,
    win_h: int,
    config: Config,
) -> None:
    nav_w = max(int(win_w * NAV_WIDTH_RATIO), 160)
    content_x = nav_w
    content_w = win_w - nav_w

    try:
        nav.draw_nav(screen, font, font_sm, state, win_h, nav_w)
    except Exception as e:
        _logger.error("nav: %s", e, exc_info=True)

    pygame.draw.line(screen, (40, 50, 70), (nav_w, 0), (nav_w, win_h), 1)

    try:
        tabs.draw_tabs(screen, font, font_sm, state, content_x, content_w)
    except Exception as e:
        _logger.error("tabs: %s", e, exc_info=True)

    content_rect = nav.get_content_rect(win_w, win_h)

    try:
        if state.active_nav == "navigation":
            navigation.render(screen, font, font_sm, state, content_rect)
        elif state.active_nav == "heading":
            heading.render(screen, font, font_sm, state, content_rect, state.active_tab)
        elif state.active_nav == "sailing":
            sailing.render(screen, font, font_sm, state, content_rect, state.active_tab)
        elif state.active_nav == "builder":
            polar_builder.render(
                screen, font, font_sm, state, content_rect, state.active_tab, config=config
            )
        elif state.active_nav == "replay":
            _render_replay_page(screen, font, font_sm, state, content_rect, config)
        elif state.active_nav == "diagnostics":
            diagnostics.render(screen, font, font_sm, state, content_rect, state.active_tab)
        elif state.active_nav == "settings":
            settings.render(
                screen, font, font_sm, state, content_rect, state.active_tab, config=config
            )
    except Exception as e:
        _logger.error("page render: %s", e, exc_info=True)

    # Overlay replay bar during replay
    session = getattr(state, "_replay_session", None)
    if session is not None:
        _render_replay_bar(screen, font, session, win_w, win_h)


def _render_replay_page(
    screen: pygame.Surface,
    font: pygame.font.Font,
    font_sm: pygame.font.Font,
    state: State,
    rect: tuple[int, int, int, int],
    config: Config,
) -> None:
    """Render the replay hub page when on the Replay nav tab."""
    replay_page.draw_replay_page(screen, font, state, rect, config.log_dir)


async def main() -> None:
    parser = argparse.ArgumentParser(description="PolarPrism - Sailing Navigation Instrument")
    parser.add_argument(
        "--config", dest="config_path", default=None, help="Path to polarprism.toml"
    )
    parser.add_argument("--signalk-url", default=None, help="Signal K WebSocket URL")
    parser.add_argument("--polars-dir", default=None, help="Path to polars directory")
    parser.add_argument("--routes-dir", default=None, help="Path to routes directory")
    args = parser.parse_args()

    config = load_config(args.config_path)
    if args.signalk_url:
        config.signalk_url = args.signalk_url
        config.signalk_rest_url = ws_url_to_rest_url(args.signalk_url)
    if args.polars_dir:
        config.polars_dir = args.polars_dir
    if args.routes_dir:
        config.routes_dir = args.routes_dir

    setup_logging(error_log_dir=config.error_log_dir)

    pygame.init()
    info = pygame.display.Info()
    win_w = info.current_w
    win_h = info.current_h
    screen = pygame.display.set_mode((win_w, win_h), pygame.RESIZABLE)
    pygame.display.set_caption("PolarPrism")

    clock = pygame.time.Clock()

    try:
        font = pygame.font.SysFont("monospace", 20, bold=True)
    except Exception:
        font = pygame.font.Font(None, 22)
    try:
        font_sm = pygame.font.SysFont("monospace", 14)
    except Exception:
        font_sm = pygame.font.Font(None, 16)

    from chart.tiles import configure_tiles

    configure_tiles(config.tiles_dir, config.tile_online, config.tile_url)

    log_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "heading_log.jsonl")
    set_log_paths(log_file, config.log_dir)

    if config.auto_convert_raw:
        _auto_convert_raw(config)

    state = _init_state(config.polars_dir, config.measured_dir, config.routes_dir, config)
    load_state(state, config)
    set_asyncio_sleep(asyncio.sleep)

    _tasks: list = _spawn_tasks(state, config)
    running = True
    dragging_chart = False

    while running:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False

            elif event.type == pygame.VIDEORESIZE:
                win_w, win_h = event.w, event.h
                screen = pygame.display.set_mode((win_w, win_h), pygame.RESIZABLE)

            elif event.type == pygame.MOUSEWHEEL:
                # Scrub replay timeline on mouse wheel
                session = state._replay_session
                if session is not None and session.entry_count > 0:
                    idx = session._sample_idx + int(event.y * 10)
                    session.seek_to(idx)

            elif event.type == pygame.KEYDOWN:
                # If the Settings URL editor is active, it consumes all keys
                url_input = getattr(state, "_sk_url_input", None)
                if url_input is not None and url_input.active and state.active_nav == "settings":
                    result = settings.handle_key(state, event, state.active_tab, config=config)
                    if result == "sk_reconnect":
                        for t in _tasks:
                            t.cancel()
                        _tasks = _spawn_tasks(state, config)
                    continue

                # If the Polar Builder group-name editor is active, it consumes
                # all keys (so Backspace/letters aren't hijacked as group/delete
                # shortcuts while editing a name).
                pb_name_input = getattr(state, "_pb_name_input", None)
                if (
                    pb_name_input is not None
                    and pb_name_input.active
                    and state.active_nav == "builder"
                ):
                    polar_builder.handle_key(state, event, state.active_tab)
                    continue

                session = state._replay_session
                if event.key == pygame.K_ESCAPE:
                    if session is not None:
                        _stop_replay(state)
                        continue
                    running = False

                # Replay playback controls
                if session is not None:
                    if event.key == pygame.K_SPACE:
                        session.toggle_pause()
                    elif event.key == pygame.K_greater or event.key == pygame.K_period:
                        session.speed_up()
                    elif event.key == pygame.K_less or event.key == pygame.K_comma:
                        session.speed_down()
                    elif event.key == pygame.K_r:
                        session.reset()
                    continue

                if state.active_nav == "navigation":
                    if event.key == pygame.K_c:
                        lat = state.position.get("lat")
                        lon = state.position.get("lon")
                        if lat is not None and lon is not None:
                            state.chart_center_lat = lat
                            state.chart_center_lon = lon
                    elif event.key == pygame.K_PLUS or event.key == pygame.K_EQUALS:
                        if state.chart_zoom < 13:
                            state.chart_zoom += 1
                    elif event.key == pygame.K_MINUS:
                        if state.chart_zoom > 7:
                            state.chart_zoom -= 1
                if state.active_nav == "heading":
                    heading.handle_key(state, event.key, state.active_tab)
                if state.active_nav == "diagnostics":
                    diagnostics.handle_key(state, event.key, state.active_tab)
                if state.active_nav == "sailing":
                    result = sailing.handle_key(state, event.key, state.active_tab)
                    if result and result.startswith(("log_", "sail_")):
                        _tasks.append(asyncio.ensure_future(_handle_log_event(state, result)))
                if state.active_nav == "builder":
                    result = polar_builder.handle_key(state, event, state.active_tab)
                    if result == "build_polar":
                        _tasks.append(asyncio.ensure_future(_handle_build_polar(state, config)))
                    elif result == "combine_best":
                        _tasks.append(asyncio.ensure_future(_handle_combine_best(state, config)))

            elif event.type == pygame.MOUSEBUTTONDOWN:
                mx, my = event.pos
                nav_w = max(int(win_w * NAV_WIDTH_RATIO), 160)
                content_x = nav_w

                nav_click = nav.get_nav_click(mx, my, font, state, win_w)
                if nav_click is not None:
                    state.active_nav = nav_click
                    state.active_tab = 0
                    dragging_chart = False
                    continue

                tab_click = tabs.get_tab_click(mx, my, font, state, content_x, win_w - nav_w)
                if tab_click is not None:
                    state.active_tab = tab_click
                    dragging_chart = False
                    continue

                if event.button == 1 and mx >= content_x:
                    content_rect = nav.get_content_rect(win_w, win_h)

                    # Handle replay page click for file list
                    if state.active_nav == "replay":
                        event_str = replay_page.handle_replay_page_click(
                            state,
                            mx,
                            my,
                            content_rect,
                            config.log_dir,
                            lambda fp: _start_replay(state, fp),
                        )
                        if event_str == "stop":
                            _stop_replay(state)
                        continue

                    if state.active_nav == "navigation":
                        chart_result = navigation.handle_click(state, mx, my, content_rect)
                        if chart_result == "drag":
                            dragging_chart = True
                            state.dragging = True
                            state.drag_start = (mx, my)
                    elif state.active_nav == "sailing":
                        result = sailing.handle_click(state, mx, my, content_rect, state.active_tab)
                        if result and result.startswith(("log_", "sail_")):
                            _tasks.append(asyncio.ensure_future(_handle_log_event(state, result)))
                    elif state.active_nav == "builder":
                        result = polar_builder.handle_click(
                            state, mx, my, content_rect, state.active_tab, config=config
                        )
                        if result == "build_polar":
                            _tasks.append(asyncio.ensure_future(_handle_build_polar(state, config)))
                        elif result == "combine_best":
                            _tasks.append(
                                asyncio.ensure_future(_handle_combine_best(state, config))
                            )
                    elif state.active_nav == "settings":
                        result = settings.handle_click(
                            state, mx, my, content_rect, state.active_tab, config=config
                        )
                        if result == "sk_reconnect":
                            for t in _tasks:
                                t.cancel()
                            _tasks = _spawn_tasks(state, config)

                if event.button in (4, 5) and mx >= content_x and state.active_nav == "navigation":
                    content_rect = nav.get_content_rect(win_w, win_h)
                    direction = 1 if event.button == 4 else -1
                    navigation.handle_scroll(state, mx, my, content_rect, direction)

            elif event.type == pygame.MOUSEBUTTONUP:
                if event.button == 1:
                    dragging_chart = False
                    state.dragging = False

            elif (
                event.type == pygame.MOUSEMOTION and dragging_chart and state.drag_start is not None
            ):
                mx, my = event.pos
                sx, sy = state.drag_start
                dx = mx - sx
                dy = my - sy
                content_rect = nav.get_content_rect(win_w, win_h)
                navigation.handle_drag(state, dx, dy, content_rect)
                state.drag_start = (mx, my)

        screen.fill(BG)
        _render_frame(screen, state, font, font_sm, win_w, win_h, config)
        pygame.display.flip()
        dt_ms = clock.tick(config.fps)
        state._frame_dt_ms = dt_ms

        # Drive replay playback forward each frame
        session = state._replay_session
        if session is not None and not session.is_paused:
            session.advance(state, dt_ms)

        await asyncio.sleep(0)

    save_state(state, config)
    pygame.quit()


async def _handle_log_event(state, result):
    if result == "log_start":
        await write_log_event(
            state,
            "log_start",
            {
                "polar": state.polar_active,
                "active_sails": list(state.active_sails),
                "sailing_state": state.sailing_state,
            },
        )
    elif result == "log_stop":
        await write_log_event(
            state,
            "log_stop",
            {
                "samples": state.log_sample_count,
            },
        )
    elif result == "state_change":
        await write_log_event(
            state,
            "sailing_state_change",
            {
                "to": state.sailing_state,
            },
        )
    elif result == "sail_toggle":
        await write_log_event(
            state,
            "sail_change",
            {
                "active_sails": list(state.active_sails),
                "polar": state.polar_active,
            },
        )


async def _handle_build_polar(state: State, config: Config) -> None:
    """Accumulate a measured polar from the active builder group's sessions + live buffer.

    Reuses the log_analysis.py pipeline (build_coverage_from_sessions +
    coverage_mean + write_polar_csv) so the in-app result matches the CLI.
    Each build **accumulates**: the group's new coverage is merged into a
    sidecar ``<name>.cov.json`` kept next to the CSV, and bin means are
    recomputed across all accumulated sessions — so the polar gets richer
    as you build more. Renaming the group (via the name field) retargets the
    output file; a fresh name starts a fresh sidecar.
    Writes to config.measured_dir; if config.load_measured is set, hot-reloads
    the new polar into state.polar_data without a restart.
    """
    import os

    from polars.coverage import (
        build_coverage_from_sessions,
        coverage_mean,
        load_coverage_sidecar,
        merge_coverage,
        save_coverage_sidecar,
    )
    from polars.parser import load_polar

    groups = state.polar_builder_groups
    if not groups:
        return
    idx = max(0, min(state.polar_builder_active_group, len(groups) - 1))
    group = groups[idx]
    sessions = list(group.get("sessions", []))
    polar_name = group.get("polar", "")

    # Build coverage from the group's sessions + live buffer
    new_coverage = build_coverage_from_sessions(sessions)
    if group.get("polar") == state.polar_active and state.polar_builder_live_buffer:
        for twa_bin, tws_bin, stw_kts in state.polar_builder_live_buffer:
            new_coverage.setdefault((twa_bin, tws_bin), []).append(stw_kts)
    if not new_coverage:
        state._pb_build_status = "No coverage data to build from"
        _logger.warning("build_polar: no coverage data for group '%s'", group.get("name"))
        return

    # Write the measured polar CSV (accumulate via sidecar)
    os.makedirs(config.measured_dir, exist_ok=True)
    out_name = group.get("name", "Measured").replace(" ", "_")
    csv_path = os.path.join(config.measured_dir, f"{out_name}.csv")
    accumulated = merge_coverage(load_coverage_sidecar(csv_path), new_coverage)
    measured = coverage_mean(accumulated)
    if not measured:
        state._pb_build_status = "No coverage data to build from"
        _logger.warning("build_polar: no coverage data for group '%s'", group.get("name"))
        return
    try:
        from log_analysis import write_polar_csv

        write_polar_csv(measured, csv_path)
        save_coverage_sidecar(accumulated, csv_path)
    except Exception as exc:
        state._pb_build_status = f"Build failed: {exc}"
        _logger.error("build_polar write failed: %s", exc, exc_info=True)
        return

    total_samples = sum(len(v) for v in accumulated.values())
    state._pb_build_status = f"Built {out_name}.csv ({total_samples} accumulated samples)"

    # Hot-reload the measured polar if configured
    if config.load_measured:
        p = load_polar(csv_path)
        if p is not None:
            p.measured = True
            state.polar_data[p.name] = p
            if p.name not in state.polar_names:
                state.polar_names.append(p.name)
            state.polar_display_names[p.name] = p.name + " (measured)"

    # Optionally generate a comparison image if matplotlib is available
    comparison_polar = state.polar_data.get(polar_name)
    if comparison_polar is not None:
        try:
            from log_analysis import generate_comparison_image

            img_path = os.path.join(config.measured_dir, f"{out_name}_vs_{polar_name}.png")
            generate_comparison_image(measured, comparison_polar, polar_name, img_path)
        except ImportError:
            _logger.debug("matplotlib not installed; skipping comparison image")
        except Exception as exc:
            _logger.warning("comparison image failed: %s", exc, exc_info=True)


async def _handle_combine_best(state: State, config: Config) -> None:
    """Combine all loaded measured polars into an envelope (max STW per bin).

    Reads every polar currently in ``state.polar_data`` flagged
    ``measured=True``, takes the per-bin max STW across them, and writes a
    combined ``combined_best.csv`` to the measured dir. This is the GUI
    counterpart of ``log_analysis.py polar --combine-best``: e.g. merge
    separate jib / code0 / asym measured polars into one best-performance
    polar for a race. Hot-reloads the result if ``config.load_measured`` is set.
    """
    import os

    from polars.coverage import combine_best, read_measured_polar_csv

    measured_paths = _measured_polar_paths(state, config)
    if len(measured_paths) < 2:
        state._pb_build_status = "Need 2+ measured polars to combine"
        return

    measured_dicts = [read_measured_polar_csv(p) for p in measured_paths]
    combined = combine_best(*measured_dicts)
    if not combined:
        state._pb_build_status = "Combined polar has no data"
        return

    os.makedirs(config.measured_dir, exist_ok=True)
    csv_path = os.path.join(config.measured_dir, "combined_best.csv")
    try:
        from log_analysis import write_polar_csv

        write_polar_csv(combined, csv_path)
    except Exception as exc:
        state._pb_build_status = f"Combine failed: {exc}"
        _logger.error("combine_best write failed: %s", exc, exc_info=True)
        return

    state._pb_build_status = f"Built combined_best.csv ({len(combined)} bins)"

    if config.load_measured:
        from polars.parser import load_polar

        p = load_polar(csv_path)
        if p is not None:
            p.measured = True
            state.polar_data[p.name] = p
            if p.name not in state.polar_names:
                state.polar_names.append(p.name)
            state.polar_display_names[p.name] = p.name + " (measured)"


def _measured_polar_paths(state: State, config: Config) -> list[str]:
    """Return paths to on-disk CSVs for all loaded measured polars that still exist."""
    import os

    paths: list[str] = []
    for name, p in state.polar_data.items():
        if not getattr(p, "measured", False):
            continue
        path = os.path.join(config.measured_dir, name + ".csv")
        if os.path.exists(path):
            paths.append(path)
    return paths


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pygame.quit()
        sys.exit(0)
    except Exception as e:
        tb = traceback.format_exc()
        _logger.error("FATAL: %s\n%s", e, tb)
        with contextlib.suppress(Exception):
            pygame.quit()
        sys.exit(1)


def cli() -> None:
    """Synchronous console-script entry point (see pyproject [project.scripts])."""
    asyncio.run(main())
