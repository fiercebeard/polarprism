#!/usr/bin/env python3
import asyncio
import os
import sys
import traceback

import pygame

from theme import BG, NAV_WIDTH_RATIO
from signalk.models import State
from signalk.client import (
    ws_reader, fetch_vessel_name, fetch_device_names,
    fetch_multi_values, logger, ws_writer, log_error, set_asyncio_sleep,
    performance_logger, write_log_event,
)
from polars.parser import discover_polars, load_saildef, load_sailselect
import nav
import tabs
from pages import navigation, heading, sailing, settings

FPS = 30
POLARS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "polars")


async def main():
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

    state = State()

    polars = discover_polars(POLARS_DIR)
    for p in polars:
        state.polar_data[p.name] = p
        state.polar_names.append(p.name)
    if state.polar_names:
        state.polar_active = state.polar_names[0]

    saildef_path = os.path.join(POLARS_DIR, "US50_Rated_BestPerf.saildef")
    state.saildef = load_saildef(saildef_path)
    state.saildef.setdefault(3, "Code0")

    sailselect_path = os.path.join(POLARS_DIR, "US50_Rated_BestPerf.sailselect")
    state.sailselect = load_sailselect(sailselect_path)

    set_asyncio_sleep(asyncio.sleep)

    asyncio.ensure_future(fetch_vessel_name(state))
    asyncio.ensure_future(fetch_device_names(state))
    asyncio.ensure_future(fetch_multi_values(state))
    asyncio.ensure_future(ws_reader(state))
    asyncio.ensure_future(logger(state))
    asyncio.ensure_future(ws_writer(state))
    asyncio.ensure_future(performance_logger(state))

    running = True
    dragging_chart = False

    while running:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False

            elif event.type == pygame.VIDEORESIZE:
                win_w, win_h = event.w, event.h
                screen = pygame.display.set_mode((win_w, win_h), pygame.RESIZABLE)

            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    running = False
                elif state.active_nav == "navigation":
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
                if state.active_nav == "sailing":
                    result = sailing.handle_key(state, event.key, state.active_tab)
                    if result and result.startswith("log_"):
                        asyncio.ensure_future(_handle_log_event(state, result))

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
                    if state.active_nav == "navigation":
                        chart_result = navigation.handle_click(state, mx, my, content_rect)
                        if chart_result == "drag":
                            dragging_chart = True
                            state.dragging = True
                            state.drag_start = (mx, my)
                    elif state.active_nav == "sailing":
                        result = sailing.handle_click(state, mx, my, content_rect, state.active_tab)
                        if result and result.startswith("log_"):
                            asyncio.ensure_future(_handle_log_event(state, result))

                if event.button in (4, 5) and mx >= content_x and state.active_nav == "navigation":
                    content_rect = nav.get_content_rect(win_w, win_h)
                    direction = 1 if event.button == 4 else -1
                    navigation.handle_scroll(state, mx, my, content_rect, direction)

            elif event.type == pygame.MOUSEBUTTONUP:
                if event.button == 1:
                    dragging_chart = False
                    state.dragging = False

            elif event.type == pygame.MOUSEMOTION:
                if dragging_chart and state.drag_start:
                    mx, my = event.pos
                    sx, sy = state.drag_start
                    dx = mx - sx
                    dy = my - sy
                    content_rect = nav.get_content_rect(win_w, win_h)
                    navigation.handle_drag(state, dx, dy, content_rect)
                    state.drag_start = (mx, my)

        screen.fill(BG)

        nav_w = max(int(win_w * NAV_WIDTH_RATIO), 160)
        content_x = nav_w
        content_w = win_w - nav_w

        try:
            nav.draw_nav(screen, font, font_sm, state, win_h, nav_w)
        except Exception as e:
            log_error(f"nav: {e}")

        pygame.draw.line(screen, (40, 50, 70), (nav_w, 0), (nav_w, win_h), 1)

        try:
            tabs.draw_tabs(screen, font, font_sm, state, content_x, content_w)
        except Exception as e:
            log_error(f"tabs: {e}")

        content_rect = nav.get_content_rect(win_w, win_h)

        try:
            if state.active_nav == "navigation":
                navigation.render(screen, font, font_sm, state, content_rect)
            elif state.active_nav == "heading":
                heading.render(screen, font, font_sm, state, content_rect, state.active_tab)
            elif state.active_nav == "sailing":
                sailing.render(screen, font, font_sm, state, content_rect, state.active_tab)
            elif state.active_nav == "settings":
                settings.render(screen, font, font_sm, state, content_rect, state.active_tab)
        except Exception as e:
            log_error(f"page render: {e}")

        pygame.display.flip()
        clock.tick(FPS)
        await asyncio.sleep(0)

    pygame.quit()


async def _handle_log_event(state, result):
    if result == "log_start":
        await write_log_event(state, "log_start", {
            "polar": state.polar_active,
            "active_sails": list(state.active_sails),
            "sailing_state": state.sailing_state,
        })
    elif result == "log_stop":
        await write_log_event(state, "log_stop", {
            "samples": state.log_sample_count,
        })
    elif result == "state_change":
        await write_log_event(state, "sailing_state_change", {
            "to": state.sailing_state,
        })
    elif result == "sail_toggle":
        await write_log_event(state, "sail_change", {
            "active_sails": list(state.active_sails),
        })


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pygame.quit()
        sys.exit(0)
    except Exception as e:
        tb = traceback.format_exc()
        log_error(f"FATAL: {e}\n{tb}")
        try:
            pygame.quit()
        except Exception:
            pass
        sys.exit(1)