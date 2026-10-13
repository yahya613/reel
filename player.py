"""Player: libmpv rendered into a QOpenGLWidget, with a clean auto-hiding overlay."""
import os, re, sys, subprocess
from PyQt6.QtCore import Qt, QTimer, QRectF, pyqtSignal
from PyQt6.QtGui import QPainter, QColor, QLinearGradient, QOpenGLContext, QFontMetricsF, QPainterPath
from PyQt6.QtOpenGLWidgets import QOpenGLWidget
from PyQt6.QtWidgets import (QWidget, QHBoxLayout, QVBoxLayout, QLabel, QAbstractButton, QScrollArea,
                             QFileDialog, QFrame)
import mpv
from PyQt6.QtGui import QFont
NORMAL = QFont.Weight.Normal
from theme import (TEXT, MUTED, ACCENT, ACCENT2, font, BOLD, HEAVY, draw_icon, IconButton, PillButton, Fader,
                   Toast, rounded)
from library import fmt_time, fmt_dur

LANGS = {'en': 'English', 'eng': 'English', 'ja': 'Japanese', 'jpn': 'Japanese', 'es': 'Spanish', 'spa': 'Spanish',
         'fr': 'French', 'fre': 'French', 'fra': 'French', 'de': 'German', 'ger': 'German', 'deu': 'German',
         'it': 'Italian', 'ita': 'Italian', 'pt': 'Portuguese', 'por': 'Portuguese', 'pob': 'Portuguese (BR)',
         'ru': 'Russian', 'rus': 'Russian', 'ko': 'Korean', 'kor': 'Korean', 'zh': 'Chinese', 'chi': 'Chinese',
         'zho': 'Chinese', 'hi': 'Hindi', 'hin': 'Hindi', 'ar': 'Arabic', 'ara': 'Arabic', 'tr': 'Turkish',
         'tur': 'Turkish', 'pl': 'Polish', 'pol': 'Polish', 'nl': 'Dutch', 'dut': 'Dutch', 'nld': 'Dutch',
         'sv': 'Swedish', 'swe': 'Swedish', 'no': 'Norwegian', 'nor': 'Norwegian', 'nob': 'Norwegian',
         'da': 'Danish', 'dan': 'Danish', 'fi': 'Finnish', 'fin': 'Finnish', 'el': 'Greek', 'gre': 'Greek',
         'ell': 'Greek', 'he': 'Hebrew', 'heb': 'Hebrew', 'hu': 'Hungarian', 'hun': 'Hungarian', 'cs': 'Czech',
         'cze': 'Czech', 'ces': 'Czech', 'ro': 'Romanian', 'rum': 'Romanian', 'ron': 'Romanian', 'th': 'Thai',
         'tha': 'Thai', 'vi': 'Vietnamese', 'vie': 'Vietnamese', 'id': 'Indonesian', 'ind': 'Indonesian',
         'ms': 'Malay', 'may': 'Malay', 'msa': 'Malay', 'uk': 'Ukrainian', 'ukr': 'Ukrainian', 'ur': 'Urdu',
         'urd': 'Urdu', 'bn': 'Bengali', 'ben': 'Bengali', 'ta': 'Tamil', 'tam': 'Tamil', 'te': 'Telugu',
         'tel': 'Telugu', 'fil': 'Filipino', 'tgl': 'Tagalog', 'fa': 'Persian', 'per': 'Persian', 'fas': 'Persian',
         'hr': 'Croatian', 'hrv': 'Croatian', 'sr': 'Serbian', 'srp': 'Serbian', 'bg': 'Bulgarian', 'bul': 'Bulgarian'}
CODECS = {'aac': 'AAC', 'ac3': 'Dolby Digital', 'eac3': 'Dolby Digital+', 'truehd': 'TrueHD', 'dts': 'DTS',
          'flac': 'FLAC', 'opus': 'Opus', 'mp3': 'MP3', 'vorbis': 'Vorbis'}
CHANNELS = {1: 'Mono', 2: 'Stereo', 6: '5.1', 8: '7.1'}
JUNK = re.compile(r'galaxy|yts|rarbg|www\.|\.com\b|\.org\b|\.net\b|excellence|encoded|ripped|\bby\b|tgx|eztv|psa\b', re.I)
INTRO = re.compile(r'\b(intro|opening|op|recap|previously)\b', re.I)
CREDITS = re.compile(r'\b(credits|ending|ed|outro|end)\b', re.I)
SUB_SIZES = [('Small', .8), ('Normal', 1.0), ('Large', 1.25), ('Huge', 1.55)]
SPEEDS = [.5, .75, 1.0, 1.25, 1.5, 1.75, 2.0]


def track_text(t):
    code = (t.get('lang') or '').lower()
    lang = LANGS.get(code, code.upper())
    title = (t.get('title') or '').strip()
    main = lang
    if title and not JUNK.search(title) and len(title) <= 40 and title.lower() not in (lang.lower(), code):
        main = f'{lang} · {title}' if lang else title
    main = main or f'Track {t["id"]}'
    extra = []
    if t['type'] == 'audio':
        if t.get('codec'):
            extra.append(CODECS.get(t['codec'], t['codec'].upper()))
        ch = t.get('demux-channel-count')
        if ch:
            extra.append(CHANNELS.get(ch, f'{ch}ch'))
    else:
        if t.get('forced'):
            extra.append('Forced')
        if t.get('hearing-impaired'):
            extra.append('SDH')
        if t.get('external'):
            extra.append('File')
    return main, ' · '.join(extra)


# ---------------------------------------------------------------- video surface

