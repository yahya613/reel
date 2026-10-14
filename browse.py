"""Library UI: sidebar, home, movies, shows, detail pages, search."""
import os, re, math, time, shutil, subprocess, sys, hashlib
from PyQt6.QtCore import Qt, QRectF, QSize, QTimer, pyqtSignal, QPoint
from PyQt6.QtGui import QPainter, QColor, QLinearGradient, QFontMetricsF, QFont, QAction, QPixmap, QPen
from PyQt6.QtWidgets import (QWidget, QHBoxLayout, QVBoxLayout, QLabel, QScrollArea, QFrame, QLineEdit,
                             QStackedWidget, QAbstractButton, QMenu, QSizePolicy)
from theme import (BG, SURFACE, SURFACE2, BORDER, TEXT, MUTED, ACCENT, ACCENT2, font, BOLD, HEAVY, draw_icon,
                   qicon, app_icon, rounded, IconButton, PillButton)
from library import fmt_time, fmt_dur, fmt_size, norm_key
from cloud import sync_id

NORMAL = QFont.Weight.Normal

SCROLL_CSS = ('QScrollArea{background:transparent;border:none}'
              'QScrollBar:vertical{width:10px;background:transparent;margin:4px 2px}'
              'QScrollBar::handle:vertical{background:rgba(255,255,255,40);border-radius:3px;min-height:40px}'
              'QScrollBar::handle:vertical:hover{background:rgba(255,255,255,80)}'
              'QScrollBar::add-line,QScrollBar::sub-line,QScrollBar::add-page,QScrollBar::sub-page{height:0;background:none}')
MENU_CSS = (f'QMenu{{background:#1a1a22;border:1px solid {BORDER};border-radius:10px;padding:6px;color:{TEXT}}}'
            'QMenu::item{padding:8px 26px 8px 14px;border-radius:6px}'
            'QMenu::item:selected{background:rgba(255,255,255,22)}'
            f'QMenu::separator{{height:1px;background:{BORDER};margin:5px 8px}}')


def cover(p, pm, rect, cache_owner=None, align_top=False):
    """Draw pixmap scaled to fill rect (center crop)."""
    if not pm or pm.isNull():
        return
    dpr = 2.0
    tw, th = int(rect.width() * dpr), int(rect.height() * dpr)
    key = (pm.cacheKey(), tw, th)
    scaled = None
    if cache_owner is not None:
        c = getattr(cache_owner, '_scaled', None)
        if c and c[0] == key:
            scaled = c[1]
    if scaled is None:
        scaled = pm.scaled(tw, th, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
        if cache_owner is not None:
            cache_owner._scaled = (key, scaled)
    sx = (scaled.width() - tw) / 2
    sy = 0 if align_top else (scaled.height() - th) / 2
    p.drawPixmap(rect, scaled, QRectF(sx, sy, tw, th))


def placeholder(p, rect, title, icon='film'):
    h = int(hashlib.md5(title.encode()).hexdigest()[:2], 16) / 255
    g = QLinearGradient(rect.topLeft(), rect.bottomRight())
    g.setColorAt(0, QColor.fromHslF(h, .35, .22))
    g.setColorAt(1, QColor.fromHslF((h + .12) % 1, .35, .11))
    p.fillRect(rect, g)
    s = min(rect.width(), rect.height()) * .22
    draw_icon(p, icon, QRectF(rect.center().x() - s / 2, rect.center().y() - s / 2 - (rect.height() * .12 if rect.height() > rect.width() else 0), s, s),
              '#ffffff55')
    if rect.height() > rect.width():  # posters: print the title like a key-art card
        p.setPen(QColor(255, 255, 255, 220))
        f = font(max(13, rect.width() * .1), HEAVY)
        p.setFont(f)
        p.drawText(rect.adjusted(14, rect.height() * .52, -14, -12),
                   Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap, title)


# ---------------------------------------------------------------- cards & grids

class Card(QWidget):
    TEXT_H = 52

    def __init__(self, shape, resolve, on_click, on_menu=None, parent=None):
        super().__init__(parent)
        self.shape, self.resolve, self.on_click, self.on_menu = shape, resolve, on_click, on_menu
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.hover = False

    def img_h(self, w):
        return w * 1.5 if self.shape == 'poster' else w * 9 / 16

    def enterEvent(self, e):
        self.hover = True
        self.update()

    def leaveEvent(self, e):
        self.hover = False
        self.update()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and self.rect().contains(e.position().toPoint()):
            self.on_click()

    def contextMenuEvent(self, e):
        if self.on_menu:
            self.on_menu(e.globalPos())

    def paintEvent(self, e):
        d = self.resolve()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        w = self.width()
        full = QRectF(0, 0, w, round(self.img_h(w)))
        ir = full
        if d.get('stack'):                 # draw two offset cards behind, so a collection reads as a set
            ir = full.adjusted(0, 7, 0, 0)
            for i, inset in enumerate((10, 5)):
                layer = QRectF(inset, (2 - i) * 3.5, w - 2 * inset, ir.height())
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(255, 255, 255, 30 + i * 25))
                p.drawRoundedRect(layer, 10, 10)
        p.save()
        p.setClipPath(rounded(ir, 10))
        if d.get('pix'):
            cover(p, d['pix'], ir, self, align_top=self.shape == 'poster')
        else:
            placeholder(p, ir, d.get('title', ''), d.get('icon', 'film'))
        sel = d.get('select')
        if d.get('dim'):
            p.fillRect(ir, QColor(10, 10, 14, 170))
        elif self.hover and sel is None:
            p.fillRect(ir, QColor(0, 0, 0, 70))
            c = ir.center()
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(255, 255, 255, 235))
            p.drawEllipse(c, 26, 26)
            draw_icon(p, 'play', QRectF(c.x() - 12, c.y() - 12, 24, 24), '#0a0a0e')
        elif self.hover:
            p.fillRect(ir, QColor(0, 0, 0, 40))
        prog = d.get('progress', 0)
        if 0 < prog < 1:
            p.setPen(Qt.PenStyle.NoPen)
            bar = QRectF(10, full.height() - 12, w - 20, 4)
            p.setBrush(QColor(0, 0, 0, 140))
            p.drawRoundedRect(bar.adjusted(-1, -1, 1, 1), 3, 3)
            p.setBrush(QColor(255, 255, 255, 80))
            p.drawRoundedRect(bar, 2, 2)
            p.setBrush(QColor(ACCENT))
            p.drawRoundedRect(QRectF(bar.x(), bar.y(), bar.width() * prog, 4), 2, 2)
        p.restore()
        if sel:
            p.setPen(QPen(QColor(ACCENT), 3))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(ir.adjusted(1.5, 1.5, -1.5, -1.5), 10, 10)
        elif self.hover and not d.get('dim'):
            p.setPen(QColor(255, 255, 255, 210))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(ir.adjusted(.75, .75, -.75, -.75), 10, 10)
        if sel is not None:                # select mode: tick circle, top-left
            br = QRectF(9, 9, 28, 28)
            p.setPen(Qt.PenStyle.NoPen if sel else QPen(QColor(255, 255, 255, 235), 2))
            p.setBrush(QColor(ACCENT) if sel else QColor(0, 0, 0, 120))
            p.drawEllipse(br)
            if sel:
                draw_icon(p, 'check', br.adjusted(6, 6, -6, -6), '#ffffff')
        # corner badges
        p.setPen(Qt.PenStyle.NoPen)
        if d.get('watched'):
            br = QRectF(w - 34, 8, 26, 26)
            p.setBrush(QColor(ACCENT))
            p.drawEllipse(br)
            draw_icon(p, 'check', br.adjusted(6, 6, -6, -6), '#ffffff')
        elif d.get('count'):
            t = str(d['count'])
            f = font(12, HEAVY)
            bw = max(26, QFontMetricsF(f).horizontalAdvance(t) + 14)
            br = QRectF(w - bw - 8, 8, bw, 24)
            p.setBrush(QColor(ACCENT))
            p.drawRoundedRect(br, 12, 12)
            p.setPen(QColor('#ffffff'))
            p.setFont(f)
            p.drawText(br, Qt.AlignmentFlag.AlignCenter, t)
        if d.get('badge'):
            f = font(11, HEAVY)
            bw = QFontMetricsF(f).horizontalAdvance(d['badge']) + 14
            br = QRectF(44 if sel is not None else 8, 8 if sel is None else 12, bw, 22)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(0, 0, 0, 170))
            p.drawRoundedRect(br, 6, 6)
            p.setPen(QColor(TEXT))
            p.setFont(f)
            p.drawText(br, Qt.AlignmentFlag.AlignCenter, d['badge'])
        # text
        y = full.height() + 8
        p.setPen(QColor(TEXT))
        f = font(14, BOLD)
        p.setFont(f)
        p.drawText(QRectF(2, y, w - 4, 20), Qt.AlignmentFlag.AlignVCenter,
                   QFontMetricsF(f).elidedText(d.get('title', ''), Qt.TextElideMode.ElideRight, w - 4))
        if d.get('sub'):
            f = font(12.5)
            p.setFont(f)
            p.setPen(QColor(MUTED))
            p.drawText(QRectF(2, y + 21, w - 4, 18), Qt.AlignmentFlag.AlignVCenter,
                       QFontMetricsF(f).elidedText(d['sub'], Qt.TextElideMode.ElideRight, w - 4))


class Grid(QWidget):
    def __init__(self, cards, min_w, gap=20, max_rows=0):
        super().__init__()
        self.cards, self.min_w, self.gap, self.max_rows = cards, min_w, gap, max_rows
        for c in cards:
            c.setParent(self)
        sp = QSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        sp.setHeightForWidth(True)
        self.setSizePolicy(sp)

    def _geom(self, w):
        cols = max(1, int((w + self.gap) // (self.min_w + self.gap)))
        cw = (w - self.gap * (cols - 1)) / cols
        n = len(self.cards) if not self.max_rows else min(len(self.cards), cols * self.max_rows)
        rows = math.ceil(n / cols) if n else 0
        ch = (self.cards[0].img_h(cw) if self.cards else 0) + Card.TEXT_H
        return cols, cw, ch, n, rows

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, w):
        cols, cw, ch, n, rows = self._geom(w)
        return int(rows * ch + max(0, rows - 1) * (self.gap + 6))

    def sizeHint(self):
        return QSize(self.min_w, self.heightForWidth(max(self.width(), self.min_w)))

    def resizeEvent(self, e):
        cols, cw, ch, n, rows = self._geom(self.width())
        for i, c in enumerate(self.cards):
            if i >= n:
                c.hide()
                continue
            r, k = divmod(i, cols)
            c.setGeometry(int(k * (cw + self.gap)), int(r * (ch + self.gap + 6)), int(cw), int(ch))
            c.show()
        h = self.heightForWidth(self.width())
        if self.minimumHeight() != h:
            self.setMinimumHeight(h)


class Page(QScrollArea):
    def __init__(self):
        super().__init__()
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setStyleSheet(SCROLL_CSS)
        self.viewport().setStyleSheet('background:transparent')
        self.fresh()

    def fresh(self, margins=(40, 8, 40, 48), keep_scroll=False):
        pos = self.verticalScrollBar().value() if keep_scroll else 0
        self.body = QWidget()
        self.body.setStyleSheet('background:transparent')
        self.v = QVBoxLayout(self.body)
        self.v.setContentsMargins(*margins)
        self.v.setSpacing(14)
        self.setWidget(self.body)
        if keep_scroll:
            QTimer.singleShot(0, lambda: self.verticalScrollBar().setValue(pos))
        return self.v


def label(text, px, color=TEXT, weight=NORMAL, wrap=False, maxw=None):
    l = QLabel(text)
    l.setFont(font(px, weight))
    l.setStyleSheet(f'color:{color};background:transparent')
    l.setWordWrap(wrap)
    if maxw:
        l.setMaximumWidth(maxw)
    l.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
    return l


def section(title, right=None, top=18):
    w = QWidget()
    h = QHBoxLayout(w)
    h.setContentsMargins(0, top, 0, 2)
    h.addWidget(label(title, 21, TEXT, HEAVY))
    if right:
        h.addSpacing(6)
        h.addWidget(label(right, 14, MUTED), 0, Qt.AlignmentFlag.AlignBottom)
    h.addStretch(1)
    return w, h


class Pill(QAbstractButton):
    def __init__(self, text, checked=False, parent=None):
        super().__init__(parent)
        self.setText(text)
        self.setCheckable(True)
        self.setChecked(checked)
        self.setFixedHeight(34)
        self.setFixedWidth(int(QFontMetricsF(font(13.5, BOLD)).horizontalAdvance(text) + 30))
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def enterEvent(self, e):
        self.update()

    def leaveEvent(self, e):
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(.5, .5, -.5, -.5)
        on = self.isChecked()
        p.setPen(Qt.PenStyle.NoPen if on else QColor(255, 255, 255, 40))
        p.setBrush(QColor('#f3f3f6') if on else QColor(255, 255, 255, 22 if self.underMouse() else 0))
        p.drawRoundedRect(r, 17, 17)
        p.setPen(QColor('#0a0a0e') if on else QColor(TEXT))
        p.setFont(font(13.5, BOLD))
        p.drawText(r, Qt.AlignmentFlag.AlignCenter, self.text())


def pills(options, current, on_pick):
    w = QWidget()
    h = QHBoxLayout(w)
    h.setContentsMargins(0, 0, 0, 0)
    h.setSpacing(8)
    btns = []
    for key, text in options:
        b = Pill(text, key == current)
        btns.append(b)

        def pick(_=False, key=key, b=b):
            for o in btns:
                o.setChecked(o is b)
            on_pick(key)
        b.clicked.connect(pick)
        h.addWidget(b)
    h.addStretch(1)
    return w


class ImageBox(QWidget):
    """Rounded image painted from a resolver (so it refreshes when the download lands)."""

    def __init__(self, fn, w, h, title='', icon='film', radius=12):
        super().__init__()
        self.fn, self.title, self.icon, self.radius = fn, title, icon, radius
        self.setFixedSize(w, h)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect())
        p.setClipPath(rounded(r, self.radius))
        pm = self.fn()
        if pm:
            cover(p, pm, r, self, align_top=r.height() > r.width())
        else:
            placeholder(p, r, self.title, self.icon)


