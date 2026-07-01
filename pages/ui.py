import pygame

from theme import SECTION, TEXT_LABEL, TEXT_VALUE


def draw_row(
    surface: pygame.Surface,
    font: pygame.font.Font,
    x: int,
    y: int,
    label: str,
    value: str,
    label_x: int | None = None,
    value_x: int | None = None,
    color: tuple = TEXT_VALUE,
    detail: str = "",
    detail_x: int | None = None,
    detail_color: tuple = TEXT_LABEL,
) -> int:
    lx = label_x if label_x is not None else x
    vx = value_x if value_x is not None else x + 140
    ts_l = font.render(label, True, TEXT_LABEL)
    ts_v = font.render(value, True, color)
    surface.blit(ts_l, (lx, y))
    surface.blit(ts_v, (vx, y))
    if detail:
        dx = detail_x if detail_x is not None else x + 260
        ts_d = font.render(detail, True, detail_color)
        surface.blit(ts_d, (dx, y))
    return ts_l.get_height()


def draw_heading(
    surface: pygame.Surface,
    font: pygame.font.Font,
    x: int,
    y: int,
    text: str,
) -> int:
    ts = font.render(text, True, SECTION)
    surface.blit(ts, (x, y))
    return ts.get_height()


class TextInput:
    """A minimal single-line text input field for pygame.

    The field is rendered inside ``rect``. When ``active`` is True, it shows a
    cursor and accepts text input via :meth:`handle_key`. Callers are
    responsible for routing KEYDOWN events to ``handle_key`` and for
    activating/deactivating the field (e.g. on click and on Enter/Esc).
    """

    CURSOR_BLINK_MS = 500

    PAD_X = 8

    def __init__(self, rect: pygame.Rect, font: pygame.font.Font, text: str = "") -> None:
        self.rect = rect
        self.font = font
        self.text = text
        self.active = False
        self.cursor_visible = True
        self._blink_acc = 0
        # Caret position: index into text (0..len). Insertions/deletions happen
        # here, so the field can be edited anywhere, not just at the end.
        self.cursor_pos = len(text)
        # Horizontal scroll offset (px) for text longer than the field.
        self.scroll_px = 0

    def set_text(self, text: str) -> None:
        self.text = text
        self.cursor_pos = min(self.cursor_pos, len(text))

    def activate(self, text: str | None = None) -> None:
        self.active = True
        if text is not None:
            self.text = text
        self.cursor_pos = len(self.text)
        self._show_cursor()

    def deactivate(self) -> None:
        self.active = False

    def _show_cursor(self) -> None:
        """Force the caret visible and restart the blink (after any edit/move)."""
        self.cursor_visible = True
        self._blink_acc = 0

    def place_cursor_from_x(self, mouse_x: int) -> None:
        """Move the caret to the character boundary nearest ``mouse_x``.

        Lets the user click anywhere in the field to position the insertion
        point instead of only editing at the end.
        """
        target = mouse_x - (self.rect.x + self.PAD_X) + self.scroll_px
        if target <= 0:
            self.cursor_pos = 0
            self._show_cursor()
            return
        pos = len(self.text)
        prev_w = 0
        for i in range(1, len(self.text) + 1):
            w = self.font.size(self.text[:i])[0]
            if target < (prev_w + w) / 2:
                pos = i - 1
                break
            prev_w = w
        self.cursor_pos = max(0, min(len(self.text), pos))
        self._show_cursor()

    def handle_key(self, event: pygame.event.Event) -> str | None:
        """Process one KEYDOWN event. Returns 'commit', 'cancel', or None."""
        if not self.active:
            return None
        key = event.key
        if key == pygame.K_RETURN:
            self.active = False
            return "commit"
        if key == pygame.K_ESCAPE:
            self.active = False
            return "cancel"

        self._show_cursor()
        if key == pygame.K_LEFT:
            self.cursor_pos = max(0, self.cursor_pos - 1)
        elif key == pygame.K_RIGHT:
            self.cursor_pos = min(len(self.text), self.cursor_pos + 1)
        elif key == pygame.K_HOME:
            self.cursor_pos = 0
        elif key == pygame.K_END:
            self.cursor_pos = len(self.text)
        elif key == pygame.K_BACKSPACE:
            if self.cursor_pos > 0:
                self.text = self.text[: self.cursor_pos - 1] + self.text[self.cursor_pos :]
                self.cursor_pos -= 1
        elif key == pygame.K_DELETE:
            if self.cursor_pos < len(self.text):
                self.text = self.text[: self.cursor_pos] + self.text[self.cursor_pos + 1 :]
        elif key == pygame.K_v and (event.mod & pygame.KMOD_CTRL):
            raw = pygame.scrap.get(pygame.SCRAP_TEXT) if pygame.scrap.get_init() else None
            if raw:
                text = raw.decode("utf-8", errors="ignore") if isinstance(raw, bytes) else raw
                text = text.replace("\r", "").replace("\n", "").replace("\x00", "")
                self._insert(text)
        elif event.unicode and event.unicode.isprintable():
            self._insert(event.unicode)
        return None

    def _insert(self, s: str) -> None:
        self.text = self.text[: self.cursor_pos] + s + self.text[self.cursor_pos :]
        self.cursor_pos += len(s)

    def tick(self, dt_ms: int) -> None:
        if not self.active:
            return
        self._blink_acc += dt_ms
        if self._blink_acc >= self.CURSOR_BLINK_MS:
            self._blink_acc = 0
            self.cursor_visible = not self.cursor_visible

    def draw(self, surface: pygame.Surface, bg: tuple, border: tuple, text_color: tuple) -> None:
        from theme import TEXT_DIM

        pygame.draw.rect(surface, bg, self.rect, border_radius=4)
        pygame.draw.rect(surface, border, self.rect, 1, border_radius=4)

        text_surf = self.font.render(self.text, True, text_color)
        text_w = text_surf.get_width()
        text_x = self.rect.x + self.PAD_X
        text_y = self.rect.y + (self.rect.h - text_surf.get_height()) // 2
        max_w = self.rect.w - 2 * self.PAD_X

        # Scroll horizontally so the caret stays inside the field.
        caret_px = self.font.size(self.text[: self.cursor_pos])[0]
        if caret_px - self.scroll_px > max_w:
            self.scroll_px = caret_px - max_w
        if caret_px - self.scroll_px < 0:
            self.scroll_px = caret_px
        self.scroll_px = max(0, min(self.scroll_px, max(0, text_w - max_w)))

        if text_w > 0:
            visible_w = min(max_w, text_w - self.scroll_px)
            surface.blit(
                text_surf,
                (text_x, text_y),
                area=pygame.Rect(self.scroll_px, 0, visible_w, text_surf.get_height()),
            )

        if self.active and self.cursor_visible:
            cursor_x = text_x + (caret_px - self.scroll_px)
            pygame.draw.line(
                surface,
                text_color,
                (cursor_x, self.rect.y + 6),
                (cursor_x, self.rect.bottom - 6),
                1,
            )
        elif not self.active and not self.text:
            hint = self.font.render("(click to edit)", True, TEXT_DIM)
            surface.blit(hint, (text_x, text_y))