class KeepAwake:
    """Stop the display from sleeping while a video is actually playing.
    mpv normally does this itself, but with vo=libmpv (video rendered inside our window)
    the OS never hears about it, so the screen would sleep mid-movie. We tell it directly.
    """

    def __init__(self):
        self.on = False
        self._proc = None

    def set(self, keep):
        if keep == self.on:
            return
        self.on = keep
        try:
            if sys.platform == 'darwin':
                if keep:
                    # caffeinate -d = no display sleep; -w <pid> makes it quit if Reel ever does
                    self._proc = subprocess.Popen(['caffeinate', '-d', '-w', str(os.getpid())],
                                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                elif self._proc:
                    self._proc.terminate()
                    self._proc = None
            elif sys.platform == 'win32':
                import ctypes
                ES_CONTINUOUS, ES_DISPLAY, ES_SYSTEM = 0x80000000, 0x00000002, 0x00000001
                ctypes.windll.kernel32.SetThreadExecutionState(
                    ES_CONTINUOUS | ES_DISPLAY | ES_SYSTEM if keep else ES_CONTINUOUS)
        except Exception:
            pass


def _gl_proc(_, name):
    ctx = QOpenGLContext.currentContext()
    p = ctx.getProcAddress(name) if ctx else None
    return int(p) if p else 0


class MpvWidget(QOpenGLWidget):
    frame = pyqtSignal()
    gl_ready = pyqtSignal()

    def __init__(self, parent, **opts):
        super().__init__(parent)
        self.mpv = mpv.MPV(vo='libmpv', **opts)
        self.ctx = None
        self._pending = []
        self.frame.connect(self.update, Qt.ConnectionType.QueuedConnection)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

    def initializeGL(self):
        self._proc = mpv.MpvGlGetProcAddressFn(_gl_proc)
        self.ctx = mpv.MpvRenderContext(self.mpv, 'opengl', opengl_init_params={'get_proc_address': self._proc})
        self.ctx.update_cb = self.frame.emit
        for fn in self._pending:
            QTimer.singleShot(0, fn)
        self._pending = []

    def paintGL(self):
        if self.ctx:
            r = self.devicePixelRatioF()
            self.ctx.render(flip_y=True, opengl_fbo={'w': int(self.width() * r), 'h': int(self.height() * r),
                                                     'fbo': self.defaultFramebufferObject()})

    def when_ready(self, fn):
        if self.ctx:
            fn()
        else:
            self._pending.append(fn)

    def shutdown(self):
        if self.ctx:
            self.makeCurrent()
            self.ctx.free()
            self.ctx = None
            self.doneCurrent()
        self.mpv.terminate()

    # input is handled by the player view
    def mouseMoveEvent(self, e):
        self.parent().poke()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.parent().video_clicked()
        elif e.button() == Qt.MouseButton.RightButton:
            self.parent().toggle_panel()

    def mouseDoubleClickEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.parent().video_double()

    def wheelEvent(self, e):
        # mouse wheels send 120 per notch; trackpads send many small steps - add them up
        self._wheel = getattr(self, '_wheel', 0) + e.angleDelta().y()
        while abs(self._wheel) >= 120:
            step = 1 if self._wheel > 0 else -1
            self._wheel -= step * 120
            self.parent().change_volume(5 * step)


# ---------------------------------------------------------------- overlay pieces

class Gradient(QWidget):
    def __init__(self, parent, top):
        super().__init__(parent)
        self.top = top
        self.setMouseTracking(True)

    def paintEvent(self, e):
        p = QPainter(self)
        g = QLinearGradient(0, 0, 0, self.height())
        a, b = QColor(0, 0, 0, 170), QColor(0, 0, 0, 0)
        g.setColorAt(0, a if self.top else b)
        g.setColorAt(1, b if self.top else QColor(0, 0, 0, 200))
        p.fillRect(self.rect(), g)

    def mouseMoveEvent(self, e):
        self.window().findChild(PlayerView).poke()


class SeekBar(QWidget):
    seek = pyqtSignal(float, bool)

    def __init__(self, parent):
        super().__init__(parent)
        self.setFixedHeight(42)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.dur = self.pos = self.cache = 0.0
        self.chapters = []
        self.hover = self.drag = None
        self._last_emit = 0

    M = 8

    def x_to_t(self, x):
        w = self.width() - 2 * self.M
        return max(0.0, min(1.0, (x - self.M) / w)) * self.dur if w > 0 else 0

    def t_to_x(self, t):
        return self.M + (t / self.dur if self.dur else 0) * (self.width() - 2 * self.M)

    def set_state(self, pos, dur, cache):
        self.dur = dur or 0
        if self.drag is None and pos is not None:
            self.pos = pos
        self.cache = cache or 0
        self.update()

    def chapter_at(self, t):
        title = ''
        for c in self.chapters:
            if c.get('time', 0) <= t:
                title = c.get('title') or ''
        return title

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        active = self.hover is not None or self.drag is not None
        th = 6 if active else 4
        y = self.height() - 12
        w = self.width() - 2 * self.M
        track = QRectF(self.M, y - th / 2, w, th)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 255, 255, 60))
        p.drawRoundedRect(track, th / 2, th / 2)
        if self.dur:
            if self.cache > self.pos:
                p.setBrush(QColor(255, 255, 255, 70))
                p.drawRoundedRect(QRectF(self.M, track.y(), self.t_to_x(min(self.cache, self.dur)) - self.M, th), th / 2, th / 2)
            px = self.t_to_x(self.pos)
            p.setBrush(QColor(ACCENT))
            p.drawRoundedRect(QRectF(self.M, track.y(), max(th, px - self.M), th), th / 2, th / 2)
            p.setBrush(QColor(0, 0, 0, 150))
            for c in self.chapters:
                t = c.get('time', 0)
                if 1 < t < self.dur - 1:
                    p.drawRect(QRectF(self.t_to_x(t) - 1, track.y(), 2, th))
            if active:
                p.setBrush(QColor('#ffffff'))
                p.drawEllipse(QRectF(px - 7, y - 7, 14, 14))
            if self.hover is not None:
                t = self.x_to_t(self.hover)
                ch = self.chapter_at(t)
                text = fmt_time(t) + (f'  ·  {ch}' if ch and len(self.chapters) > 1 else '')
                f = font(12, BOLD)
                tw = QFontMetricsF(f).horizontalAdvance(text) + 18
                bx = max(0, min(self.width() - tw, self.hover - tw / 2))
                p.setBrush(QColor(14, 14, 20, 235))
                p.drawRoundedRect(QRectF(bx, 0, tw, 22), 6, 6)
                p.setPen(QColor(TEXT))
                p.setFont(f)
                p.drawText(QRectF(bx, 0, tw, 22), Qt.AlignmentFlag.AlignCenter, text)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and self.dur:
            self.drag = e.position().x()
            self.pos = self.x_to_t(self.drag)
            self.seek.emit(self.pos, False)
            self.update()

    def mouseMoveEvent(self, e):
        self.hover = e.position().x()
        if self.drag is not None:
            self.drag = self.hover
            self.pos = self.x_to_t(self.drag)
            import time
            if time.time() - self._last_emit > 0.06:
                self._last_emit = time.time()
                self.seek.emit(self.pos, False)
        self.update()

    def mouseReleaseEvent(self, e):
        if self.drag is not None:
            self.pos = self.x_to_t(e.position().x())
            self.seek.emit(self.pos, True)
            self.drag = None
            self.update()

    def leaveEvent(self, e):
        self.hover = None
        self.update()


