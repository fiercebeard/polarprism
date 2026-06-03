BG = (15, 16, 20)
NAV_BG = (15, 16, 20)
CONTENT_BG = (15, 16, 20)

NAV_INACTIVE = (156, 163, 175)
NAV_ACTIVE_BG = (243, 244, 246)
NAV_ACTIVE_TEXT = (15, 16, 20)

TAB_INACTIVE = (156, 163, 175)
TAB_ACTIVE = (255, 255, 255)
TAB_ACCENT = (251, 191, 36)

DROPDOWN_BG = (42, 43, 48)
DROPDOWN_TEXT = (255, 255, 255)

TEXT_WHITE = (255, 255, 255)
TEXT_MUTED = (156, 163, 175)
TEXT_DIM = (80, 90, 100)
TEXT_LABEL = (150, 160, 180)
TEXT_VALUE = (220, 230, 240)
TEXT_SRC = (90, 100, 115)

WARN = (255, 80, 80)
OK = (80, 220, 80)
CALC = (100, 220, 180)
SECTION = (100, 120, 150)

CONNECTED = (0, 200, 80)
DISCONNECTED = (200, 50, 50)
FUSION_ON = (0, 200, 255)
FUSION_OFF = (80, 80, 80)

WATER = (8, 14, 28)
GRID = (30, 40, 55)
GRID_MAJOR = (45, 60, 85)
GRID_LABEL = (60, 80, 110)
VESSEL = (200, 210, 220)
VESSEL_OUTLINE = (100, 110, 130)
CHART_BORDER = (50, 60, 80)
ZOOM_BTN_BG = (30, 40, 55)
ZOOM_BTN_BORDER = (80, 100, 130)

COMPASS_RING = (20, 25, 35)
COMPASS_RING_BORDER = (40, 50, 70)
COMPASS_FILL = (15, 18, 28)
COMPASS_TICK = (60, 70, 90)
COMPASS_CENTER_OUTER = (50, 60, 80)
COMPASS_CENTER_INNER = (30, 35, 50)

SIGNAL_COLORS = {
    "headingMagnetic": (0, 220, 60),
    "headingTrue": (255, 255, 255),
    "cogTrue": (255, 60, 60),
    "apTargetMagnetic": (255, 255, 0),
    "magneticVariation": (80, 110, 255),
    "rateOfTurn": (190, 120, 255),
    "fusionTrue": (0, 200, 255),
}

SIGNAL_LABELS = {
    "headingMagnetic": "MAG HDG",
    "headingTrue": "TRUE HDG",
    "cogTrue": "COG TRUE",
    "apTargetMagnetic": "AP TARGET",
    "magneticVariation": "MAG VAR",
    "rateOfTurn": "ROT",
    "fusionTrue": "FUSION",
}

NAV_ITEMS = [
    ("navigation", "\u2693"),
    ("heading", "\u2197"),
    ("sailing", "\u26F5"),
    ("settings", "\u2699"),
]

NAV_ITEM_LABELS = {
    "navigation": "Navigation",
    "heading": "Heading",
    "sailing": "Sailing",
    "settings": "Settings",
}

NAV_TABS = {
    "navigation": ["Chart"],
    "heading": ["Compass", "Diagnostics", "Fusion"],
    "sailing": ["Polars", "Wind", "Log"],
    "settings": ["SignalK", "Display"],
}

NAV_WIDTH_RATIO = 0.20
TAB_HEIGHT = 40
FILTER_ROW_HEIGHT = 36
CONTENT_PAD = 12
NAV_GAP = 16
NAV_PILL_PAD_V = 10
NAV_PILL_PAD_H = 16
TAB_ACCENT_THICKNESS = 2

DROPDOWN_RADIUS = 6
DROPDOWN_PAD_V = 8
DROPDOWN_PAD_H = 12

POLAR_RING = (30, 40, 55)
POLAR_GRID = (40, 50, 70)
POLAR_SPEED_LINE = (60, 80, 110)
POLAR_BOAT_DOT = (255, 200, 60)
POLAR_TARGET_DOT = (80, 220, 80)
POLAR_FILL = (20, 25, 35)

TWS_COLORS = [
    (100, 180, 255),
    (80, 220, 160),
    (160, 230, 80),
    (240, 220, 60),
    (255, 170, 40),
    (255, 110, 60),
    (240, 70, 80),
    (200, 60, 140),
]

WIND_TRUE = (100, 200, 255)
WIND_APPARENT = (255, 200, 80)
WIND_DIR_ARROW = (180, 220, 255)

SAILING_ACTIVE = (80, 220, 80)
SAILING_INACTIVE = (80, 80, 80)
MOTORING_COLOR = (200, 120, 40)
IDLE_COLOR = (100, 100, 120)

SAIL_COLORS = {
    "Jib": (100, 180, 255),
    "Code0": (160, 230, 80),
    "Asym": (255, 110, 60),
}

BTN_BG = (30, 40, 55)
BTN_BORDER = (60, 80, 110)
BTN_ACTIVE_BG = (40, 60, 90)
BTN_ACTIVE_BORDER = (251, 191, 36)