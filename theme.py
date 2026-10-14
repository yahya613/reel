"""Colors, fonts, vector icons and small shared widgets."""
import sys
from PyQt6.QtCore import Qt, QRectF, QSize, QByteArray, pyqtSignal, QTimer, QVariantAnimation, QEasingCurve
from PyQt6.QtGui import QPainter, QColor, QFont, QPainterPath, QPixmap, QIcon, QLinearGradient, QPen
from PyQt6.QtSvg import QSvgRenderer
from PyQt6.QtWidgets import QAbstractButton, QWidget, QGraphicsOpacityEffect

BG = '#0a0a0e'
SURFACE = '#14141b'
SURFACE2 = '#1c1c25'
BORDER = '#272732'
TEXT = '#f3f3f6'
MUTED = '#8c8c9b'
ACCENT = '#5b8cff'
ACCENT2 = '#7aa2ff'

FAMILIES = (['Segoe UI Variable Text', 'Segoe UI'] if sys.platform == 'win32'
            else ['SF Pro Text', 'SF Pro', '.AppleSystemUIFont', 'Helvetica Neue', 'Arial'])


def font(px, weight=QFont.Weight.Normal):
    f = QFont()
    f.setFamilies(FAMILIES)
    f.setPixelSize(int(px))
    f.setWeight(weight)
    f.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    return f


BOLD = QFont.Weight.DemiBold
HEAVY = QFont.Weight.Bold

# ---------------------------------------------------------------- icons (24x24 stroke icons)
SPEAKER = ('<path d="M11 4.7L6.6 8.5H3.6a1.1 1.1 0 0 0-1.1 1.1v4.8a1.1 1.1 0 0 0 1.1 1.1h3l4.4 3.8'
           'a.6.6 0 0 0 1-.45V5.15a.6.6 0 0 0-1-.45z" fill="currentColor" stroke="none"/>')
ICONS = {
    'play': '<path d="M7.5 5.2v13.6a1.1 1.1 0 0 0 1.7.93l10.6-6.8a1.1 1.1 0 0 0 0-1.86L9.2 4.27a1.1 1.1 0 0 0-1.7.93z" fill="currentColor" stroke="none"/>',
    'pause': '<rect x="5.5" y="4.5" width="4.5" height="15" rx="1.3" fill="currentColor" stroke="none"/>'
             '<rect x="14" y="4.5" width="4.5" height="15" rx="1.3" fill="currentColor" stroke="none"/>',
    'next': '<path d="M5 5.6v12.8a1 1 0 0 0 1.56.83l9.3-6.4a1 1 0 0 0 0-1.66l-9.3-6.4A1 1 0 0 0 5 5.6z" fill="currentColor" stroke="none"/>'
            '<path d="M19.5 5v14" stroke-width="2.4"/>',
    'back': '<path d="M19 12H5M11.5 18.5L5 12l6.5-6.5"/>',
    'chevron-left': '<path d="M15 18l-6-6 6-6"/>',
    'chevron-right': '<path d="M9 18l6-6-6-6"/>',
    'vol': SPEAKER + '<path d="M15.5 8.6a4.8 4.8 0 0 1 0 6.8"/><path d="M18.6 5.6a9 9 0 0 1 0 12.8"/>',
    'vol-low': SPEAKER + '<path d="M15.5 8.6a4.8 4.8 0 0 1 0 6.8"/>',
    'mute': SPEAKER + '<path d="M22 9.2l-5.6 5.6M16.4 9.2l5.6 5.6"/>',
    'fs': '<path d="M8 3.5H5.5a2 2 0 0 0-2 2V8M20.5 8V5.5a2 2 0 0 0-2-2H16M3.5 16v2.5a2 2 0 0 0 2 2H8M16 20.5h2.5a2 2 0 0 0 2-2V16"/>',
    'fs-exit': '<path d="M8 3.5V6a2 2 0 0 1-2 2H3.5M20.5 8H18a2 2 0 0 1-2-2V3.5M3.5 16H6a2 2 0 0 1 2 2v2.5M16 20.5V18a2 2 0 0 1 2-2h2.5"/>',
    'cc': '<rect x="2.5" y="4.5" width="19" height="15" rx="3.2"/><path d="M7 15h3.5M13.5 15H17M7 11h6M16 11h1"/>',
    'rew': '<path d="M4.2 12a7.8 7.8 0 1 0 2.3-5.5L4 9"/><path d="M4 4v5h5"/>',
    'fwd': '<path d="M19.8 12a7.8 7.8 0 1 1-2.3-5.5L20 9"/><path d="M20 4v5h-5"/>',
    'search': '<circle cx="11" cy="11" r="6.8"/><path d="M20.5 20.5l-4.6-4.6"/>',
    'folder': '<path d="M3 7.2a2 2 0 0 1 2-2h3.8a1.5 1.5 0 0 1 1.2.6l1.4 1.9h7.6a2 2 0 0 1 2 2v8.1a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
    'file': '<path d="M14 3.5H7a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8.5z"/><path d="M14 3.5v5h5"/><path d="M10 12.2v5l4-2.5z" fill="currentColor"/>',
    'plus': '<path d="M12 5v14M5 12h14"/>',
    'x': '<path d="M18 6L6 18M6 6l12 12"/>',
    'check': '<path d="M20 6.5L9.2 17.3 4 12.1"/>',
    'refresh': '<path d="M20 12a8 8 0 1 1-2.6-5.9L20 8.5"/><path d="M20 3.5v5h-5"/>',
    'film': '<rect x="3" y="3" width="18" height="18" rx="2.5"/><path d="M7.5 3v18M16.5 3v18M3 8h4.5M3 12h18M3 16h4.5M16.5 8H21M16.5 16H21"/>',
    'tv': '<rect x="2.5" y="6.5" width="19" height="13" rx="2.5"/><path d="M8 2.8l4 3.7 4-3.7"/>',
    'home': '<path d="M3.5 10.5L12 3.5l8.5 7V19a1.5 1.5 0 0 1-1.5 1.5h-4.5V15h-5v5.5H5A1.5 1.5 0 0 1 3.5 19z"/>',
    'skip': '<path d="M6 17.5l5.5-5.5L6 6.5M13 17.5l5.5-5.5L13 6.5"/>',
    'layers': '<path d="M12 3.5l9 4.8-9 4.8-9-4.8z"/><path d="M3 12.5l9 4.8 9-4.8"/>',
    'sparkles': '<path d="M12 3l1.8 4.9L18.7 9.7l-4.9 1.8L12 16.4l-1.8-4.9L5.3 9.7l4.9-1.8z"/>'
                '<path d="M18.5 14.5l.8 2.1 2.1.8-2.1.8-.8 2.1-.8-2.1-2.1-.8 2.1-.8z" stroke-width="1.6"/>',
    'plus-circle': '<circle cx="12" cy="12" r="9"/><path d="M12 8v8M8 12h8"/>',
    'bookmark': '<path d="M6.5 3.5h11a1 1 0 0 1 1 1V21l-6.5-4-6.5 4V4.5a1 1 0 0 1 1-1z"/>',
    'play-o': '<circle cx="12" cy="12" r="9"/><path d="M10 8.5l5 3.5-5 3.5z" fill="currentColor" stroke="none"/>',
    'users': '<circle cx="9" cy="8" r="3.4"/><path d="M3.5 19.5a5.5 5.5 0 0 1 11 0"/>'
             '<path d="M16 5.2a3.4 3.4 0 0 1 0 6.1"/><path d="M17.5 14.2a5.5 5.5 0 0 1 3 4.8"/>',
    'power': '<path d="M12 4v8"/><path d="M7.5 7a7 7 0 1 0 9 0"/>',
    'download': '<path d="M12 4v11"/><path d="M7 10.5l5 5 5-5"/><path d="M4.5 19.5h15"/>',
}
_cache = {}