class VolumeSlider(QWidget):
    changed = pyqtSignal(float)

    def __init__(self, parent):
        super().__init__(parent)
        self.setFixedSize(96, 32)
        self.value, self.drag = 100.0, False
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def set_value(self, v):
        self.value = v
        self.update()

    def _from_x(self, x):
        v = max(0.0, min(1.0, (x - 6) / (self.width() - 12))) * 100
        self.value = v
        self.changed.emit(v)
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        y, w = self.height() / 2, self.width() - 12
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 255, 255, 60))
        p.drawRoundedRect(QRectF(6, y - 2, w, 4), 2, 2)
        fx = 6 + w * min(self.value, 100) / 100
        p.setBrush(QColor('#ffffff'))
        p.drawRoundedRect(QRectF(6, y - 2, fx - 6, 4), 2, 2)
        if self.underMouse() or self.drag:
            p.drawEllipse(QRectF(fx - 6, y - 6, 12, 12))

    def enterEvent(self, e):
        self.update()

    def leaveEvent(self, e):
        self.update()

    def mousePressEvent(self, e):
        self.drag = True
        self._from_x(e.position().x())

    def mouseMoveEvent(self, e):
        if self.drag:
            self._from_x(e.position().x())

    def mouseReleaseEvent(self, e):
        self.drag = False
        self.update()


class TextButton(QAbstractButton):
    def __init__(self, text, parent=None, px=14):
        super().__init__(parent)
        self.px = px
        self.setText(text)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setFixedHeight(36)

    def setText(self, t):
        super().setText(t)
        self.setFixedWidth(int(QFontMetricsF(font(self.px, BOLD)).horizontalAdvance(t) + 22))
        self.update()

    def enterEvent(self, e):
        self.update()

    def leaveEvent(self, e):
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self.underMouse():
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(255, 255, 255, 28))
            p.drawRoundedRect(QRectF(self.rect()), 18, 18)
        p.setPen(QColor(TEXT))
        p.setFont(font(self.px, BOLD))
        p.drawText(QRectF(self.rect()), Qt.AlignmentFlag.AlignCenter, self.text())


class OptionRow(QAbstractButton):
    def __init__(self, text, sub='', selected=False, parent=None):
        super().__init__(parent)
        self.setText(text)
        self.sub, self.selected = sub, selected
        self.setFixedHeight(34)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        fs = font(12)
        self.setMinimumWidth(int(min(320, QFontMetricsF(font(14, BOLD)).horizontalAdvance(text) +
                                     (QFontMetricsF(fs).horizontalAdvance(sub) + 10 if sub else 0) + 50)))

    def enterEvent(self, e):
        self.update()

    def leaveEvent(self, e):
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect())
        if self.underMouse():
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(255, 255, 255, 22))
            p.drawRoundedRect(r, 8, 8)
        if self.selected:
            draw_icon(p, 'check', QRectF(8, (r.height() - 16) / 2, 16, 16), ACCENT2)
        f = font(14, BOLD if self.selected else NORMAL)
        p.setFont(f)
        p.setPen(QColor(TEXT if self.selected else '#d4d4dc'))
        fm = QFontMetricsF(f)
        avail = r.width() - 34 - 8
        main = fm.elidedText(self.text(), Qt.TextElideMode.ElideRight, avail)
        p.drawText(QRectF(32, 0, avail, r.height()), Qt.AlignmentFlag.AlignVCenter, main)
        if self.sub:
            x = 32 + fm.horizontalAdvance(main) + 8
            p.setFont(font(12))
            p.setPen(QColor(MUTED))
            p.drawText(QRectF(x, 0, max(0, r.width() - x - 6), r.height()), Qt.AlignmentFlag.AlignVCenter,
                       QFontMetricsF(font(12)).elidedText(self.sub, Qt.TextElideMode.ElideRight, max(0, r.width() - x - 6)))