class Hero(QWidget):
    """Backdrop that fades into the page, with content laid over it."""

    def __init__(self, fn, min_h=440):
        super().__init__()
        self.fn = fn
        self.setMinimumHeight(min_h)

    def paintEvent(self, e):
        p = QPainter(self)
        r = QRectF(self.rect())
        p.fillRect(r, QColor(BG))
        pm = self.fn()
        if pm:
            p.setOpacity(.62)
            cover(p, pm, r, self)
            p.setOpacity(1)
        g = QLinearGradient(0, 0, r.width(), 0)
        g.setColorAt(0, QColor(10, 10, 14, 245))
        g.setColorAt(.45, QColor(10, 10, 14, 150))
        g.setColorAt(1, QColor(10, 10, 14, 30))
        p.fillRect(r, g)
        g = QLinearGradient(0, r.height() * .45, 0, r.height())
        g.setColorAt(0, QColor(10, 10, 14, 0))
        g.setColorAt(1, QColor(BG))
        p.fillRect(r, g)


class EpisodeRow(QWidget):
    def __init__(self, browser, item, on_click, on_menu):
        super().__init__()
        self.b, self.item, self.on_click, self.on_menu = browser, item, on_click, on_menu
        self.setFixedHeight(150)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.hover = False

    def enterEvent(self, e):
        self.hover = True
        self.update()

    def leaveEvent(self, e):
        self.hover = False
        self.update()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.on_click()

    def contextMenuEvent(self, e):
        self.on_menu(e.globalPos())

    def paintEvent(self, e):
        b, it = self.b, self.item
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        r = QRectF(self.rect())
        if self.hover:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(255, 255, 255, 13))
            p.drawRoundedRect(r, 14, 14)
        ir = QRectF(14, 14, 216, 122)
        p.save()
        p.setClipPath(rounded(ir, 10))
        pm = b.episode_pixmap(it)
        if pm:
            cover(p, pm, ir, self)
        else:
            placeholder(p, ir, it.title, 'tv')
        if self.hover:
            p.fillRect(ir, QColor(0, 0, 0, 80))
            c = ir.center()
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(255, 255, 255, 235))
            p.drawEllipse(c, 20, 20)
            draw_icon(p, 'play', QRectF(c.x() - 9, c.y() - 9, 18, 18), '#0a0a0e')
        frac = b.store.fraction(it)
        watched = b.store.watched(it)
        if 0 < frac < 1 and not watched:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(255, 255, 255, 80))
            p.drawRect(QRectF(ir.x(), ir.bottom() - 4, ir.width(), 4))
            p.setBrush(QColor(ACCENT))
            p.drawRect(QRectF(ir.x(), ir.bottom() - 4, ir.width() * frac, 4))
        p.restore()
        if watched:
            br = QRectF(ir.right() - 30, ir.y() + 6, 24, 24)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(ACCENT))
            p.drawEllipse(br)
            draw_icon(p, 'check', br.adjusted(5, 5, -5, -5), '#ffffff')
        em = b.episode_meta(it)
        x = ir.right() + 22
        tw = r.width() - x - 20
        dur = b.store.duration(it)
        rtext = fmt_dur(dur)
        if 0 < frac < 1 and not watched and dur:
            rtext = f'{fmt_dur(dur * (1 - frac))} left'
        f = font(13)
        p.setFont(f)
        p.setPen(QColor(MUTED))
        rw = QFontMetricsF(f).horizontalAdvance(rtext) + 4
        p.drawText(QRectF(r.width() - rw - 20, 18, rw, 22), Qt.AlignmentFlag.AlignVCenter, rtext)
        num = f'{it.episode}' + (f'–{it.episode_end}' if it.episode_end else '')
        f = font(16, BOLD)
        p.setFont(f)
        p.setPen(QColor(MUTED))
        nw = QFontMetricsF(f).horizontalAdvance(num) + 12
        p.drawText(QRectF(x, 18, nw, 22), Qt.AlignmentFlag.AlignVCenter, num)
        p.setPen(QColor(TEXT))
        name = em.get('name') or it.ep_name
        p.drawText(QRectF(x + nw, 18, tw - nw - rw - 10, 22), Qt.AlignmentFlag.AlignVCenter,
                   QFontMetricsF(f).elidedText(name, Qt.TextElideMode.ElideRight, tw - nw - rw - 10))
        meta = [m for m in (em.get('aired', ''), it.quality, fmt_size(it.size), b.dl_short(it)) if m]
        p.setFont(font(12.5))
        p.setPen(QColor(MUTED))
        p.drawText(QRectF(x, 44, tw, 18), Qt.AlignmentFlag.AlignVCenter, '  ·  '.join(meta))
        ov = em.get('overview', '')
        if ov:
            p.setFont(font(13.5))
            p.setPen(QColor('#b9b9c4'))
            p.drawText(QRectF(x, 68, tw, 60), Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap, ov)


class NavButton(QAbstractButton):
    def __init__(self, icon, text):
        super().__init__()
        self.icon_name = icon
        self.setText(text)
        self.count = ''
        self.setCheckable(True)
        self.setFixedHeight(42)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def enterEvent(self, e):
        self.update()

    def leaveEvent(self, e):
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect())
        on = self.isChecked()
        if on or self.underMouse():
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(255, 255, 255, 20 if on else 11))
            p.drawRoundedRect(r, 10, 10)
        if on:
            p.setBrush(QColor(ACCENT))
            p.drawRoundedRect(QRectF(0, 11, 3, 20), 1.5, 1.5)
        col = TEXT if on else '#a9a9b6'
        draw_icon(p, self.icon_name, QRectF(16, 11, 20, 20), ACCENT2 if on else col)
        p.setPen(QColor(col))
        p.setFont(font(14.5, BOLD if on else NORMAL))
        p.drawText(QRectF(48, 0, r.width() - 90, r.height()), Qt.AlignmentFlag.AlignVCenter, self.text())
        if self.count:
            p.setPen(QColor(MUTED))
            p.setFont(font(12.5))
            p.drawText(QRectF(0, 0, r.width() - 14, r.height()), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, self.count)


class ScanBar(QWidget):
    def __init__(self):
        super().__init__()
        self.active = False
        self.phase = 0.0
        self.setFixedHeight(4)
        self.timer = QTimer(self, interval=30, timeout=self._step)

    def set_active(self, on):
        self.active = on
        self.timer.start() if on else self.timer.stop()
        self.update()

    def _step(self):
        self.phase = (self.phase + .015) % 1.3
        self.update()

    def paintEvent(self, e):
        if not self.active:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w = self.width()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 255, 255, 25))
        p.drawRoundedRect(QRectF(0, 0, w, 4), 2, 2)
        x = (self.phase - .3) * w
        p.setBrush(QColor(ACCENT))
        p.drawRoundedRect(QRectF(max(0, x), 0, min(w * .3, w - max(0, x), x + w * .3), 4), 2, 2)


# ---------------------------------------------------------------- the browser