def renderer(name, color):
    key = (name, color)
    r = _cache.get(key)
    if r is None:
        svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
               'stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' + ICONS[name] + '</svg>')
        r = _cache[key] = QSvgRenderer(QByteArray(svg.replace('currentColor', color).encode()))
    return r


def draw_icon(p, name, rect, color=TEXT):
    renderer(name, color if isinstance(color, str) else color.name()).render(p, QRectF(rect))


def qicon(name, color=TEXT, size=20):
    pm = QPixmap(size * 2, size * 2)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    draw_icon(p, name, QRectF(0, 0, size * 2, size * 2), color)
    p.end()
    pm.setDevicePixelRatio(2)
    return QIcon(pm)


def app_icon(size=256):
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    g = QLinearGradient(0, 0, size, size)
    g.setColorAt(0, QColor('#6d9bff'))
    g.setColorAt(1, QColor('#3a5fe0'))
    path = QPainterPath()
    path.addRoundedRect(QRectF(size * .04, size * .04, size * .92, size * .92), size * .23, size * .23)
    p.fillPath(path, g)
    draw_icon(p, 'play', QRectF(size * .24, size * .22, size * .56, size * .56), '#ffffff')
    p.end()
    return pm


def rounded(rect, r):
    path = QPainterPath()
    path.addRoundedRect(QRectF(rect), r, r)
    return path


# ---------------------------------------------------------------- widgets