class TracksPanel(QFrame):
    def __init__(self, player):
        super().__init__(player)
        self.player = player
        self.lay = QHBoxLayout(self)
        self.lay.setContentsMargins(16, 16, 16, 16)
        self.lay.setSpacing(14)
        self.hide()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QColor(255, 255, 255, 24))
        p.setBrush(QColor(16, 16, 22, 242))
        p.drawRoundedRect(QRectF(self.rect()).adjusted(.5, .5, -.5, -.5), 16, 16)

    def column(self, title, rows, width):
        col = QWidget()
        v = QVBoxLayout(col)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(2)
        h = QLabel(title.upper())
        h.setFont(font(11, HEAVY))
        h.setStyleSheet(f'color:{MUTED};letter-spacing:1px;padding:2px 8px 8px 8px;background:transparent')
        v.addWidget(h)
        box = QWidget()
        bv = QVBoxLayout(box)
        bv.setContentsMargins(0, 0, 0, 0)
        bv.setSpacing(1)
        for text, sub, sel, fn in rows:
            r = OptionRow(text, sub, sel)
            r.clicked.connect(fn)
            bv.addWidget(r)
        bv.addStretch(1)
        box.setStyleSheet('background:transparent')
        if len(rows) > 8:
            sa = QScrollArea()
            sa.setWidget(box)
            sa.setWidgetResizable(True)
            sa.setFrameShape(QFrame.Shape.NoFrame)
            sa.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            sa.setFixedHeight(8 * 35)
            sa.setStyleSheet('QScrollArea{background:transparent} QScrollBar:vertical{width:6px;background:transparent}'
                             'QScrollBar::handle:vertical{background:rgba(255,255,255,60);border-radius:3px}'
                             'QScrollBar::add-line,QScrollBar::sub-line{height:0}')
            sa.viewport().setStyleSheet('background:transparent')
            v.addWidget(sa)
        else:
            v.addWidget(box)
        col.setFixedWidth(width)
        col.setStyleSheet('background:transparent')
        return col

    def rebuild(self):
        while self.lay.count():
            w = self.lay.takeAt(0).widget()
            if w:
                w.deleteLater()
        pl = self.player
        tracks = pl.tracks
        audio = [t for t in tracks if t['type'] == 'audio']
        subs = [t for t in tracks if t['type'] == 'sub']
        arows = [(*track_text(t), bool(t.get('selected')), lambda _=0, t=t: pl.pick_track('audio', t)) for t in audio]
        if not arows:
            arows = [('No audio', '', True, lambda: None)]
        any_sub = any(t.get('selected') for t in subs)
        srows = [('Off', '', not any_sub, lambda _=0: pl.pick_track('sub', None))]
        srows += [(*track_text(t), bool(t.get('selected')), lambda _=0, t=t: pl.pick_track('sub', t)) for t in subs]
        srows.append(('Add subtitle file…', '', False, lambda _=0: pl.load_sub_file()))
        scale = pl.m.sub_scale or 1.0
        zrows = [(n, '', abs(scale - v) < .01, lambda _=0, v=v: pl.set_sub_scale(v)) for n, v in SUB_SIZES]
        speed = pl.m.speed or 1.0
        prows = [('Normal' if v == 1 else f'{v:g}×', '', abs(speed - v) < .01, lambda _=0, v=v: pl.set_speed(v)) for v in SPEEDS]
        self.lay.addWidget(self.column('Audio', arows, 250))
        self.lay.addWidget(self.column('Subtitles', srows, 260))
        self.lay.addWidget(self.column('Subtitle size', zrows, 130))
        self.lay.addWidget(self.column('Speed', prows, 110))
        self.adjustSize()


class UpNext(QWidget):
    play = pyqtSignal()
    dismiss = pyqtSignal()

    def __init__(self, player):
        super().__init__(player)
        self.player = player
        self.item, self.pix, self.left, self.total = None, None, 0, 0
        self.title, self.sub = '', ''
        self.setFixedSize(430, 150)
        self.btn_play = PillButton('Play now', 'play', 'light', self, h=34, px=13)
        self.btn_x = PillButton('Cancel', None, 'ghost', self, h=34, px=13)
        self.btn_play.clicked.connect(self.play)
        self.btn_x.clicked.connect(self.dismiss)
        self.timer = QTimer(self, interval=100, timeout=self._tick)
        self.hide()

    def start(self, item, title, sub, pix, seconds):
        self.item, self.title, self.sub, self.pix = item, title, sub, pix
        self.total = self.left = seconds
        self.btn_play.move(186, 104)
        self.btn_x.move(186 + self.btn_play.width() + 8, 104)
        self.show()
        self.raise_()
        self.timer.start()
        self.update()

    def stop(self):
        self.timer.stop()
        self.hide()

    def _tick(self):
        self.left -= 0.1
        if self.left <= 0:
            self.timer.stop()
            self.play.emit()
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect())
        p.setPen(QColor(255, 255, 255, 26))
        p.setBrush(QColor(16, 16, 22, 240))
        p.drawRoundedRect(r.adjusted(.5, .5, -.5, -.5), 14, 14)
        tr = QRectF(14, 14, 160, 90)
        p.save()
        p.setClipPath(rounded(tr, 8))
        if self.pix and not self.pix.isNull():
            pm = self.pix.scaled(int(tr.width() * 2), int(tr.height() * 2), Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                 Qt.TransformationMode.SmoothTransformation)
            p.drawPixmap(tr, pm, QRectF((pm.width() - tr.width() * 2) / 2, (pm.height() - tr.height() * 2) / 2,
                                        tr.width() * 2, tr.height() * 2))
        else:
            p.fillRect(tr, QColor(40, 40, 52))
        p.restore()
        p.setPen(QColor(MUTED))
        p.setFont(font(11, HEAVY))
        secs = max(0, int(self.left + .99))
        p.drawText(QRectF(186, 14, 230, 16), Qt.AlignmentFlag.AlignVCenter,
                   f'UP NEXT  ·  PLAYING IN {secs}' if self.timer.isActive() else 'UP NEXT')
        p.setPen(QColor(TEXT))
        p.setFont(font(15, BOLD))
        fm = QFontMetricsF(font(15, BOLD))
        p.drawText(QRectF(186, 34, 230, 22), Qt.AlignmentFlag.AlignVCenter,
                   fm.elidedText(self.title, Qt.TextElideMode.ElideRight, 230))
        p.setPen(QColor(MUTED))
        p.setFont(font(13))
        p.drawText(QRectF(186, 58, 230, 40), Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap, self.sub)
        if self.total and self.timer.isActive():
            frac = 1 - self.left / self.total
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(ACCENT))
            p.drawRoundedRect(QRectF(14, 112 + 26, (r.width() - 28) * frac, 3), 1.5, 1.5)