class Browser(QWidget):
    play = pyqtSignal(object, object)  # item, start (None = resume)

    def __init__(self, main):
        super().__init__()
        self.main = main
        self.store, self.images, self.meta = main.store, main.images, main.meta
        self.lib = main.lib
        self.sort = {'movies': 'added', 'shows': 'added'}
        self._coll_cache = None
        self.account_rows = []
        self.shares_rows = []
        self.season = {}
        self.history = []
        self.current = ('home', None)
        self.selecting = False            # "Select to download" mode on Movies / TV Shows
        self.selected = {}                # card key -> [items]
        self._page_entries = []           # (key, items) of the selectable cards on screen
        self._dl_buttons = []
        self._dl_sig = None
        self._sid_map = {}

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # sidebar --------------------------------------------------------
        side = QFrame()
        side.setFixedWidth(236)
        side.setStyleSheet(f'QFrame{{background:#0e0e13;border-right:1px solid #1b1b23}}')
        sv = QVBoxLayout(side)
        sv.setContentsMargins(14, 20, 14, 16)
        sv.setSpacing(4)
        logo = QHBoxLayout()
        logo.setContentsMargins(8, 0, 0, 18)
        ic = QLabel()
        pm = app_icon(64)
        pm.setDevicePixelRatio(2)
        ic.setPixmap(pm)
        ic.setStyleSheet('background:transparent;border:none')
        logo.addWidget(ic)
        logo.addSpacing(8)
        name = label('Reel', 22, TEXT, HEAVY)
        name.setStyleSheet('color:#f3f3f6;background:transparent;border:none')
        logo.addWidget(name)
        logo.addStretch(1)
        sv.addLayout(logo)
        self.nav = {}
        for key, icon, text in (('home', 'home', 'Home'), ('discover', 'sparkles', 'Discover'),
                                ('movies', 'film', 'Movies'), ('shows', 'tv', 'TV Shows'),
                                ('downloads', 'download', 'Downloads')):
            b = NavButton(icon, text)
            b.clicked.connect(lambda _=False, k=key: self.go(k))
            b.setStyleSheet('border:none')
            sv.addWidget(b)
            self.nav[key] = b
        sv.addStretch(1)
        self.scan_status = label('', 12.5, MUTED, wrap=True)
        self.scan_status.setStyleSheet(f'color:{MUTED};background:transparent;border:none')
        self.scan_bar = ScanBar()
        self.scan_bar.setStyleSheet('border:none')
        sv.addWidget(self.scan_status)
        self.cloud_status = label('', 12, '#6f8fdc', wrap=True)
        self.cloud_status.setStyleSheet('color:#6f8fdc;background:transparent;border:none')
        self.cloud_status.hide()
        sv.addWidget(self.cloud_status)
        sv.addSpacing(6)
        sv.addWidget(self.scan_bar)
        sv.addSpacing(8)
        self.btn_account = PillButton('Owner', 'users', 'ghost', h=36, px=13)
        self.btn_account.clicked.connect(self.account_tapped)
        sv.addWidget(self.btn_account)
        sv.addSpacing(6)
        srow = QHBoxLayout()
        srow.setSpacing(6)
        self.btn_scan = PillButton('Scan computer', 'refresh', 'primary', h=40, px=14)
        self.btn_scan.clicked.connect(self.main.start_scan)
        srow.addWidget(self.btn_scan)
        self.btn_settings = IconButton('folder', 40, 20, tip='Library settings')
        self.btn_settings.clicked.connect(self.main.open_settings)
        srow.addWidget(self.btn_settings)
        srow.addStretch(1)
        sv.addLayout(srow)
        root.addWidget(side)

        # content --------------------------------------------------------
        content = QWidget()
        cv = QVBoxLayout(content)
        cv.setContentsMargins(0, 0, 0, 0)
        cv.setSpacing(0)
        top = QHBoxLayout()
        top.setContentsMargins(40, 18, 34, 10)
        self.btn_back = IconButton('chevron-left', 38, 22)
        self.btn_back.clicked.connect(self.back)
        top.addWidget(self.btn_back)
        top.addSpacing(6)
        self.search = QLineEdit()
        self.search.setPlaceholderText('Search movies, shows, episodes')
        self.search.addAction(QAction(qicon('search', MUTED, 18), '', self.search), QLineEdit.ActionPosition.LeadingPosition)
        self.search.setFixedSize(380, 40)
        self.search.setFont(font(14))
        self.search.setClearButtonEnabled(True)
        self.search.setStyleSheet(f'QLineEdit{{background:{SURFACE};border:1px solid {BORDER};border-radius:20px;'
                                  f'padding:0 12px 0 6px;color:{TEXT};selection-background-color:{ACCENT}}}'
                                  f'QLineEdit:focus{{border:1px solid #3a3a48;background:{SURFACE2}}}')
        self.search_timer = QTimer(self, singleShot=True, interval=180, timeout=self._do_search)
        self.search.textChanged.connect(lambda: self.search_timer.start())
        top.addWidget(self.search)
        top.addStretch(1)
        self.btn_open = PillButton('Open file', 'file', 'ghost', h=38, px=13.5)
        self.btn_open.clicked.connect(self.main.open_file_dialog)
        top.addWidget(self.btn_open)
        cv.addLayout(top)
        self.pages = QStackedWidget()
        self.page = Page()
        self.pages.addWidget(self.page)
        cv.addWidget(self.pages, 1)
        # selection bar (bottom) -------------------------------------------
        self.sel_bar = QFrame()
        self.sel_bar.setObjectName('selbar')
        self.sel_bar.setStyleSheet(f'#selbar{{background:#15151c;border-top:1px solid {BORDER}}}')
        sb = QHBoxLayout(self.sel_bar)
        sb.setContentsMargins(40, 12, 34, 12)
        sb.setSpacing(10)
        self.sel_label = label('', 14.5, TEXT, BOLD)
        sb.addWidget(self.sel_label)
        sb.addStretch(1)
        b_all = PillButton('Select all', None, 'ghost', h=40, px=14)
        b_all.clicked.connect(self.select_all)
        sb.addWidget(b_all)
        b_no = PillButton('Cancel', None, 'ghost', h=40, px=14)
        b_no.clicked.connect(self.stop_selecting)
        sb.addWidget(b_no)
        self.sel_go = PillButton('Download', 'download', 'primary', h=40, px=14)
        self.sel_go.clicked.connect(self.download_selected)
        sb.addWidget(self.sel_go)
        self.sel_bar.hide()
        cv.addWidget(self.sel_bar)
        root.addWidget(content, 1)
        self.dl_timer = QTimer(self, singleShot=True, interval=400, timeout=self._dl_refresh)

        self.repaint_timer = QTimer(self, singleShot=True, interval=120, timeout=self._repaint_cards)
        self.images.ready.connect(lambda _: self.repaint_timer.start())
        self.meta_timer = QTimer(self, singleShot=True, interval=1500, timeout=lambda: self.render(keep_scroll=True))
        self.meta.ready.connect(self._meta_ready)
        self.set_library(self.lib)

    # ------------------------------------------------------------ data helpers
    def movie_meta(self, it):
        return self.meta.movie(it) or {}

    def show_meta(self, show):
        return self.meta.show(show) or {} if show else {}

    def episode_meta(self, it):
        return self.meta.episode(self.show_meta(self.lib.show_of(it)), it)

    def episode_pixmap(self, it):
        em = self.episode_meta(it)
        pm = self.images.remote(em.get('thumb')) if em.get('thumb') else None
        if pm is None:
            pm = self.images.frame(it)
        if pm is None:
            pm = self.images.remote(self.show_meta(self.lib.show_of(it)).get('background'))
        return pm

    def is_movie(self, it):
        if it.kind != 'movie':
            return False
        if it.release and it.year:
            return True
        mm = self.meta.movie(it)  # weak name: only trust an exact online match
        if not mm:
            return False
        my = int(str(mm.get('year') or '0')[:4] or 0)
        return norm_key(mm.get('name') or '') == norm_key(it.title) and (not it.year or abs(my - it.year) <= 1)

    def movies(self):
        return [m for m in self.lib.movies if self.is_movie(m)]

    def others(self):
        return [m for m in self.lib.movies if not self.is_movie(m)] + list(self.lib.videos)

    def titles(self, it):
        if it.kind == 'episode':
            show = self.lib.show_of(it)
            sm = self.show_meta(show)
            em = self.meta.episode(sm, it)
            return sm.get('name') or it.title, f'{it.code}  ·  {em.get("name") or it.ep_name}'
        mm = self.movie_meta(it) if self.is_movie(it) else {}
        bits = [str(it.year) if it.year else '', it.quality]
        return mm.get('name') or it.title, '  ·  '.join(b for b in bits if b)

    # ------------------------------------------------------------ collections
    def movie_title(self, it):
        return self.movie_meta(it).get('name') or it.title

    def collections(self):
        """Group movies that share a name / are sequels. Returns ({root: [items by year]}, item.key->root).
        Near-linear (bucketed) and cached per library version so it's cheap to call every render."""
        import re
        from collections import defaultdict
        sig = (id(self.lib), len(self.lib.items))
        if self._coll_cache and self._coll_cache[0] == sig:
            return self._coll_cache[1], self._coll_cache[2]
        from library import collection_key, same_series
        movies = self.movies()
        title = {m.key: self.movie_title(m) for m in movies}
        clean = {m.key: re.sub(r'[^a-z0-9]+', ' ', title[m.key].lower()).strip() for m in movies}
        base = {m.key: collection_key(title[m.key]) for m in movies}
        parent = {m.key: m.key for m in movies}

        def find(k):
            while parent[k] != k:
                parent[k] = parent[parent[k]]
                k = parent[k]
            return k

        def union(keys):
            for k in keys[1:]:
                parent[find(k)] = find(keys[0])

        buckets = defaultdict(list)                     # 1. shared base key (Iron Man / Iron Man 2)
        for m in movies:
            if len(base[m.key]) >= 3:
                buckets[base[m.key]].append(m.key)
        for ks in buckets.values():
            union(ks)
        stems = defaultdict(list)                       # 2. same pre-colon stem (Avengers: …, Thor: …)
        for m in movies:
            t = title[m.key].lower()
            i = t.find(': ')
            s = re.sub(r'[^a-z0-9]+', ' ', t[:i]).strip() if i > 0 else ''
            if len(s.replace(' ', '')) >= 4:
                stems[s].append(m.key)
        for ks in stems.values():
            union(ks)
        owned = {}                                      # 3. prefix sequels (The Matrix → …Reloaded)
        for m in movies:
            owned.setdefault(clean[m.key], m.key)
        for m in movies:                                # look up whether a shorter owned title is this one's base
            toks = clean[m.key].split(' ')
            for j in range(len(toks) - 1, 0, -1):
                base_title = ' '.join(toks[:j])
                root_key = owned.get(base_title)
                if root_key and root_key != m.key and same_series(base_title, clean[m.key]):
                    parent[find(m.key)] = find(root_key)
                    break
        groups = defaultdict(list)
        for m in movies:
            groups[find(m.key)].append(m)
        colls, member = {}, {}
        for root, items in groups.items():
            if len(items) >= 2:
                items.sort(key=lambda m: (m.year or 9999, title[m.key].lower()))
                colls[root] = items
                for m in items:
                    member[m.key] = root
        self._coll_cache = (sig, colls, member)
        return colls, member

    def collection_name(self, items):
        from library import collection_label
        return collection_label([self.movie_title(m) for m in items]) or self.movie_title(items[0])

    def collection_poster(self, items):
        for m in items:                    # the earliest film with artwork represents the set
            pm = self.images.remote(self.movie_meta(m).get('poster')) if self.movie_meta(m).get('poster') else None
            if pm:
                return pm
        return None

    # ------------------------------------------------------------ card resolvers
    def movie_card(self, it):
        def resolve():
            mm = self.movie_meta(it)
            pm = self.images.remote(mm.get('poster')) if mm.get('poster') else None
            sub = '  ·  '.join(x for x in (str(it.year or ''), fmt_dur(self.store.duration(it)) or mm.get('runtime', '')) if x)
            return self._decorate({'title': mm.get('name') or it.title, 'sub': sub, 'pix': pm,
                                   'progress': self.store.fraction(it), 'watched': self.store.watched(it),
                                   'icon': 'film'}, it.key, [it])
        self._page_entries.append((it.key, [it]))
        return Card('poster', resolve, lambda: self.card_click(it.key, [it], lambda: self.open_movie(it)),
                    lambda pos: self.item_menu(it, pos))

    def collection_card(self, root, items):
        def resolve():
            unwatched = sum(1 for m in items if not self.store.watched(m))
            return self._decorate({'title': self.collection_name(items), 'sub': f'{len(items)} movies',
                                   'pix': self.collection_poster(items), 'icon': 'film',
                                   'count': unwatched if 0 < unwatched < len(items) else 0,
                                   'watched': unwatched == 0, 'stack': True}, f'coll:{root}', items)
        self._page_entries.append((f'coll:{root}', items))
        return Card('poster', resolve, lambda: self.card_click(f'coll:{root}', items, lambda: self.go('collection', root)),
                    lambda pos: self.collection_menu(items, pos))

    def show_card(self, show):
        def resolve():
            sm = self.show_meta(show)
            pm = self.images.remote(sm.get('poster')) if sm.get('poster') else None
            unwatched = sum(1 for e in show.episodes if not self.store.watched(e))
            n = len(show.seasons)
            sub = f'{n} seasons' if n > 1 else f'{len(show.episodes)} episode' + ('s' if len(show.episodes) != 1 else '')
            return self._decorate({'title': sm.get('name') or show.name, 'sub': sub, 'pix': pm, 'icon': 'tv',
                                   'count': unwatched if unwatched and unwatched != len(show.episodes) else 0,
                                   'watched': unwatched == 0}, show.key, show.episodes)
        self._page_entries.append((show.key, show.episodes))
        return Card('poster', resolve, lambda: self.card_click(show.key, show.episodes, lambda: self.open_show(show)),
                    lambda pos: self.show_menu(show, pos))

    def wide_card(self, it, mode=''):
        def resolve():
            if it.kind == 'episode':
                show = self.lib.show_of(it)
                title, sub = self.titles(it)
                pm = self.episode_pixmap(it)
                badge = 'NEXT EPISODE' if mode == 'next' else ''
                sub = sub.replace('  ·  ', ' · ')
            else:
                title, _ = self.titles(it)
                mm = self.movie_meta(it) if self.is_movie(it) else {}
                pm = self.images.remote(mm.get('background')) if mm.get('background') else None
                pm = pm or self.images.frame(it)
                badge = ''
                d = self.store.duration(it)
                sub = '  ·  '.join(x for x in (str(it.year or ''), fmt_dur(d), fmt_size(it.size) if not self.is_movie(it) else '') if x)
            prog = self.store.fraction(it)
            d = self.store.duration(it)
            if mode == 'resume' and d and 0 < prog < 1:
                sub = f'{fmt_dur(d * (1 - prog))} left  ·  ' + sub
            return {'title': title, 'sub': sub, 'pix': pm, 'progress': prog, 'badge': badge,
                    'watched': self.store.watched(it) and mode != 'next', 'icon': 'tv' if it.kind == 'episode' else 'film'}
        click = (lambda: self.play.emit(it, None)) if mode or it.kind == 'episode' or not self.is_movie(it) else (lambda: self.open_movie(it))
        return Card('wide', resolve, click, lambda pos: self.item_menu(it, pos))

    def _repaint_cards(self):
        w = self.pages.currentWidget()
        if w:
            for c in w.findChildren(QWidget):
                if isinstance(c, (Card, EpisodeRow, ImageBox, Hero)):
                    c.update()

    def _meta_ready(self, key):
        self.repaint_timer.start()
        if key.startswith('movie:'):     # a title/poster resolved → grouping may change
            self._coll_cache = None
        if self.current[0] in ('movies', 'collection', 'home', 'search'):
            self.meta_timer.start()

    # ------------------------------------------------------------ navigation
    def set_library(self, lib):
        self.lib = lib
        self._coll_cache = None
        self.nav['movies'].count = str(len(self.movies())) if lib.items else ''
        self.nav['shows'].count = str(len(lib.shows)) if lib.items else ''
        for b in self.nav.values():
            b.update()
        # warm metadata for everything so posters fill in
        for m in lib.movies:
            self.meta.movie(m)
        for s in lib.shows.values():
            self.meta.show(s)
        self.render(keep_scroll=True)

    def go(self, page, arg=None, push=True):
        if push and self.current != (page, arg):
            self.history.append(self.current)
            self.history = self.history[-30:]
        self.current = (page, arg)
        if self.selecting and page not in ('movies', 'shows', 'collection', 'search'):
            self.stop_selecting(render=False)
        if page != 'search' and self.search.text():
            self.search.blockSignals(True)
            self.search.clear()
            self.search.blockSignals(False)
        self.render()

    def back(self):
        if self.history:
            self.current = self.history.pop()
            self.render()

    def refresh(self):
        self.set_library(self.lib)

    def render(self, keep_scroll=False):
        page, arg = self.current
        for k, b in self.nav.items():
            b.setChecked(k == page or (k == 'shows' and page == 'show')
                         or (k == 'movies' and page in ('movie', 'collection'))
                         or (k == 'discover' and page == 'reco'))
        self.btn_back.setVisible(bool(self.history) and page not in ('home',))
        self._dl_buttons = []
        self._page_entries = []
        self.nav['downloads'].setVisible(bool(self.main.cloud.on or self.main.downloads.queue))
        self.nav['movies'].count = str(len(self.movies())) if self.lib.items else ''
        acct = self.main.account()
        self.btn_account.setText(acct.get('name') or 'Owner')
        {'home': self.render_home, 'discover': self.render_discover, 'movies': self.render_movies,
         'shows': self.render_shows, 'show': self.render_show, 'movie': self.render_movie,
         'collection': self.render_collection, 'reco': self.render_reco, 'accounts': self.render_accounts,
         'downloads': self.render_downloads, 'search': self.render_search}[page](arg, keep_scroll)

    def _do_search(self):
        q = self.search.text().strip()
        if q:
            if self.current[0] != 'search':
                self.history.append(self.current)
            self.current = ('search', q)
            self.render()
        elif self.current[0] == 'search':
            self.back()

    # ------------------------------------------------------------ pages
    def empty_state(self, v, scanning):
        box = QWidget()
        b = QVBoxLayout(box)
        b.setContentsMargins(0, 70, 0, 0)
        b.setSpacing(12)
        ic = QLabel()
        pm = app_icon(176)
        pm.setDevicePixelRatio(2)
        ic.setPixmap(pm)
        ic.setStyleSheet('background:transparent')
        b.addWidget(ic, 0, Qt.AlignmentFlag.AlignHCenter)
        b.addSpacing(8)
        b.addWidget(label('Scanning your computer…' if scanning else 'Let’s find your movies & shows', 30, TEXT, HEAVY),
                    0, Qt.AlignmentFlag.AlignHCenter)
        t = label('Reel looks through every drive for video files, sorts them into Movies and TV Shows, '
                  'and grabs posters, plots and episode names automatically.', 15, MUTED, wrap=True, maxw=520)
        t.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        b.addWidget(t, 0, Qt.AlignmentFlag.AlignHCenter)
        b.addSpacing(10)
        if not scanning:
            btn = PillButton('Scan my computer', 'refresh', 'primary', h=50, px=16)
            btn.clicked.connect(self.main.start_scan)
            b.addWidget(btn, 0, Qt.AlignmentFlag.AlignHCenter)
        v.addWidget(box)
        v.addStretch(1)

    def render_home(self, _, keep_scroll=False):
        v = self.page.fresh((0, 0, 0, 48), keep_scroll)
        self.pages.setCurrentWidget(self.page)
        if not self.lib.items:
            inner = QWidget()
            iv = QVBoxLayout(inner)
            iv.setContentsMargins(40, 0, 40, 0)
            self.empty_state(iv, self.main.scanning)
            v.addWidget(inner)
            return
        cw = self.store.continue_watching(self.lib, 12)
        # hero: what you were watching, else the newest movie/show that has artwork
        feat, mode = None, ''
        for it, md in cw + [(i, '') for i in self.lib.recent(60)]:
            art = self.show_meta(self.lib.show_of(it)) if it.kind == 'episode' else                 self.movie_meta(it) if self.is_movie(it) else {}
            if art.get('background'):
                feat, mode = it, md
                if it.kind == 'episode' and not md:
                    feat = self.store.up_next(self.lib.show_of(it))
                break
        if feat:
            v.addWidget(self.feature_hero(feat, mode))
        else:
            v.addSpacing(10)
        inner = QWidget()
        iv = QVBoxLayout(inner)
        iv.setContentsMargins(40, 0, 40, 0)
        iv.setSpacing(12)
        # Home stays focused on what you're watching. Everything else lives under Movies / TV Shows.
        if cw:
            iv.addWidget(section('Continue Watching', top=4)[0])
            iv.addWidget(Grid([self.wide_card(it, md) for it, md in cw], 300, max_rows=2))
        else:
            movies = sorted(self.movies(), key=lambda m: -m.added)
            shows = sorted(self.lib.shows.values(), key=lambda s: -s.added)
            if movies:
                iv.addWidget(section('Recently Added Movies')[0])
                iv.addWidget(Grid([self.movie_card(m) for m in movies[:12]], 170, max_rows=1))
            if shows:
                iv.addWidget(section('Recently Added TV')[0])
                iv.addWidget(Grid([self.show_card(s) for s in shows[:12]], 170, max_rows=1))
        v.addWidget(inner)
        v.addStretch(1)

    def feature_hero(self, it, mode):
        show = self.lib.show_of(it)
        if show:
            sm = self.show_meta(show)
            bg = lambda: self.images.remote(sm.get('background')) or self.episode_pixmap(it)
            title, sub = sm.get('name') or show.name, ''
            desc = self.meta.episode(sm, it).get('overview') or sm.get('description', '')
        else:
            mm = self.movie_meta(it)
            bg = lambda: (self.images.remote(mm.get('background')) if mm.get('background') else None) or self.images.frame(it)
            title, desc = mm.get('name') or it.title, mm.get('description', '')
        hero = Hero(bg, 420)
        h = QVBoxLayout(hero)
        h.setContentsMargins(40, 40, 40, 34)
        h.addStretch(1)
        kicker = 'CONTINUE WATCHING' if mode == 'resume' else 'UP NEXT' if mode == 'next' else 'RECENTLY ADDED'
        h.addWidget(label(kicker, 12, ACCENT2, HEAVY))
        h.addWidget(label(title, 44, TEXT, HEAVY))
        if show:
            _, s = self.titles(it)
            h.addWidget(label(s, 16, '#d5d5de', BOLD))
        if desc:
            d = label(desc, 15, '#c4c4ce', wrap=True, maxw=640)
            h.addWidget(d)
        h.addSpacing(10)
        row = QHBoxLayout()
        row.setSpacing(10)
        pos = self.store.resume_pos(it)
        b = PillButton(f'Resume  {fmt_time(pos)}' if pos > 15 else 'Play', 'play', 'light', h=46, px=15)
        b.clicked.connect(lambda: self.play.emit(it, None))
        row.addWidget(b)
        info = PillButton('Details', None, 'ghost', h=46, px=15)
        info.clicked.connect(lambda: self.open_show(show) if show else self.open_movie(it))
        row.addWidget(info)
        row.addStretch(1)
        h.addLayout(row)
        return hero

    def render_movies(self, _, keep_scroll=False):
        v = self.page.fresh(keep_scroll=keep_scroll)
        self.pages.setCurrentWidget(self.page)
        colls, member = self.collections()
        singles = [m for m in self.movies() if m.key not in member]
        total = len(singles) + sum(len(it) for it in colls.values())
        # one "entry" per standalone movie or per collection, so sequels fold into one tile
        entries = [('movie', m) for m in singles] + [('coll', root, items) for root, items in colls.items()]
        w, h = section('Movies', f'{total}', top=6)
        self._select_button(h)
        v.addWidget(w)
        mode = self.sort['movies']
        v.addWidget(pills([('added', 'Recently added'), ('az', 'A–Z'), ('year', 'Year'), ('rating', 'Rating'),
                           ('unwatched', 'Unwatched')], mode,
                          lambda k: (self.sort.__setitem__('movies', k), self.render())))

        def added(e):
            return max(m.added for m in (e[2] if e[0] == 'coll' else [e[1]]))

        def year(e):
            return max((m.year or 0) for m in (e[2] if e[0] == 'coll' else [e[1]]))

        def rating(e):
            return max(float(self.movie_meta(m).get('rating') or 0) for m in (e[2] if e[0] == 'coll' else [e[1]]))

        def az(e):
            t = (self.collection_name(e[2]) if e[0] == 'coll' else self.movie_title(e[1])).lower()
            return t[4:] if t.startswith('the ') else t
        if mode == 'added':
            entries.sort(key=lambda e: -added(e))
        elif mode == 'year':
            entries.sort(key=lambda e: -year(e))
        elif mode == 'rating':
            entries.sort(key=lambda e: -rating(e))
        elif mode == 'unwatched':
            entries = [e for e in entries if any(not self.store.watched(m) for m in (e[2] if e[0] == 'coll' else [e[1]]))]
            entries.sort(key=az)
        else:
            entries.sort(key=az)
        if not entries:
            v.addWidget(label('No movies found yet. Press “Scan computer” to look again.', 15, MUTED))
        v.addSpacing(6)
        cards = [self.collection_card(e[1], e[2]) if e[0] == 'coll' else self.movie_card(e[1]) for e in entries]
        v.addWidget(Grid(cards, 170))
        v.addStretch(1)

    def render_collection(self, root, keep_scroll=False):
        colls, _ = self.collections()
        items = colls.get(root) or next((it for it in colls.values() if any(m.key == root for m in it)), None)
        if not items:
            return self.go('movies', push=False)
        v = self.page.fresh((0, 0, 0, 48), keep_scroll)
        self.pages.setCurrentWidget(self.page)
        name = self.collection_name(items)
        hero = Hero(lambda: self.collection_poster_bg(items), 360)
        hb = QVBoxLayout(hero)
        hb.setContentsMargins(40, 40, 40, 30)
        hb.addStretch(1)
        hb.addWidget(label('COLLECTION', 12, ACCENT2, HEAVY))
        hb.addWidget(label(name, 44, TEXT, HEAVY, wrap=True, maxw=820))
        watched = sum(1 for m in items if self.store.watched(m))
        years = [m.year for m in items if m.year]
        span = f'{min(years)}–{max(years)}' if len(set(years)) > 1 else (str(years[0]) if years else '')
        hb.addWidget(label('   ·   '.join(x for x in (f'{len(items)} movies', span,
                                                      f'{watched}/{len(items)} watched' if watched else '') if x), 15, '#d0d0da', BOLD))
        hb.addSpacing(8)
        nxt = next((m for m in items if not self.store.watched(m)), items[0])
        row = QHBoxLayout()
        row.setSpacing(10)
        b = PillButton(f'Play {self.movie_title(nxt)}', 'play', 'light', h=46, px=15)
        b.clicked.connect(lambda: self.play.emit(nxt, None))
        row.addWidget(b)
        self._add_download_button(row, items, 'Download all', h=46)
        row.addStretch(1)
        hb.addLayout(row)
        v.addWidget(hero)
        inner = QWidget()
        iv = QVBoxLayout(inner)
        iv.setContentsMargins(40, 0, 40, 0)
        iv.addWidget(Grid([self.movie_card(m) for m in items], 170))
        v.addWidget(inner)
        v.addStretch(1)

    def collection_poster_bg(self, items):
        for m in items:
            bg = self.movie_meta(m).get('background')
            if bg:
                pm = self.images.remote(bg)
                if pm:
                    return pm
        return self.images.frame(items[0])

    def collection_menu(self, items, pos):
        m = QMenu(self)
        m.setStyleSheet(MENU_CSS)
        m.setFont(font(13.5))
        nxt = next((x for x in items if not self.store.watched(x)), items[0])
        m.addAction(f'Play {self.movie_title(nxt)}', lambda: self.play.emit(nxt, None))
        m.addAction('Mark all watched', lambda: ([self.store.set_watched(x, True) for x in items], self.render(keep_scroll=True)))
        m.addAction('Mark all unwatched', lambda: ([self.store.set_watched(x, False) for x in items], self.render(keep_scroll=True)))
        if any(x.remote for x in items):
            m.addSeparator()
            m.addAction('Download all to this computer', lambda: self.main.download(items))
        m.exec(pos)

    def render_shows(self, _, keep_scroll=False):
        v = self.page.fresh(keep_scroll=keep_scroll)
        self.pages.setCurrentWidget(self.page)
        shows = list(self.lib.shows.values())
        w, h = section('TV Shows', f'{len(shows)}', top=6)
        self._select_button(h)
        v.addWidget(w)
        mode = self.sort['shows']
        v.addWidget(pills([('added', 'Recently added'), ('az', 'A–Z'), ('unwatched', 'Unwatched')], mode,
                          lambda k: (self.sort.__setitem__('shows', k), self.render())))
        if mode == 'added':
            shows.sort(key=lambda s: -s.added)
        elif mode == 'unwatched':
            shows = [s for s in shows if any(not self.store.watched(e) for e in s.episodes)]
        if not shows:
            v.addWidget(label('No TV shows found yet. Episodes named like “Show.S01E02” are grouped automatically.', 15, MUTED))
        v.addSpacing(6)
        v.addWidget(Grid([self.show_card(s) for s in shows], 170))
        v.addStretch(1)

    def render_search(self, q, keep_scroll=False):
        v = self.page.fresh(keep_scroll=keep_scroll)
        self.pages.setCurrentWidget(self.page)
        ql = q.lower()

        def hit(*texts):
            return any(ql in (t or '').lower() for t in texts)
        movies = [m for m in self.movies() if hit(m.title, self.movie_meta(m).get('name'), str(m.year))]
        shows = [s for s in self.lib.shows.values() if hit(s.name, self.show_meta(s).get('name'))]
        eps = [e for e in self.lib.items if e.kind == 'episode' and hit(e.ep_title, self.episode_meta(e).get('name'))]
        v.addWidget(section(f'Results for “{q}”', top=6)[0])
        if not (movies or shows or eps):
            v.addWidget(label('Nothing matches. Try a different spelling, or scan again.', 15, MUTED))
        if shows:
            v.addWidget(section('TV Shows', str(len(shows)))[0])
            v.addWidget(Grid([self.show_card(s) for s in shows], 170))
        if movies:
            v.addWidget(section('Movies', str(len(movies)))[0])
            v.addWidget(Grid([self.movie_card(m) for m in movies], 170))
        if eps:
            v.addWidget(section('Episodes', str(len(eps)))[0])
            v.addWidget(Grid([self.wide_card(e) for e in eps[:60]], 280))
        v.addStretch(1)

    # ------------------------------------------------------------ Discover (recommendations + watchlist)
    def owned_keys(self):
        keys = {norm_key(self.movie_title(m)) for m in self.movies()}
        keys |= {norm_key(self.show_meta(s).get('name') or s.name) for s in self.lib.shows.values()}
        return keys

    def taste(self):
        """Genre weights from what you own and (more so) what you've watched."""
        from collections import defaultdict
        w = defaultdict(float)
        for m in self.movies():
            for g in self.movie_meta(m).get('genres', []):
                w[g] += 2.5 if self.store.watched(m) else 1.0
        for s in self.lib.shows.values():
            hot = any(self.store.watched(e) for e in s.episodes)
            for g in self.show_meta(s).get('genres', []):
                w[g] += 2.5 if hot else 1.0
        return w

    def recommend(self, kind, weights, genres, n=24, exclude=()):
        owned = self.owned_keys()
        skip = set(self.store.settings.data.get('reco_hidden', [])) | set(exclude)
        seen, out = set(), []
        pool = list(self.main.catalog.get(kind))          # trending
        for g in genres:
            pool += self.main.catalog.get(kind, g)         # per-genre top
        for c in pool:
            cid = c.get('id')
            if not cid or cid in seen or cid in skip or norm_key(c.get('name', '')) in owned:
                continue
            seen.add(cid)
            score = sum(weights.get(g, 0) for g in c.get('genres', [])) + float(c.get('rating') or 0) * 0.3
            out.append((score, c))
        out.sort(key=lambda sc: -sc[0])
        return [c for _, c in out[:n]]

    def watchlist(self):
        return self.store.settings.data.setdefault('watchlist', [])

    def in_watchlist(self, cid):
        return any(w.get('id') == cid for w in self.watchlist())

    def toggle_watchlist(self, cand):
        wl = self.watchlist()
        cid = cand.get('id')
        if self.in_watchlist(cid):
            wl[:] = [w for w in wl if w.get('id') != cid]
        else:
            wl.insert(0, {k: cand.get(k) for k in ('id', 'kind', 'name', 'year', 'poster', 'background',
                                                   'rating', 'genres', 'description')})
        self.store.settings.save()

    def owned_item(self, cand):
        """If a recommended title is already in your library, return (item_or_show, is_show)."""
        key = norm_key(cand.get('name', ''))
        if cand.get('kind') == 'series':
            for s in self.lib.shows.values():
                if norm_key(self.show_meta(s).get('name') or s.name) == key:
                    return s, True
        else:
            for m in self.movies():
                if norm_key(self.movie_title(m)) == key:
                    return m, False
        return None, False

    def on_catalog_ready(self, key):
        self.repaint_timer.start()
        if self.current[0] in ('discover', 'reco'):
            self.meta_timer.start()

    def reco_card(self, cand):
        def resolve():
            owned_it, _ = self.owned_item(cand)
            sub = '  ·  '.join(x for x in (str(cand.get('year', ''))[:4],
                                           f'★ {cand["rating"]}' if cand.get('rating') else '') if x)
            return {'title': cand.get('name', ''), 'sub': sub,
                    'pix': self.images.remote(cand.get('poster')) if cand.get('poster') else None,
                    'icon': 'tv' if cand.get('kind') == 'series' else 'film',
                    'badge': 'IN LIBRARY' if owned_it else ('WATCHLIST' if self.in_watchlist(cand.get('id')) else '')}
        return Card('poster', resolve, lambda: self.go('reco', cand), lambda pos: self.reco_menu(cand, pos))

    def reco_menu(self, cand, pos):
        m = QMenu(self)
        m.setStyleSheet(MENU_CSS)
        m.setFont(font(13.5))
        owned_it, is_show = self.owned_item(cand)
        if owned_it:
            m.addAction('Play' if not is_show else 'Open',
                        lambda: (self.open_show(owned_it) if is_show else self.play.emit(owned_it, None)))
        inwl = self.in_watchlist(cand.get('id'))
        m.addAction('Remove from watchlist' if inwl else 'Add to watchlist',
                    lambda: (self.toggle_watchlist(cand), self.render(keep_scroll=True)))
        if not owned_it:
            m.addSeparator()
            m.addAction('Not interested',
                        lambda: (self.store.settings.data.setdefault('reco_hidden', []).append(cand.get('id')),
                                 self.store.settings.save(), self.render(keep_scroll=True)))
        m.exec(pos)

    def render_discover(self, _, keep_scroll=False):
        v = self.page.fresh(keep_scroll=keep_scroll)
        self.pages.setCurrentWidget(self.page)
        if not self.main.meta.enabled:
            v.addWidget(label('Discover needs the online lookup turned on (Library settings → '
                              '“Download posters, plots and episode names”).', 15, MUTED))
            v.addStretch(1)
            return
        weights = self.taste()
        top_genres = [g for g, _ in sorted(weights.items(), key=lambda kv: -kv[1])]
        v.addWidget(section('Discover', top=6)[0])
        v.addWidget(label('Suggestions based on what you watch. Add things to your watchlist — '
                          'anything you get later shows up in your library automatically.', 13.5, MUTED))
        v.addSpacing(4)
        if self.shares_rows:
            senders = ', '.join(dict.fromkeys(s.get('from_name', '') for s in self.shares_rows))
            v.addWidget(section('Recommended to You', f'from {senders}' if senders else '')[0])
            v.addWidget(Grid([self.share_card(s) for s in self.shares_rows], 170, max_rows=1))
        wl = self.watchlist()
        if wl:
            w0, h0 = section('Your Watchlist', str(len(wl)))
            v.addWidget(w0)
            v.addWidget(Grid([self.reco_card(c) for c in wl], 170, max_rows=1))
        movies = self.recommend('movie', weights, top_genres[:3], 24)
        if movies:
            v.addWidget(section('Recommended Movies' if top_genres else 'Trending Movies')[0])
            v.addWidget(Grid([self.reco_card(c) for c in movies], 170, max_rows=1 if top_genres else 2))
        shows = self.recommend('series', weights, top_genres[:3], 18)
        if shows:
            v.addWidget(section('Recommended Shows' if top_genres else 'Trending Shows')[0])
            v.addWidget(Grid([self.reco_card(c) for c in shows], 170, max_rows=1))
        for g in top_genres[:3]:
            picks = self.recommend('movie', weights, [g], 18, exclude=[c['id'] for c in movies])
            if len(picks) >= 4:
                v.addWidget(section(f'More {g}')[0])
                v.addWidget(Grid([self.reco_card(c) for c in picks], 170, max_rows=1))
        if not (wl or movies or shows):
            v.addWidget(label('Loading suggestions…' if self.main.meta.enabled else '', 15, MUTED))
        v.addStretch(1)

    def render_reco(self, cand, keep_scroll=False):
        v = self.page.fresh((0, 0, 0, 48), keep_scroll)
        self.pages.setCurrentWidget(self.page)
        full = self.main.catalog.meta(cand.get('kind', 'movie'), cand.get('id', ''))
        desc = full.get('description') or cand.get('description', '')
        cast = full.get('cast') or cand.get('cast', [])
        hero = Hero(lambda: self.images.remote(cand.get('background')) if cand.get('background') else
                    (self.images.remote(cand.get('poster')) if cand.get('poster') else None), 520)
        h = QHBoxLayout(hero)
        h.setContentsMargins(40, 30, 40, 30)
        h.setSpacing(36)
        h.addWidget(ImageBox(lambda: self.images.remote(cand.get('poster')) if cand.get('poster') else None, 250, 375,
                             cand.get('name', ''), 'tv' if cand.get('kind') == 'series' else 'film', 14),
                    0, Qt.AlignmentFlag.AlignVCenter)
        col = QVBoxLayout()
        col.setSpacing(10)
        col.addStretch(1)
        col.addWidget(label(cand.get('name', ''), 42, TEXT, HEAVY, wrap=True, maxw=820))
        bits = [str(cand.get('year', ''))[:4], f'★ {cand["rating"]}' if cand.get('rating') else '',
                ', '.join(cand.get('genres', []))]
        col.addWidget(label('   ·   '.join(b for b in bits if b), 15, '#d0d0da', BOLD))
        col.addSpacing(6)
        row = QHBoxLayout()
        row.setSpacing(10)
        owned_it, is_show = self.owned_item(cand)
        if owned_it:
            tag = label(' IN YOUR LIBRARY ', 11, '#0a0a0e', HEAVY)
            tag.setStyleSheet(f'color:#0a0a0e;background:{ACCENT2};border-radius:5px;padding:3px 8px')
            pb = PillButton('Open' if is_show else 'Play', 'play', 'light', h=48, px=15)
            pb.clicked.connect(lambda: self.open_show(owned_it) if is_show else self.play.emit(owned_it, None))
            row.addWidget(pb)
        inwl = self.in_watchlist(cand.get('id'))
        wb = PillButton('In Watchlist ✓' if inwl else 'Add to Watchlist', 'check' if inwl else 'plus',
                        'ghost' if inwl else 'primary', h=48, px=15)
        wb.clicked.connect(lambda: (self.toggle_watchlist(cand), self.render(keep_scroll=True)))
        row.addWidget(wb)
        if full.get('trailer'):
            tb = PillButton('Trailer', 'play-o', 'ghost', h=48, px=15)
            tb.clicked.connect(lambda: self.open_trailer(full['trailer']))
            row.addWidget(tb)
        rb = PillButton('Recommend', 'users', 'ghost', h=48, px=15)
        rb.clicked.connect(lambda: self.recommend_to({'kind': cand.get('kind', 'movie'), 'name': cand.get('name'),
                                                       'year': cand.get('year'), 'meta_id': cand.get('id'),
                                                       'poster': cand.get('poster'), 'background': cand.get('background')}))
        row.addWidget(rb)
        share = cand.get('_share')
        if share:
            db = PillButton('Dismiss', 'x', 'ghost', h=48, px=15)
            db.clicked.connect(lambda: (self.dismiss_share(share), self.back()))
            row.addWidget(db)
        row.addStretch(1)
        col.addLayout(row)
        col.addSpacing(6)
        if share and share.get('note'):
            nb = label(f'“{share["note"]}”  — {share.get("from_name", "a friend")}', 15, ACCENT2, BOLD, wrap=True, maxw=760)
            col.addWidget(nb)
        elif share:
            col.addWidget(label(f'{share.get("from_name", "A friend")} recommended this to you.', 14, ACCENT2, BOLD))
        if desc:
            col.addWidget(label(desc, 15.5, '#cdcdd7', wrap=True, maxw=760))
        if cast:
            col.addWidget(label('Starring ' + ', '.join(cast), 13.5, MUTED, wrap=True, maxw=760))
        if owned_it:
            col.addWidget(label('You already have this — press Play.', 13, MUTED))
        else:
            col.addWidget(label('Not in your library yet. Add it to your watchlist; once you have the file it '
                                'appears here automatically.', 13, MUTED, wrap=True, maxw=760))
        col.addStretch(1)
        h.addLayout(col, 1)
        v.addWidget(hero)
        v.addStretch(1)

    def open_trailer(self, yt):
        from PyQt6.QtGui import QDesktopServices
        from PyQt6.QtCore import QUrl
        url = yt if str(yt).startswith('http') else f'https://www.youtube.com/watch?v={yt}'
        QDesktopServices.openUrl(QUrl(url))

    # ------------------------------------------------------------ accounts
    ROLE_RANK = {'owner': 4, 'admin': 3, 'moderator': 2, 'tester': 1, 'viewer': 0}

    def my_role(self):
        return self.main.account().get('role', 'owner')

    def my_rank(self):
        return self.ROLE_RANK.get(self.my_role(), 0)

    def can_panel(self):
        return self.my_role() in ('owner', 'admin', 'moderator')

    def can_manage(self):
        return self.my_role() in ('owner', 'admin')

    def can_act_on(self, a):
        return (self.can_panel() and a.get('role') != 'owner'
                and self.my_rank() > self.ROLE_RANK.get(a.get('role'), 0))

    def account_tapped(self):
        if self.can_panel():
            self.go('accounts')
        else:
            m = QMenu(self)
            m.setStyleSheet(MENU_CSS)
            m.setFont(font(13.5))
            m.addAction('Switch account', self.main.switch_account)
            m.exec(self.btn_account.mapToGlobal(QPoint(0, -10)))

    def on_accounts(self, rows):
        self.account_rows = rows or []
        if self.current[0] == 'accounts':
            self.render(keep_scroll=True)

    def render_accounts(self, _, keep_scroll=False):
        v = self.page.fresh(keep_scroll=keep_scroll)
        self.pages.setCurrentWidget(self.page)
        if not self.can_panel():
            v.addWidget(label('You don’t have access to account management.', 15, MUTED))
            v.addStretch(1)
            return
        self.main.cloud.fetch_accounts()
        w0, _h = section('People', top=6)
        v.addWidget(w0)
        v.addWidget(label('Everyone has their own watch history, library and recommendations. '
                          'Add someone, then give them their name + PIN. Revoke to cut their access instantly.', 13.5, MUTED))
        v.addSpacing(6)
        if self.can_manage():
            add = PillButton('Add account', 'plus', 'primary', h=40, px=14)
            add.clicked.connect(self.add_account)
            v.addWidget(add, 0, Qt.AlignmentFlag.AlignLeft)
            v.addSpacing(6)
        rows = sorted(self.account_rows, key=lambda a: (a.get('role') != 'owner', (a.get('name') or '').lower()))
        if not rows:
            v.addWidget(label('Loading…', 14, MUTED))
        for a in rows:
            v.addWidget(self.account_row(a))
        v.addStretch(1)

    def account_row(self, a):
        import time as _t
        card = QFrame()
        online = a.get('last_seen') and (_t.time() - a['last_seen'] < 90)
        revoked = a.get('active') is False
        card.setStyleSheet(f'QFrame{{background:{SURFACE}; border:1px solid {BORDER}; border-radius:12px}}')
        h = QHBoxLayout(card)
        h.setContentsMargins(16, 12, 12, 12)
        h.setSpacing(12)
        dot = QLabel('●')
        dot.setStyleSheet(f'color:{"#54d98c" if online else "#555"};background:transparent;border:none;font-size:13px')
        h.addWidget(dot, 0, Qt.AlignmentFlag.AlignTop)
        col = QVBoxLayout()
        col.setSpacing(2)
        name = (a.get('name') or a['id']) + f'  ·  {a.get("role", "viewer")}'
        nl = label(name + ('   (revoked)' if revoked else ''), 16, '#8c8c9b' if revoked else TEXT, BOLD)
        nl.setStyleSheet(f'color:{"#8c8c9b" if revoked else TEXT};background:transparent;border:none')
        col.addWidget(nl)
        if online and a.get('now_playing'):
            sub = f'Watching {a["now_playing"]}'
        elif online:
            sub = 'Online'
        elif a.get('last_seen'):
            mins = int((_t.time() - a['last_seen']) / 60)
            sub = 'Last seen ' + ('just now' if mins < 1 else f'{mins} min ago' if mins < 60 else
                                  f'{mins // 60} h ago' if mins < 1440 else f'{mins // 1440} d ago')
        else:
            sub = 'Never signed in'
        s = label(sub + (f'   ·   on {a["device"]}' if a.get('device') and online else ''), 13, MUTED)
        s.setStyleSheet(f'color:{MUTED};background:transparent;border:none')
        col.addWidget(s)
        h.addLayout(col, 1)
        if self.can_act_on(a):
            if revoked:
                rb = PillButton('Restore', None, 'ghost', h=34, px=13)
                rb.clicked.connect(lambda _=0, a=a: self.set_active(a, True))
                h.addWidget(rb)
            else:
                kb = PillButton('Revoke', 'power', 'ghost', h=34, px=13)
                kb.clicked.connect(lambda _=0, a=a: self.set_active(a, False))
                h.addWidget(kb)
            if self.can_manage():
                xb = IconButton('x', 34, 16, tip='Delete account')
                xb.clicked.connect(lambda _=0, a=a: self.remove_account(a))
                h.addWidget(xb)
        return card

    def add_account(self):
        if not self.can_manage():
            return
        from reel import AddAccountDialog
        roles = [r for r in ('admin', 'moderator', 'tester', 'viewer')
                 if self.ROLE_RANK[r] < self.my_rank()]
        dlg = AddAccountDialog(self.main, roles)
        if not dlg.exec() or not dlg.result_row:
            return
        r = dlg.result_row
        import time as _t
        from cloud import slug
        aid = slug(r['name'])
        if aid == 'owner' or any(a['id'] == aid for a in self.account_rows):
            aid = aid + '-' + str(int(_t.time()) % 1000)
        self.main.cloud.save_account({'id': aid, 'name': r['name'], 'pin': r['pin'], 'role': r['role'],
                                      'active': True, 't': _t.time()})
        self.set_cloud_status(f'Added {r["name"]} ({r["role"]}) — PIN {r["pin"]}')
        QTimer.singleShot(900, lambda: self.render(keep_scroll=True))

    def set_active(self, a, active):
        row = {'id': a['id'], 'active': active}
        self.main.cloud.save_account(row)
        a['active'] = active
        self.render(keep_scroll=True)

    def remove_account(self, a):
        from PyQt6.QtWidgets import QMessageBox
        if QMessageBox.question(self, 'Delete account',
                                f'Delete {a.get("name") or a["id"]} and all their watch data?') == QMessageBox.StandardButton.Yes:
            self.main.cloud.delete_account(a['id'])
            self.account_rows = [x for x in self.account_rows if x['id'] != a['id']]
            self.render(keep_scroll=True)

    # ------------------------------------------------------------ recommend to someone
    def on_shares(self, rows):
        before = {s['id'] for s in self.shares_rows}
        self.shares_rows = rows or []
        if {s['id'] for s in self.shares_rows} != before and self.current[0] in ('discover', 'home'):
            self.render(keep_scroll=True)

    def recommend_to(self, payload):
        from reel import RecommendDialog
        me = self.main.account()['id']
        accounts = [a for a in (self.account_rows or self.main.cloud.accounts_sync())
                    if a['id'] != me and a.get('active') is not False]
        if not accounts:
            self.set_cloud_status('No one to recommend to yet — add an account in People.')
            return
        RecommendDialog(self.main, payload, accounts).exec()
        self.set_cloud_status('Recommendation sent.')

    def movie_payload(self, it):
        mm = self.movie_meta(it)
        return {'kind': 'movie', 'name': mm.get('name') or it.title, 'year': it.year or mm.get('year', ''),
                'meta_id': mm.get('id', ''), 'poster': mm.get('poster', ''), 'background': mm.get('background', '')}

    def show_payload(self, show):
        sm = self.show_meta(show)
        return {'kind': 'series', 'name': sm.get('name') or show.name, 'year': sm.get('year') or show.year,
                'meta_id': sm.get('id', ''), 'poster': sm.get('poster', ''), 'background': sm.get('background', '')}

    def share_card(self, s):
        def resolve():
            owned_it, _ = self.owned_item({'name': s.get('name'), 'kind': s.get('kind')})
            sub = f'from {s.get("from_name", "a friend")}'
            return {'title': s.get('name', ''), 'sub': sub,
                    'pix': self.images.remote(s.get('poster')) if s.get('poster') else None,
                    'icon': 'tv' if s.get('kind') == 'series' else 'film',
                    'badge': 'IN LIBRARY' if owned_it else 'RECOMMENDED'}
        return Card('poster', resolve, lambda: self.open_share(s), lambda pos: self.share_menu(s, pos))

    def open_share(self, s):
        # treat a received recommendation like a Discover title (play if owned, watchlist, trailer)
        self.go('reco', {'id': s.get('meta_id') or s.get('name'), 'kind': s.get('kind', 'movie'),
                         'name': s.get('name'), 'year': s.get('year'), 'poster': s.get('poster'),
                         'background': s.get('background'), '_share': s})

    def share_menu(self, s, pos):
        m = QMenu(self)
        m.setStyleSheet(MENU_CSS)
        m.setFont(font(13.5))
        owned_it, is_show = self.owned_item({'name': s.get('name'), 'kind': s.get('kind')})
        if owned_it:
            m.addAction('Play' if not is_show else 'Open',
                        lambda: self.open_show(owned_it) if is_show else self.play.emit(owned_it, None))
        m.addAction('Open', lambda: self.open_share(s))
        m.addSeparator()
        m.addAction('Dismiss', lambda: self.dismiss_share(s))
        m.exec(pos)

    def dismiss_share(self, s):
        self.main.cloud.dismiss_share(s['id'])
        self.shares_rows = [x for x in self.shares_rows if x['id'] != s['id']]
        self.render(keep_scroll=True)

    def open_movie(self, it):
        self.go('movie', it)

    def open_show(self, show):
        self.go('show', show)

    def render_movie(self, it, keep_scroll=False):
        v = self.page.fresh((0, 0, 0, 48), keep_scroll)
        self.pages.setCurrentWidget(self.page)
        mm = self.movie_meta(it)
        hero = Hero(lambda: (self.images.remote(mm.get('background')) if mm.get('background') else None) or self.images.frame(it), 520)
        h = QHBoxLayout(hero)
        h.setContentsMargins(40, 30, 40, 30)
        h.setSpacing(36)
        poster = ImageBox(lambda: self.images.remote(mm.get('poster')) if mm.get('poster') else None, 250, 375,
                          mm.get('name') or it.title, 'film', 14)
        h.addWidget(poster, 0, Qt.AlignmentFlag.AlignVCenter)
        col = QVBoxLayout()
        col.setSpacing(10)
        col.addStretch(1)
        col.addWidget(label(mm.get('name') or it.title, 42, TEXT, HEAVY, wrap=True, maxw=820))
        bits = [str(it.year or mm.get('year') or ''), fmt_dur(self.store.duration(it)) or mm.get('runtime', ''),
                f'★ {mm["rating"]}' if mm.get('rating') else '', ', '.join(mm.get('genres', []))]
        col.addWidget(label('   ·   '.join(b for b in bits if b), 15, '#d0d0da', BOLD))
        if it.quality:
            q = label(f' {it.quality} ', 12, TEXT, HEAVY)
            q.setStyleSheet('color:#f3f3f6;background:rgba(255,255,255,28);border-radius:5px;padding:3px 6px')
            col.addWidget(q, 0, Qt.AlignmentFlag.AlignLeft)
        col.addSpacing(6)
        row = QHBoxLayout()
        row.setSpacing(10)
        pos = self.store.resume_pos(it)
        b = PillButton(f'Resume  {fmt_time(pos)}' if pos > 15 else 'Play', 'play', 'light', h=48, px=15)
        b.clicked.connect(lambda: self.play.emit(it, None))
        row.addWidget(b)
        if pos > 15:
            r = PillButton('Start over', None, 'ghost', h=48, px=15)
            r.clicked.connect(lambda: self.play.emit(it, 0))
            row.addWidget(r)
        watched = self.store.watched(it)
        wb = PillButton('Mark unwatched' if watched else 'Mark watched', 'check', 'ghost', h=48, px=15)
        wb.clicked.connect(lambda: (self.store.set_watched(it, not watched), self.render(keep_scroll=True)))
        row.addWidget(wb)
        if self.main.cloud.on:
            rb = PillButton('Recommend', 'users', 'ghost', h=48, px=15)
            rb.clicked.connect(lambda: self.recommend_to(self.movie_payload(it)))
            row.addWidget(rb)
        self._add_save_button(row, it)
        self._add_download_button(row, [it], 'Download')
        row.addStretch(1)
        col.addLayout(row)
        col.addSpacing(6)
        if mm.get('description'):
            col.addWidget(label(mm['description'], 15.5, '#cdcdd7', wrap=True, maxw=760))
        credits = []
        if mm.get('director'):
            credits.append('Directed by ' + ', '.join(mm['director']))
        if mm.get('cast'):
            credits.append('Starring ' + ', '.join(mm['cast']))
        for c in credits:
            col.addWidget(label(c, 13.5, MUTED, wrap=True, maxw=760))
        col.addStretch(1)
        h.addLayout(col, 1)
        v.addWidget(hero)
        inner = QWidget()
        iv = QVBoxLayout(inner)
        iv.setContentsMargins(40, 0, 40, 0)
        iv.addWidget(section('File', top=0)[0])
        if it.remote:
            iv.addWidget(label(f'In your library  ·  {fmt_size(it.size)}  ·  streams to this computer, or press '
                               f'Download to keep a copy here', 13, MUTED, wrap=True))
        else:
            iv.addWidget(label(f'{it.path}\n{fmt_size(it.size)}', 13, MUTED, wrap=True))
            sf = PillButton('Show in folder', 'folder', 'ghost', h=36, px=13)
            sf.clicked.connect(lambda: reveal(it.path))
            iv.addWidget(sf)
        if not mm and self.meta.enabled:
            iv.addWidget(label('No online match for this title. The filename might be unusual.', 13, MUTED))
        v.addWidget(inner)
        v.addStretch(1)

    def render_show(self, show, keep_scroll=False):
        show = self.lib.shows.get(show.key, show)
        v = self.page.fresh((0, 0, 0, 48), keep_scroll)
        self.pages.setCurrentWidget(self.page)
        sm = self.show_meta(show)
        nxt = self.store.up_next(show)
        hero = Hero(lambda: (self.images.remote(sm.get('background')) if sm.get('background') else None)
                    or self.images.frame(show.episodes[0]), 500)
        h = QHBoxLayout(hero)
        h.setContentsMargins(40, 30, 40, 30)
        h.setSpacing(36)
        h.addWidget(ImageBox(lambda: self.images.remote(sm.get('poster')) if sm.get('poster') else None, 240, 360,
                             sm.get('name') or show.name, 'tv', 14), 0, Qt.AlignmentFlag.AlignVCenter)
        col = QVBoxLayout()
        col.setSpacing(10)
        col.addStretch(1)
        col.addWidget(label(sm.get('name') or show.name, 42, TEXT, HEAVY, wrap=True, maxw=820))
        ns = len(show.seasons)
        watched = sum(1 for e in show.episodes if self.store.watched(e))
        bits = [str(sm.get('year') or show.year or ''), f'{ns} season' + ('s' if ns != 1 else ''),
                f'{len(show.episodes)} episodes', f'★ {sm["rating"]}' if sm.get('rating') else '',
                ', '.join(sm.get('genres', []))]
        col.addWidget(label('   ·   '.join(b for b in bits if b), 15, '#d0d0da', BOLD))
        if watched:
            col.addWidget(label(f'{watched} of {len(show.episodes)} watched', 13.5, MUTED))
        col.addSpacing(6)
        row = QHBoxLayout()
        row.setSpacing(10)
        pos = self.store.resume_pos(nxt)
        txt = f'Resume {nxt.code}' if pos > 15 else f'Play {nxt.code}'
        b = PillButton(txt, 'play', 'light', h=48, px=15)
        b.clicked.connect(lambda: self.play.emit(nxt, None))
        row.addWidget(b)
        if self.main.cloud.on:
            rb = PillButton('Recommend', 'users', 'ghost', h=48, px=15)
            rb.clicked.connect(lambda: self.recommend_to(self.show_payload(show)))
            row.addWidget(rb)
        self._add_download_button(row, show.episodes, 'Download all')
        row.addStretch(1)
        col.addLayout(row)
        col.addSpacing(6)
        if sm.get('description'):
            col.addWidget(label(sm['description'], 15.5, '#cdcdd7', wrap=True, maxw=760))
        if sm.get('cast'):
            col.addWidget(label('Starring ' + ', '.join(sm['cast']), 13.5, MUTED, wrap=True, maxw=760))
        col.addStretch(1)
        h.addLayout(col, 1)
        v.addWidget(hero)

        inner = QWidget()
        iv = QVBoxLayout(inner)
        iv.setContentsMargins(40, 0, 40, 0)
        iv.setSpacing(6)
        seasons = show.seasons
        cur = self.season.get(show.key, nxt.season if nxt.season in seasons else seasons[0])
        if cur not in seasons:
            cur = seasons[0]
        if len(seasons) > 1:
            iv.addWidget(pills([(s, f'Season {s}' if s else 'Specials') for s in seasons], cur,
                               lambda s: (self.season.__setitem__(show.key, s), self.render(keep_scroll=True))))
        eps = [e for e in show.episodes if e.season == cur]
        sw, sh = section(f'Season {cur}' if cur else 'Episodes', f'{len(eps)} episodes', top=8)
        if len(seasons) > 1:
            self._add_download_button(sh, eps, f'Download season {cur}' if cur else 'Download these', h=36, px=13.5)
        iv.addWidget(sw)
        for e in eps:
            iv.addWidget(EpisodeRow(self, e, lambda e=e: self.play.emit(e, None), lambda pos, e=e: self.item_menu(e, pos)))
        v.addWidget(inner)
        v.addStretch(1)

    # ------------------------------------------------------------ menus
    def item_menu(self, it, pos):
        m = QMenu(self)
        m.setStyleSheet(MENU_CSS)
        m.setFont(font(13.5))
        m.addAction('Play', lambda: self.play.emit(it, None))
        if self.store.resume_pos(it) > 15:
            m.addAction('Play from beginning', lambda: self.play.emit(it, 0))
        w = self.store.watched(it)
        m.addAction('Mark as unwatched' if w else 'Mark as watched',
                    lambda: (self.store.set_watched(it, not w), self.render(keep_scroll=True)))
        if it.kind == 'movie' and self.main.cloud.on:
            m.addAction('Recommend to…', lambda: self.recommend_to(self.movie_payload(it)))
        if not it.remote and self.main.can_upload() and not self.main.already_shared(it):
            m.addAction('Save to my library', lambda: self.main.upload_item(it))
        if it.remote:
            d = self.main.downloads.entry(it)
            if not d or d['state'] == 'failed':
                m.addAction('Download to this computer', lambda: self.main.download([it]))
            elif d['state'] in ('queued', 'downloading'):
                m.addAction('Cancel download', lambda: self.main.downloads.remove(d['id']))
        if not it.remote:
            m.addSeparator()
            m.addAction('Show in folder', lambda: reveal(it.path))
            m.addAction('Remove from library', lambda: self.main.hide_items([it]))
        m.exec(pos)

    def _add_save_button(self, row, it):
        """'Save to my library' — only on activated installs, for a local file not yet shared."""
        if it.remote or not self.main.can_upload() or self.main.already_shared(it):
            return
        sb = PillButton('Save to my library', 'plus', 'ghost', h=48, px=15)
        sb.clicked.connect(lambda: self.main.upload_item(it))
        row.addWidget(sb)

    def show_menu(self, show, pos):
        m = QMenu(self)
        m.setStyleSheet(MENU_CSS)
        m.setFont(font(13.5))
        m.addAction('Open', lambda: self.open_show(show))
        if self.main.cloud.on:
            m.addAction('Recommend to…', lambda: self.recommend_to(self.show_payload(show)))
        m.addAction('Mark all watched', lambda: ([self.store.set_watched(e, True) for e in show.episodes], self.render(keep_scroll=True)))
        m.addAction('Mark all unwatched', lambda: ([self.store.set_watched(e, False) for e in show.episodes], self.render(keep_scroll=True)))
        if any(e.remote for e in show.episodes):
            m.addAction('Download all to this computer', lambda: self.main.download(show.episodes))
        local = [e for e in show.episodes if not e.remote]
        if local:
            m.addSeparator()
            m.addAction('Show in folder', lambda: reveal(local[0].path))
            m.addAction('Remove from library', lambda: self.main.hide_items(local))
        m.exec(pos)

    # ------------------------------------------------------------ downloads (other computers -> this one)
    def remote_any(self):
        return any(i.remote for i in self.lib.items)

    def _dl_state(self, items):
        """(active entries, failed entries, remote items) for a set of items."""
        dl = self.main.downloads
        remote = [i for i in items if i.remote]
        ents = [e for e in (dl.entry(i) for i in remote) if e]
        return ([e for e in ents if e['state'] in ('queued', 'downloading')],
                [e for e in ents if e['state'] == 'failed'], remote)

    def todo_items(self, items):
        """Remote items that aren't queued / downloaded yet (failed ones count — they get retried)."""
        dl = self.main.downloads
        out = []
        for i in items:
            e = dl.entry(i) if i.remote else None
            if i.remote and (not e or e['state'] == 'failed'):
                out.append(i)
        return out

    def dl_short(self, it):
        if not it.remote:
            return ''
        d = self.main.downloads.entry(it)
        if not d:
            return ''
        if d['state'] == 'downloading':
            return f"Downloading {int(d['got'] * 100 / d['size']) if d.get('size') else 0}%"
        return {'queued': 'Queued to download', 'failed': 'Download failed'}.get(d['state'], '')

    def _decorate(self, d, key, items):
        """Add select-mode and download badges to a card's paint data."""
        if self.selecting:
            if any(i.remote for i in items):
                d['select'] = key in self.selected
            else:
                d['dim'] = True            # already on this computer: nothing to download
        if not d.get('badge'):
            active, failed, remote = self._dl_state(items)
            if active:
                if len(remote) == 1 and active[0]['state'] == 'downloading':
                    e = active[0]
                    d['badge'] = f"DOWNLOADING {int(e['got'] * 100 / e['size']) if e.get('size') else 0}%"
                else:
                    d['badge'] = 'DOWNLOADING' if any(e['state'] == 'downloading' for e in active) else 'QUEUED'
            elif failed:
                d['badge'] = 'DOWNLOAD FAILED'
        return d

    def card_click(self, key, items, open_fn):
        if not self.selecting:
            return open_fn()
        if not any(i.remote for i in items):
            return
        if key in self.selected:
            del self.selected[key]
        else:
            self.selected[key] = items
        self.update_sel_bar()
        self._repaint_cards()

    def _select_button(self, h):
        if not self.remote_any():
            return
        if self.selecting:
            b = PillButton('Done', 'check', 'ghost', h=36, px=13.5)
            b.clicked.connect(self.stop_selecting)
        else:
            b = PillButton('Select to download', 'download', 'ghost', h=36, px=13.5)
            b.clicked.connect(self.start_selecting)
        h.addWidget(b)

    def start_selecting(self):
        self.selecting = True
        self.selected = {}
        self.update_sel_bar()
        self.render(keep_scroll=True)

    def stop_selecting(self, render=True):
        self.selecting = False
        self.selected = {}
        self.sel_bar.hide()
        if render:
            self.render(keep_scroll=True)

    def select_all(self):
        pick = {k: items for k, items in self._page_entries if any(i.remote for i in items)}
        self.selected = {} if pick and all(k in self.selected for k in pick) else pick
        self.update_sel_bar()
        self._repaint_cards()

    def selected_items(self):
        out, seen = [], set()
        for items in self.selected.values():
            for i in self.todo_items(items):
                sid = sync_id(i)
                if sid not in seen:
                    seen.add(sid)
                    out.append(i)
        return out

    def update_sel_bar(self):
        self.sel_bar.setVisible(self.selecting)
        if not self.selecting:
            return
        items = self.selected_items()
        size = sum(i.size or 0 for i in items)
        if not self.selected:
            self.sel_label.setText('Tap movies or shows to pick what to download')
        else:
            n = len(self.selected)
            free = free_space(self.main.server.library_dir())
            warn = '  ·  not enough space!' if size > free else ''
            self.sel_label.setText(f'{n} selected  ·  {len(items)} file' + ('s' if len(items) != 1 else '') +
                                   f'  ·  {fmt_size(size)}  ·  {fmt_size(free)} free{warn}')
        self.sel_go.setText(f'Download {fmt_size(size)}' if items else 'Download')

    def download_selected(self):
        items = self.selected_items()
        if not items:
            return
        self.main.download(items)
        self.stop_selecting(render=False)
        self.go('downloads')

    def _add_download_button(self, row, items, text, h=48, px=15):
        if not any(i.remote for i in items):
            return
        b = PillButton(text, 'download', 'ghost', h=h, px=px)
        self._dl_buttons.append((b, items, text))
        self._set_dl_button(b, items, text)
        b.clicked.connect(lambda: self._dl_button_click(items))
        row.addWidget(b)

    def _set_dl_button(self, b, items, text):
        active, failed, remote = self._dl_state(items)
        todo = self.todo_items(items)
        if active:
            if len(remote) == 1:
                e = active[0]
                pct = int(e['got'] * 100 / e['size']) if e.get('size') else 0
                t = f'Downloading {pct}%' if e['state'] == 'downloading' else 'Queued'
            else:
                t = f'Downloading · {len(active)} left'
        elif failed and len(remote) == 1:
            t = 'Retry download'
        elif todo:
            t = f'{text}  ·  {fmt_size(sum(i.size or 0 for i in todo))}'
        else:
            t = text
        if b.text() != t:
            b.setText(t)

    def _dl_button_click(self, items):
        if not self.todo_items(items):    # all queued already: show the queue
            return self.go('downloads')
        self.main.download(items)
        for b, its, text in self._dl_buttons:
            try:
                self._set_dl_button(b, its, text)
            except RuntimeError:
                pass
        self.repaint_timer.start()

    def on_downloads(self):
        if not self.dl_timer.isActive():
            self.dl_timer.start()

    def _dl_refresh(self):
        dl = self.main.downloads
        n = len(dl.active())
        nb = self.nav['downloads']
        nb.count = str(n) if n else ''
        nb.setVisible(bool(self.main.cloud.on or dl.queue))
        nb.update()
        for b, items, text in list(self._dl_buttons):
            try:
                self._set_dl_button(b, items, text)
            except RuntimeError:          # button's page was replaced
                pass
        if self.current[0] == 'downloads' and self.main.stack.currentWidget() is self:
            if [(d['id'], d['state']) for d in dl.queue] != self._dl_sig:
                self.render(keep_scroll=True)
            else:
                for r in self.page.findChildren(DownloadRow):
                    r.refresh()
        else:
            self._repaint_cards()
        if self.selecting:
            self.update_sel_bar()

    def dl_item(self, d):
        return self._sid_map.get(d['id'])

    def dl_poster(self, d):
        it = self.dl_item(d)
        if not it:
            return None
        m = self.show_meta(self.lib.show_of(it)) if it.kind == 'episode' else self.movie_meta(it)
        return self.images.remote(m.get('poster')) if m.get('poster') else None

    def dl_status(self, d):
        dl = self.main.downloads
        st, got, size = d.get('state'), d.get('got', 0), d.get('size', 0)
        if st == 'downloading':
            bits = [f'{int(got * 100 / size)}%' if size else '', f'{fmt_size(got)} of {fmt_size(size)}' if size else fmt_size(got)]
            if dl.rate > 0:
                bits.append(f'{dl.rate / 1024**2:.1f} MB/s')
                if size:
                    bits.append(f'{eta(max(0, size - got) / dl.rate)} left')
            return '  ·  '.join(b for b in bits if b)
        if st == 'queued':
            if d['id'] not in dl.items:
                return f'Waiting for {d.get("from") or "your other computer"} to come online  ·  {fmt_size(size)}'
            t = 'Queued' + (f'  ·  {int(got * 100 / size)}% done' if got and size else '') + f'  ·  {fmt_size(size)}'
            return t + (f'  ·  {d["error"]}' if d.get('error') else '')
        if st == 'failed':
            return f'Failed — {d.get("error") or "unknown error"}'
        return f'On this computer  ·  {fmt_size(size)}'

    def play_download(self, d):
        if os.path.isfile(d.get('path', '')):
            self.main.play_path(d['path'])

    def open_download_folder(self):
        from PyQt6.QtGui import QDesktopServices
        from PyQt6.QtCore import QUrl
        folder = self.main.server.library_dir()
        os.makedirs(folder, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(folder))

    def render_downloads(self, _, keep_scroll=False):
        v = self.page.fresh(keep_scroll=keep_scroll)
        self.pages.setCurrentWidget(self.page)
        dl = self.main.downloads
        q = list(dl.queue)
        self._dl_sig = [(d['id'], d['state']) for d in q]
        self._sid_map = {sync_id(i): i for i in self.lib.items}
        active = dl.active()
        w, h = section('Downloads', f'{len(active)} in the queue' if active else None, top=6)
        if self.remote_any():
            pick = PillButton('Pick movies & shows', 'download', 'primary', h=36, px=13.5)
            pick.clicked.connect(lambda: (self.go('movies'), self.start_selecting()))
            h.addWidget(pick)
        if any(d['state'] == 'done' for d in q):
            cl = PillButton('Clear finished', None, 'ghost', h=36, px=13.5)
            cl.clicked.connect(lambda: (dl.clear_done(), self.render(keep_scroll=True)))
            h.addWidget(cl)
        of = PillButton('Open folder', 'folder', 'ghost', h=36, px=13.5)
        of.clicked.connect(self.open_download_folder)
        h.addWidget(of)
        v.addWidget(w)
        folder = self.main.server.library_dir()
        v.addWidget(label(f'Movies and shows from your other computers are saved to  {folder}  so they play without '
                          f'internet.  {fmt_size(free_space(folder))} free.  Downloads keep going while Reel is in the '
                          f'tray, and pick up where they left off after a restart.', 13.5, MUTED, wrap=True, maxw=900))
        v.addSpacing(4)
        if not q:
            msg = ('Nothing here yet. Press “Pick movies & shows” (or “Select to download” on Movies / TV Shows), '
                   'tap the ones you want, then Download.') if self.remote_any() else \
                  ('Nothing to download yet — once your other computer is online with Reel open, '
                   'its movies and shows show up here to grab.')
            v.addWidget(label(msg, 15, MUTED, wrap=True, maxw=760))
        order = {'downloading': 0, 'queued': 1, 'failed': 2, 'done': 3}
        q.sort(key=lambda d: (order.get(d['state'], 4), -d.get('finished', 0) if d['state'] == 'done' else d.get('added', 0)))
        for d in q:
            v.addWidget(DownloadRow(self, d))
        v.addStretch(1)

    # ------------------------------------------------------------ scan status
    def set_cloud_status(self, text):
        self.cloud_status.setText(text)
        self.cloud_status.setVisible(bool(text))

    def set_scan_status(self, text, active):
        self.scan_status.setText(text)
        self.scan_bar.set_active(active)
        self.btn_scan.setText('Stop scan' if active else 'Scan computer')