class IconButton(QAbstractButton):
    def __init__(self, icon, size=40, icon_size=22, parent=None, label=None, tip=None):
        super().__init__(parent)
        self.icon_name, self.icon_size, self.label = icon, icon_size, label
        self.setFixedSize(size, size)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.color = TEXT
        self.active = False
        if tip:
            self.setToolTip(tip)

    def set_icon(self, name):
        if name != self.icon_name:
            self.icon_name = name
            self.update()

    def enterEvent(self, e):
        self.update()

    def leaveEvent(self, e):
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect())
        if self.isDown():
            p.setBrush(QColor(255, 255, 255, 46))
        elif self.underMouse():
            p.setBrush(QColor(255, 255, 255, 28))
        else:
            p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(r.adjusted(1, 1, -1, -1))
        s = self.icon_size
        ir = QRectF((r.width() - s) / 2, (r.height() - s) / 2, s, s)
        draw_icon(p, self.icon_name, ir, ACCENT2 if self.active else self.color)
        if self.label:
            p.setPen(QColor(self.color))
            p.setFont(font(s * .38, HEAVY))
            p.drawText(ir.adjusted(0, 1, 0, 1), Qt.AlignmentFlag.AlignCenter, self.label)


class PillButton(QAbstractButton):
    def __init__(self, text, icon=None, kind='primary', parent=None, h=40, px=15):
        super().__init__(parent)
        self.setText(text)
        self.icon_name, self.kind, self.px = icon, kind, px
        self.setFixedHeight(h)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._fit()

    def _fit(self):
        fm_w = self.fontMetrics_w()
        self.setFixedWidth(int(fm_w + 40 + (26 if self.icon_name else 0)))

    def fontMetrics_w(self):
        from PyQt6.QtGui import QFontMetricsF
        return QFontMetricsF(font(self.px, BOLD)).horizontalAdvance(self.text())

    def setText(self, t):
        super().setText(t)
        if hasattr(self, 'kind'):
            self._fit()
            self.update()

    def enterEvent(self, e):
        self.update()

    def leaveEvent(self, e):
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(.5, .5, -.5, -.5)
        hov = self.underMouse()
        if self.kind == 'primary':
            bg, fg, pen = QColor(ACCENT2 if hov else ACCENT), QColor('#ffffff'), None
        elif self.kind == 'light':
            bg, fg, pen = QColor('#ffffff' if hov else '#e9e9ee'), QColor('#0a0a0e'), None
        elif self.kind == 'outline':
            bg, fg, pen = QColor(255, 255, 255, 40 if hov else 14), QColor(TEXT), QColor(255, 255, 255, 150)
        else:
            bg, fg, pen = QColor(255, 255, 255, 38 if hov else 22), QColor(TEXT), None
        if self.isDown():
            bg = bg.darker(115)
        p.setBrush(bg)
        p.setPen(QPen(pen, 1.2) if pen else Qt.PenStyle.NoPen)
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        p.setFont(font(self.px, BOLD))
        p.setPen(fg)
        x = 20
        if self.icon_name:
            s = self.px + 4
            draw_icon(p, self.icon_name, QRectF(x - 2, (r.height() - s) / 2 + .5, s, s), fg.name())
            x += s + 6
        p.drawText(QRectF(x, 0, r.width() - x, r.height()), Qt.AlignmentFlag.AlignVCenter, self.text())


class Fader:
    """Fades a set of widgets in/out together with an opacity effect."""

    def __init__(self, widgets, ms=180):
        self.widgets, self.visible = widgets, True
        self.effects = []
        for w in widgets:
            eff = QGraphicsOpacityEffect(w)
            eff.setOpacity(1.0)
            w.setGraphicsEffect(eff)
            self.effects.append(eff)
        self.anim = QVariantAnimation()
        self.anim.setDuration(ms)
        self.anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.anim.valueChanged.connect(self._set)
        self.anim.finished.connect(self._done)

    def _set(self, v):
        for e in self.effects:
            e.setOpacity(v)

    def _done(self):
        if not self.visible:
            for w in self.widgets:
                w.hide()

    def show(self, on, animate=True):
        if on == self.visible:
            return
        self.visible = on
        if on:
            for w in self.widgets:
                w.show()
        self.anim.stop()
        if not animate:
            self._set(1.0 if on else 0.0)
            self._done()
            return
        self.anim.setStartValue(self.effects[0].opacity())
        self.anim.setEndValue(1.0 if on else 0.0)
        self.anim.start()


class Toast(QWidget):
    def __init__(self, parent):
        super().__init__(parent)
        self.text = ''
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.fader = Fader([self], 220)
        self.fader.show(False, False)
        self.timer = QTimer(self, singleShot=True, timeout=lambda: self.fader.show(False))

    def flash(self, text, ms=1500):
        self.text = text
        from PyQt6.QtGui import QFontMetricsF
        w = QFontMetricsF(font(15, BOLD)).horizontalAdvance(text) + 40
        par = self.parentWidget()
        self.setGeometry(int((par.width() - w) / 2), 92, int(w), 42)
        self.raise_()
        self.update()
        self.fader.show(True)
        self.timer.start(ms)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(16, 16, 22, 225))
        p.drawRoundedRect(QRectF(self.rect()), 21, 21)
        p.setPen(QColor(TEXT))
        p.setFont(font(15, BOLD))
        p.drawText(QRectF(self.rect()), Qt.AlignmentFlag.AlignCenter, self.text)