# ---------------------------------------------------------------- the player

class PlayerView(QWidget):
    closed = pyqtSignal()
    fullscreen = pyqtSignal()
    title_changed = pyqtSignal(str)
    _prop = pyqtSignal(str, object)
    _event = pyqtSignal(str, object)

    def __init__(self, main):
        super().__init__(main)
        self.main, self.store = main, main.store
        self.item = None
        self.tracks, self.chapters = [], []
        self.paused = False
        self.awake = KeepAwake()
        self.upnext_dismissed = False
        self.chapter_kind = ''
        self.is_fs = False
        self.remaining = False
        self.setStyleSheet('background:#000')
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        win = sys.platform == 'win32'
        self.video = MpvWidget(
            self, hwdec='auto-safe', keep_open='yes', idle='yes', osc=False, osd_level=0, config=False,
            load_scripts=False, ytdl=False, terminal=False, input_default_bindings=False, input_vo_keyboard=False,
            sub_auto='fuzzy', audio_file_auto='fuzzy', volume_max=150, demuxer_max_bytes='300MiB',
            sub_font='Segoe UI Semibold' if win else 'Helvetica Neue', sub_font_size=44, sub_border_size=2.6,
            sub_shadow_offset=1.2, sub_shadow_color='#99000000', sub_margin_y=44, sub_blur=0.2,
            screenshot_directory=os.path.join(os.path.expanduser('~'), 'Pictures'), screenshot_format='png')
        self.m = self.video.mpv
        try:
            self.m.command('apply-profile', 'high-quality')
        except Exception:
            pass
        self.m.deband = 'yes'
        self.m.volume = self.store.settings.data.get('volume', 100)
        self.m.sub_scale = self.store.settings.data.get('sub_scale', 1.0)
        self._prop.connect(self.on_prop)
        self._event.connect(self.on_event)
        for name in ('pause', 'eof-reached', 'track-list', 'chapter-list', 'chapter', 'volume', 'mute', 'speed',
                     'paused-for-cache'):
            self.m.observe_property(name, lambda n, v: self._prop.emit(n, v))

        @self.m.event_callback('file-loaded')
        def _loaded(ev):
            self._event.emit('loaded', None)

        @self.m.event_callback('end-file')
        def _ended(ev):
            if getattr(ev.data, 'reason', None) == mpv.MpvEventEndFile.ERROR:
                self._event.emit('error', None)
        self._cbs = (_loaded, _ended)

        # overlay ----------------------------------------------------------
        self.top = Gradient(self, True)
        tl = QHBoxLayout(self.top)
        tl.setContentsMargins(24, 18, 24, 18)
        tl.setSpacing(14)
        self.btn_back = IconButton('back', 44, 24)
        self.btn_back.clicked.connect(self.close_player)
        tl.addWidget(self.btn_back, 0, Qt.AlignmentFlag.AlignTop)
        tcol = QVBoxLayout()
        tcol.setSpacing(0)
        self.lbl_title = QLabel()
        self.lbl_title.setFont(font(20, BOLD))
        self.lbl_sub = QLabel()
        self.lbl_sub.setFont(font(14))
        for l, c in ((self.lbl_title, TEXT), (self.lbl_sub, '#c7c7d1')):
            l.setStyleSheet(f'color:{c};background:transparent')
            tcol.addWidget(l)
        tl.addLayout(tcol, 1)

        self.bottom = Gradient(self, False)
        bl = QVBoxLayout(self.bottom)
        bl.setContentsMargins(22, 28, 22, 14)
        bl.setSpacing(2)
        self.seekbar = SeekBar(self.bottom)
        self.seekbar.seek.connect(self.seek_abs)
        bl.addWidget(self.seekbar)
        row = QHBoxLayout()
        row.setSpacing(4)
        self.btn_play = IconButton('pause', 46, 26)
        self.btn_play.clicked.connect(self.toggle_pause)
        self.btn_rew = IconButton('rew', 42, 26, label='10')
        self.btn_rew.clicked.connect(lambda: self.seek_rel(-10))
        self.btn_fwd = IconButton('fwd', 42, 26, label='10')
        self.btn_fwd.clicked.connect(lambda: self.seek_rel(10))
        self.btn_next = IconButton('next', 42, 22)
        self.btn_next.clicked.connect(lambda: self.play_neighbour(1))
        self.btn_vol = IconButton('vol', 42, 22)
        self.btn_vol.clicked.connect(self.toggle_mute)
        self.vol = VolumeSlider(self.bottom)
        self.vol.changed.connect(self.set_volume)
        self.btn_time = TextButton('0:00 / 0:00', px=14)
        self.btn_time.clicked.connect(self.toggle_remaining)
        self.btn_speed = TextButton('1×', px=14)
        self.btn_speed.clicked.connect(self.toggle_panel)
        self.btn_cc = IconButton('cc', 42, 22)
        self.btn_cc.clicked.connect(self.toggle_panel)
        self.btn_fs = IconButton('fs', 42, 22)
        self.btn_fs.clicked.connect(self.fullscreen)
        for w in (self.btn_play, self.btn_rew, self.btn_fwd, self.btn_next, self.btn_vol, self.vol, self.btn_time):
            row.addWidget(w)
        row.addStretch(1)
        for w in (self.btn_speed, self.btn_cc, self.btn_fs):
            row.addWidget(w)
        bl.addLayout(row)

        self.panel = TracksPanel(self)
        self.toast = Toast(self)
        self.btn_skip = PillButton('Skip Intro', 'skip', 'outline', self, h=44, px=15)
        self.btn_skip.clicked.connect(self.skip_chapter)
        self.btn_skip.hide()
        self.upnext = UpNext(self)
        self.upnext.play.connect(lambda: self.play_neighbour(1))
        self.upnext.dismiss.connect(self.dismiss_upnext)

        self.fader = Fader([self.top, self.bottom], 200)
        self.hide_timer = QTimer(self, singleShot=True, interval=2600, timeout=self.auto_hide)
        self.tick_timer = QTimer(self, interval=250, timeout=self.tick)
        self.save_timer = QTimer(self, interval=5000, timeout=self.save_progress)

    # ---------------------------------------------------------- opening files
    def open(self, item, start=None):
        if self.item:
            self.save_progress()
        self.item = item
        self.upnext.stop()
        self.upnext_dismissed = False
        self.btn_skip.hide()
        self.chapter_kind = ''
        self.panel.hide()
        self.seekbar.chapters = []
        self.seekbar.set_state(0, self.store.duration(item), 0)
        pos = self.store.resume_pos(item) if start is None else start
        self._resumed = pos if pos > 15 else 0
        self._apply_prefs(item)
        title, sub = self.main.titles(item)
        self.lbl_title.setText(title)
        self.lbl_sub.setText(sub)
        self.title_changed.emit(title + (f' · {item.code}' if item.kind == 'episode' else ''))
        self.btn_next.setVisible(self.main.lib.neighbour(item, 1) is not None)
        opts = {'start': f'{pos:.2f}'} if pos > 15 else {}
        self.video.when_ready(lambda: (self.m.loadfile(item.src or item.path, 'replace', **opts), setattr(self.m, 'pause', False)))
        self.tick_timer.start()
        self.save_timer.start()
        self.setFocus()
        self.poke()

    def group(self, item):
        return item.show_key if item.kind == 'episode' else '_movies'

    def _apply_prefs(self, item):
        pref = self.store.settings.data['track_prefs'].get(self.group(item), {})
        self.m.sid = 'auto'
        self.m.aid = 'auto'
        self.m.alang = pref.get('audio') or ''
        sub = pref.get('sub')
        if sub == 'off':
            self.m.sid = 'no'
            self.m.slang = ''
        elif sub:
            self.m.slang = sub
            self.m.subs_with_matching_audio = 'yes'
        else:
            self.m.slang = ''

    # ---------------------------------------------------------- mpv events
    def on_event(self, kind, data):
        if kind == 'loaded':
            if self.item and self.item.src:
                self._remote_subs(self.item)
            if self._resumed:
                self.toast.flash(f'Resumed at {fmt_time(self._resumed)}  ·  Home to start over', 3200)
            self.tick()
            self._update_awake()
        elif kind == 'error':
            self.toast.flash(f"Can't reach {self.item.remote} - is Reel open there?" if self.item and self.item.remote
                             else "Can't play this file", 3500)

    def _remote_subs(self, item):
        """Streams can't see .srt files next to the video, so ask the other computer for them."""
        import threading, json, urllib.request
        base, _, q = item.src.partition('?')
        listing = base.replace('/v/', '/subs/') + '?' + q

        def run():
            try:
                names = json.loads(urllib.request.urlopen(listing, timeout=5).read())
            except Exception:
                return
            for i, n in enumerate(names):
                if self.item is not item:
                    return
                try:
                    self.m.command('sub-add', base.replace('/v/', '/sub/') + f'/{i}?' + q, 'auto', n)
                except Exception:
                    pass
        threading.Thread(target=run, daemon=True).start()

    def on_prop(self, name, v):
        if name == 'pause':
            self.paused = bool(v)
            self.btn_play.set_icon('play' if self.paused else 'pause')
            self._update_awake()
            self.poke()
        elif name == 'eof-reached':
            if v:
                self.on_eof()
        elif name == 'track-list':
            self.tracks = v or []
            self.btn_cc.active = any(t['type'] == 'sub' and t.get('selected') for t in self.tracks)
            self.btn_cc.update()
            if self.panel.isVisible():
                self.panel.rebuild()
                self.place()
        elif name == 'chapter-list':
            self.chapters = v or []
            self.seekbar.chapters = self.chapters
        elif name == 'chapter':
            self.on_chapter(v)
        elif name in ('volume', 'mute'):
            vol, mute = self.m.volume or 0, self.m.mute
            self.vol.set_value(0 if mute else vol)
            self.btn_vol.set_icon('mute' if mute or vol == 0 else 'vol-low' if vol < 50 else 'vol')
        elif name == 'speed':
            self.btn_speed.setText(f'{(v or 1):g}×')
        elif name == 'paused-for-cache' and v:
            self.toast.flash('Buffering…', 1200)

    def on_chapter(self, idx):
        self.chapter_kind = ''
        self.btn_skip.hide()
        if idx is None or idx < 0 or idx >= len(self.chapters):
            return
        title = self.chapters[idx].get('title') or ''
        if INTRO.search(title) and idx + 1 < len(self.chapters):
            recap = re.search(r'recap|previously', title, re.I)
            self.chapter_kind = 'intro'
            self.btn_skip.setText('Skip Recap' if recap else 'Skip Intro')
            self.btn_skip.show()
            self.btn_skip.raise_()
            self.place()
        elif CREDITS.search(title) and idx >= len(self.chapters) // 2:
            self.chapter_kind = 'credits'
            self.show_upnext(12)

    def skip_chapter(self):
        self.m.command('add', 'chapter', '1')
        self.btn_skip.hide()

    def on_eof(self):
        if not self.item:
            return
        self.store.set_progress(self.item, self.m.duration or 1, self.m.duration or 1)
        self.store.progress.save()
        if not self.show_upnext(6):
            self.poke()

    def show_upnext(self, seconds):
        nxt = self.main.lib.neighbour(self.item, 1) if self.item else None
        if not nxt or self.upnext_dismissed:
            return False
        if self.upnext.isVisible():  # credits countdown already running: hurry it at the very end
            self.upnext.left = min(self.upnext.left, seconds)
        else:
            show, sub = self.main.titles(nxt)
            code, _, name = sub.partition('  ·  ')
            blurb = '  ·  '.join(x for x in (show, code, self.main.episode_blurb(nxt)) if x)
            self.upnext.start(nxt, name or code, blurb, self.main.episode_pixmap(nxt), seconds)
            self.place()
        return True

    def dismiss_upnext(self):
        self.upnext_dismissed = True
        self.upnext.stop()

    # ---------------------------------------------------------- actions
    def tick(self):
        if not self.item:
            return
        pos, dur = self.m.time_pos, self.m.duration
        try:
            cache = self.m.demuxer_cache_time
        except Exception:
            cache = 0
        self.seekbar.set_state(pos, dur, cache)
        if dur:
            right = f'-{fmt_time(dur - (pos or 0))}' if self.remaining else fmt_time(dur)
            self.btn_time.setText(f'{fmt_time(pos)} / {right}')

    def save_progress(self):
        if not self.item:
            return
        pos, dur = self.m.time_pos, self.m.duration
        if pos is not None and dur and not self.m.eof_reached:
            self.store.set_progress(self.item, pos, dur)
            self.store.progress.save()

    def toggle_pause(self):
        if self.m.eof_reached:
            self.m.command('seek', '0', 'absolute')
        self.m.pause = not self.m.pause

    def seek_abs(self, t, exact):
        self.m.command('seek', f'{t:.2f}', 'absolute+exact' if exact else 'absolute+keyframes')
        self.poke()

    def seek_rel(self, s):
        self.m.command('seek', str(s), 'relative+exact')
        self.poke()
        pos = (self.m.time_pos or 0)
        self.toast.flash(f'{"+" if s > 0 else "−"}{abs(s)}s   {fmt_time(pos)}', 700)

    def set_volume(self, v):
        self.m.mute = False
        self.m.volume = v
        self.store.settings.data['volume'] = round(v)

    def change_volume(self, d):
        v = max(0, min(150, (self.m.volume or 0) + d))
        self.set_volume(v)
        self.toast.flash(f'Volume {v:.0f}%' + ('  (boost)' if v > 100 else ''), 900)

    def toggle_mute(self):
        self.m.mute = not self.m.mute
        self.toast.flash('Muted' if self.m.mute else f'Volume {self.m.volume:.0f}%', 900)

    def toggle_remaining(self):
        self.remaining = not self.remaining
        self.tick()

    def set_speed(self, v):
        self.m.speed = v
        self.panel.rebuild()
        self.toast.flash(f'Speed {v:g}×', 900)

    def set_sub_scale(self, v):
        self.m.sub_scale = v
        self.store.settings.data['sub_scale'] = v
        self.store.settings.save()
        self.panel.rebuild()

    def pick_track(self, kind, t):
        prefs = self.store.settings.data['track_prefs'].setdefault(self.group(self.item), {}) if self.item else {}
        if kind == 'sub':
            self.m.sid = t['id'] if t else 'no'
            prefs['sub'] = (t.get('lang') or 'auto') if t else 'off'
            if prefs['sub'] == 'auto':
                prefs.pop('sub')
            self.toast.flash('Subtitles: ' + (track_text(t)[0] if t else 'Off'), 1200)
        else:
            self.m.aid = t['id']
            if t.get('lang'):
                prefs['audio'] = t['lang']
            self.toast.flash('Audio: ' + track_text(t)[0], 1200)
        self.store.settings.save()

    def cycle(self, kind):
        ts = [t for t in self.tracks if t['type'] == kind]
        if not ts:
            self.toast.flash('No subtitles' if kind == 'sub' else 'No other audio', 900)
            return
        cur = next((i for i, t in enumerate(ts) if t.get('selected')), -1)
        if kind == 'sub':
            nxt = cur + 1
            self.pick_track('sub', ts[nxt] if nxt < len(ts) else None)
        else:
            self.pick_track('audio', ts[(cur + 1) % len(ts)])

    def load_sub_file(self):
        start = os.path.dirname(self.item.path) if self.item else ''
        f, _ = QFileDialog.getOpenFileName(self, 'Add subtitles', start,
                                           'Subtitles (*.srt *.ass *.ssa *.vtt *.sub *.sup);;All files (*)')
        if f:
            self.m.command('sub-add', f, 'select')
            self.toast.flash('Subtitles added', 1000)
        self.setFocus()

    def play_neighbour(self, step):
        nxt = self.main.lib.neighbour(self.item, step) if self.item else None
        if nxt:
            self.upnext.stop()
            self.open(nxt, start=None if not self.store.watched(nxt) else 0)
        else:
            self.toast.flash('No more episodes' if step > 0 else 'This is the first episode', 1000)

    def close_player(self):
        self.save_progress()
        self.store.settings.save()
        self.upnext.stop()
        self.tick_timer.stop()
        self.save_timer.stop()
        self.m.command('stop')
        self.item = None
        self.awake.set(False)
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.closed.emit()

    def _update_awake(self):
        self.awake.set(self.item is not None and not self.paused)

    def toggle_panel(self):
        if self.panel.isVisible():
            self.panel.hide()
        else:
            self.panel.rebuild()
            self.panel.show()
            self.panel.raise_()
            self.place()
        self.poke()

    def info(self):
        try:
            vp = self.m.video_params or {}
            parts = [f'{vp.get("w")}×{vp.get("h")}' if vp else '', (self.m.video_codec or '').split(' ')[0],
                     f'{self.m.container_fps:.3g} fps' if self.m.container_fps else '',
                     self.m.hwdec_current or 'software', vp.get('gamma', '') if vp.get('gamma') in ('pq', 'hlg') else '']
            self.toast.flash('   ·   '.join(p for p in parts if p), 3500)
        except Exception:
            pass

    def set_fs(self, on):
        self.is_fs = on
        self.btn_fs.set_icon('fs-exit' if on else 'fs')

    # ---------------------------------------------------------- input
    def video_clicked(self):
        if self.panel.isVisible():
            self.panel.hide()
            return
        self.toggle_pause()

    def video_double(self):
        self.toggle_pause()  # undo the single click's pause
        self.fullscreen.emit()

    def keyPressEvent(self, e):
        k, mod = e.key(), e.modifiers()
        K = Qt.Key
        shift = bool(mod & Qt.KeyboardModifier.ShiftModifier)
        if k in (K.Key_Space, K.Key_K, K.Key_MediaPlay, K.Key_MediaPause, K.Key_MediaTogglePlayPause):
            self.toggle_pause()
        elif k == K.Key_Left:
            self.seek_rel(-30 if shift else -5)
        elif k == K.Key_Right:
            self.seek_rel(30 if shift else 5)
        elif k == K.Key_J:
            self.seek_rel(-10)
        elif k == K.Key_L:
            self.seek_rel(10)
        elif k == K.Key_Up:
            self.change_volume(5)
        elif k == K.Key_Down:
            self.change_volume(-5)
        elif k == K.Key_M:
            self.toggle_mute()
        elif k in (K.Key_F, K.Key_F11) or (k == K.Key_Return and mod & Qt.KeyboardModifier.AltModifier):
            self.fullscreen.emit()
        elif k == K.Key_Escape:
            if self.panel.isVisible():
                self.panel.hide()
            elif self.is_fs:
                self.fullscreen.emit()
            else:
                self.close_player()
        elif k == K.Key_Backspace:
            self.close_player()
        elif k in (K.Key_S, K.Key_C):
            self.cycle('sub')
        elif k == K.Key_A:
            self.cycle('audio')
        elif k in (K.Key_N, K.Key_MediaNext):
            self.play_neighbour(1)
        elif k in (K.Key_P, K.Key_MediaPrevious):
            self.play_neighbour(-1)
        elif k == K.Key_BracketRight:
            self.set_speed(min(4, round((self.m.speed or 1) + .25, 2)))
        elif k == K.Key_BracketLeft:
            self.set_speed(max(.25, round((self.m.speed or 1) - .25, 2)))
        elif k == K.Key_Equal:
            self.set_speed(1.0)
        elif k == K.Key_Period:
            self.m.frame_step()
        elif k == K.Key_Comma:
            self.m.frame_back_step()
        elif k in (K.Key_G, K.Key_H):
            d = (self.m.sub_delay or 0) + (-.1 if k == K.Key_G else .1)
            self.m.sub_delay = d
            self.toast.flash(f'Subtitle delay {d * 1000:+.0f} ms', 900)
        elif k == K.Key_Home:
            self.m.command('seek', '0', 'absolute')
            self.toast.flash('Starting over', 900)
        elif k == K.Key_I:
            self.info()
        elif k == K.Key_Tab or k == K.Key_T:
            self.toggle_panel()
        elif K.Key_0 <= k <= K.Key_9 and not mod & Qt.KeyboardModifier.ControlModifier:
            dur = self.m.duration
            if dur:
                self.seek_abs(dur * (k - K.Key_0) / 10, True)
        else:
            return super().keyPressEvent(e)
        self.poke()

    def mouseMoveEvent(self, e):
        self.poke()

    def poke(self):
        if self.cursor().shape() == Qt.CursorShape.BlankCursor:
            self.setCursor(Qt.CursorShape.ArrowCursor)
            self.video.setCursor(Qt.CursorShape.ArrowCursor)
        self.fader.show(True)
        self.hide_timer.start()

    def auto_hide(self):
        over = any(w.isVisible() and w.underMouse() for w in (self.top, self.bottom, self.panel, self.upnext))
        if self.paused or self.panel.isVisible() or over or not self.item:
            self.hide_timer.start()
            return
        self.fader.show(False)
        self.setCursor(Qt.CursorShape.BlankCursor)
        self.video.setCursor(Qt.CursorShape.BlankCursor)

    # ---------------------------------------------------------- layout
    def resizeEvent(self, e):
        self.place()

    def place(self):
        w, h = self.width(), self.height()
        self.video.setGeometry(0, 0, w, h)
        self.top.setGeometry(0, 0, w, 96)
        self.bottom.setGeometry(0, h - 128, w, 128)
        if self.panel.isVisible():
            ps = self.panel.sizeHint()
            pw, ph = min(ps.width(), w - 32), min(ps.height(), h - 180)
            self.panel.setGeometry(w - pw - 24, h - 128 - ph - 4, pw, ph)
        self.btn_skip.move(w - self.btn_skip.width() - 40, h - 128 - self.btn_skip.height() - 24)
        self.upnext.move(w - self.upnext.width() - 32, h - 128 - self.upnext.height() - 16)
        for wd in (self.top, self.bottom, self.btn_skip, self.upnext, self.panel):
            wd.raise_()