def free_space(path):
    while path and not os.path.exists(path):
        parent = os.path.dirname(path)
        if parent == path:
            break
        path = parent
    try:
        return shutil.disk_usage(path).free
    except OSError:
        return 0


def eta(secs):
    secs = int(secs)
    if secs < 60:
        return 'under a minute'
    h, m = secs // 3600, secs % 3600 // 60
    return f'{h}h {m}m' if h else f'{m} min'


class ProgressLine(QWidget):
    def __init__(self):
        super().__init__()
        self.setFixedHeight(6)
        self.frac, self.color = 0.0, ACCENT

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect())
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 255, 255, 26))
        p.drawRoundedRect(r, 3, 3)
        if self.frac > 0:
            p.setBrush(QColor(self.color))
            p.drawRoundedRect(QRectF(0, 0, r.width() * min(1.0, self.frac), r.height()), 3, 3)


class DownloadRow(QFrame):
    def __init__(self, browser, d):
        super().__init__()
        self.b, self.d = browser, d
        dl = browser.main.downloads
        self.setObjectName('dlrow')
        self.setStyleSheet(f'#dlrow{{background:{SURFACE};border:1px solid {BORDER};border-radius:14px}}')
        h = QHBoxLayout(self)
        h.setContentsMargins(14, 12, 16, 12)
        h.setSpacing(16)
        h.addWidget(ImageBox(lambda: browser.dl_poster(d), 52, 78, '',
                             'tv' if d.get('kind') == 'episode' else 'film', 8))
        col = QVBoxLayout()
        col.setSpacing(7)
        col.addStretch(1)
        col.addWidget(label(d.get('name', ''), 15.5, TEXT, BOLD))
        self.status = label('', 13, MUTED, wrap=True)
        col.addWidget(self.status)
        self.bar = ProgressLine()
        col.addWidget(self.bar)
        col.addStretch(1)
        h.addLayout(col, 1)
        st = d.get('state')
        if st == 'done':
            pb = PillButton('Play', 'play', 'light', h=38, px=13.5)
            pb.clicked.connect(lambda: browser.play_download(d))
            h.addWidget(pb)
            fb = IconButton('folder', 38, 19, tip='Show in folder')
            fb.clicked.connect(lambda: reveal(d['path']) if os.path.exists(d.get('path', '')) else None)
            h.addWidget(fb)
        elif st == 'failed':
            rb = PillButton('Retry', 'refresh', 'ghost', h=38, px=13.5)
            rb.clicked.connect(lambda: dl.retry(d['id']))
            h.addWidget(rb)
        xb = IconButton('x', 38, 18, tip='Remove from list (keeps the file)' if st == 'done' else 'Cancel download')
        xb.clicked.connect(lambda: (dl.remove(d['id']), browser.render(keep_scroll=True)))
        h.addWidget(xb)
        self.refresh()

    def refresh(self):
        d = self.d
        self.status.setText(self.b.dl_status(d))
        size = d.get('size') or 0
        self.bar.frac = (d.get('got', 0) / size) if size else 0
        self.bar.color = ACCENT if d.get('state') == 'downloading' else '#6a6a78'
        self.bar.setVisible(d.get('state') != 'done')
        self.bar.update()


def reveal(path):
    if sys.platform == 'win32':
        subprocess.Popen(['explorer', '/select,', os.path.normpath(path)])
    elif sys.platform == 'darwin':
        subprocess.Popen(['open', '-R', path])
    else:
        subprocess.Popen(['xdg-open', os.path.dirname(path)])
