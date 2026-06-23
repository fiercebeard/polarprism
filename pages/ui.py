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

    def __init__(self, rect: pygame.Rect, font: pygame.font.Font, text: str = "") -> None:
        self.rect = rect
        self.font = font
        self.text = text
        self.active = False
        self.cursor_visible = True
        self._blink_acc = 0

    def set_text(self, text: str) -> None:
        self.text = text

    def activate(self, text: str | None = None) -> None:
        self.active = True
        if text is not None:
            self.text = text
        self.cursor_visible = True
        self._blink_acc = 0

    def deactivate(self) -> None:
        self.active = False

    def handle_key(self, event: pygame.event.Event) -> str | None:
        """Process one KEYDOWN event. Returns 'commit', 'cancel', or None."""
        if not self.active:
            return None
        if event.key == pygame.K_RETURN:
            self.active = False
            return "commit"
        if event.key == pygame.K_ESCAPE:
            self.active = False
            return "cancel"
        if event.key == pygame.K_BACKSPACE:
            self.text = self.text[:-1]
            return None
        if event.key == pygame.K_v and (event.mod & pygame.KMOD_CTRL):
            pasted = pygame.scrap.get(pygame.SCRAP_TEXT) if pygame.scrap.get_init() else None
            if pasted:
                if isinstance(pasted, bytes):
                    pasted = pasted.decode("utf-8", errors="ignore")
                self.text += pasted.rstrip("\r\n\x00")
            return None
        if event.unicode and event.unicode.isprintable():
            self.text += event.unicode
            return None
        return None

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
        text_x = self.rect.x + 8
        text_y = self.rect.y + (self.rect.h - text_surf.get_height()) // 2

        # Clip the text to the field width.
        max_w = self.rect.w - 16
        if text_surf.get_width() > max_w:
            # Show the rightmost portion of the text.
            crop_x = text_surf.get_width() - max_w
            surface.blit(
                text_surf,
                (text_x, text_y),
                area=pygame.Rect(crop_x, 0, max_w, text_surf.get_height()),
            )
        else:
            surface.blit(text_surf, (text_x, text_y))

        if self.active and self.cursor_visible:
            cursor_x = text_x + min(text_surf.get_width(), max_w)
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
