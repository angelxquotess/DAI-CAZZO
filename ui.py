from __future__ import annotations

import json
import math
import os
import platform
import random
import subprocess
import sys
import threading
import time
from pathlib import Path

import psutil

from PyQt6.QtCore import (
    QEasingCurve, QMimeData, QObject, QPointF, QRectF, QSize, Qt,
    QTimer, QUrl, pyqtSignal,
)
from PyQt6.QtGui import (
    QBrush, QColor, QDragEnterEvent, QDropEvent, QFont, QFontDatabase,
    QKeySequence, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap,
    QRadialGradient, QShortcut,
)
from PyQt6.QtWidgets import (
    QApplication, QFileDialog, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QMainWindow, QPushButton, QScrollArea, QSizePolicy, QTextEdit,
    QVBoxLayout, QWidget, QProgressBar,
)

# QWebEngineView e' opzionale: serve per la mappa 3D nella stessa finestra.
# Se non e' installato (pip install PyQt6-WebEngine), si usa un fallback.
try:
    from PyQt6.QtWebEngineWidgets import QWebEngineView  # type: ignore
    _HAS_WEBENGINE = True
except Exception as _e:
    QWebEngineView = None  # type: ignore
    _HAS_WEBENGINE = False
    print(f"[ui] PyQt6-WebEngine non disponibile, mappa 3D in fallback: {_e}")

def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent

BASE_DIR   = _base_dir()
CONFIG_DIR = BASE_DIR / "config"
API_FILE   = CONFIG_DIR / "api_keys.json"

_DEFAULT_W, _DEFAULT_H = 980, 700
_MIN_W,     _MIN_H     = 820, 580
_LEFT_W  = 148
_RIGHT_W = 340

_OS = platform.system()  # "Windows" | "Darwin" | "Linux"


class C:
    BG        = "#00060a"
    PANEL     = "#010d14"
    PANEL2    = "#010f18"
    BORDER    = "#0d3347"
    BORDER_B  = "#1a5c7a"
    BORDER_A  = "#0f4060"
    PRI       = "#00d4ff"
    PRI_DIM   = "#007a99"
    PRI_GHO   = "#001f2e"
    ACC       = "#ff6b00"
    ACC2      = "#ffcc00"
    GREEN     = "#00ff88"
    GREEN_D   = "#00aa55"
    RED       = "#ff3355"
    MUTED_C   = "#ff3366"
    TEXT      = "#8ffcff"
    TEXT_DIM  = "#3a8a9a"
    TEXT_MED  = "#5ab8cc"
    WHITE     = "#d8f8ff"
    DARK      = "#000d14"
    BAR_BG    = "#011520"


def qcol(h: str, a: int = 255) -> QColor:
    c = QColor(h); c.setAlpha(a); return c

class _SysMetrics:
    def __init__(self):
        self.cpu  = 0.0
        self.mem  = 0.0
        self.net  = 0.0   
        self.gpu  = -1.0  
        self.tmp  = -1.0  
        self._lock = threading.Lock()
        self._last_net = psutil.net_io_counters()
        self._last_net_t = time.time()
        self._running = True
        t = threading.Thread(target=self._loop, daemon=True)
        t.start()

    def _loop(self):
        while self._running:
            try:
                self._update()
            except Exception:
                pass
            time.sleep(1.5)

    def _update(self):
        cpu = psutil.cpu_percent(interval=None)
        mem = psutil.virtual_memory().percent

        nc  = psutil.net_io_counters()
        now = time.time()
        dt  = now - self._last_net_t
        if dt > 0:
            sent = (nc.bytes_sent - self._last_net.bytes_sent) / dt
            recv = (nc.bytes_recv - self._last_net.bytes_recv) / dt
            net  = (sent + recv) / (1024 * 1024)
        else:
            net = 0.0
        self._last_net   = nc
        self._last_net_t = now

        gpu = self._get_gpu()

        tmp = self._get_temp()

        with self._lock:
            self.cpu = cpu
            self.mem = mem
            self.net = net
            self.gpu = gpu
            self.tmp = tmp

    def _get_gpu(self) -> float:
        # NVIDIA
        try:
            r = subprocess.run(
                ["nvidia-smi", "--query-gpu=utilization.gpu",
                 "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=2
            )
            if r.returncode == 0:
                vals = [float(v.strip()) for v in r.stdout.strip().split("\n") if v.strip()]
                if vals:
                    return sum(vals) / len(vals)
        except Exception:
            pass

        # AMD (Linux)
        if _OS == "Linux":
            try:
                r = subprocess.run(
                    ["rocm-smi", "--showuse", "--csv"],
                    capture_output=True, text=True, timeout=2
                )
                if r.returncode == 0:
                    for line in r.stdout.strip().split("\n"):
                        parts = line.split(",")
                        if len(parts) >= 2:
                            try:
                                return float(parts[1].strip().replace("%", ""))
                            except ValueError:
                                pass
            except Exception:
                pass

            # Intel GPU (Linux)
            try:
                r = subprocess.run(
                    ["intel_gpu_top", "-J", "-s", "500"],
                    capture_output=True, text=True, timeout=1
                )
                if r.returncode == 0 and "Render/3D" in r.stdout:
                    import re
                    m = re.search(r'"busy":\s*([\d.]+)', r.stdout)
                    if m:
                        return float(m.group(1))
            except Exception:
                pass

        # macOS — powermetrics (GPU Engine)
        if _OS == "Darwin":
            try:
                r = subprocess.run(
                    ["sudo", "-n", "powermetrics", "-n", "1", "-i", "500",
                     "--samplers", "gpu_power"],
                    capture_output=True, text=True, timeout=2
                )
                if r.returncode == 0 and "GPU" in r.stdout:
                    import re
                    m = re.search(r'GPU\s+Active:\s+([\d.]+)%', r.stdout)
                    if m:
                        return float(m.group(1))
            except Exception:
                pass

        return -1.0

    def _get_temp(self) -> float:
        try:
            temps = psutil.sensors_temperatures()
            candidates = ["coretemp", "k10temp", "cpu_thermal", "acpitz",
                          "cpu-thermal", "zenpower", "it8688"]
            for name in candidates:
                if name in temps:
                    entries = temps[name]
                    if entries:
                        return entries[0].current
            for entries in temps.values():
                if entries:
                    return entries[0].current
        except Exception:
            pass
        if _OS == "Darwin":
            try:
                r = subprocess.run(
                    ["osx-cpu-temp"], capture_output=True, text=True, timeout=2
                )
                if r.returncode == 0:
                    import re
                    m = re.search(r"([\d.]+)", r.stdout)
                    if m:
                        return float(m.group(1))
            except Exception:
                pass

        if _OS == "Windows":
            try:
                r = subprocess.run(
                    ["powershell", "-Command",
                     "(Get-WmiObject MSAcpi_ThermalZoneTemperature -Namespace root/wmi).CurrentTemperature"],
                    capture_output=True, text=True, timeout=3
                )
                if r.returncode == 0 and r.stdout.strip():
                    raw = float(r.stdout.strip().split("\n")[0])
                    return (raw / 10.0) - 273.15
            except Exception:
                pass

        return -1.0

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "cpu": self.cpu,
                "mem": self.mem,
                "net": self.net,
                "gpu": self.gpu,
                "tmp": self.tmp,
            }


_metrics = _SysMetrics()

class HudCanvas(QWidget):
    def __init__(self, face_path: str, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
        self.setMinimumSize(300, 300)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self.muted    = False
        self.speaking = False
        self.state    = "INITIALISING"

        self._tick       = 0
        self._scale      = 1.0
        self._tgt_scale  = 1.0
        self._halo       = 55.0
        self._tgt_halo   = 55.0
        self._last_t     = time.time()
        self._scan       = 0.0
        self._scan2      = 180.0
        self._rings      = [0.0, 120.0, 240.0]
        self._pulses: list[float] = [0.0, 50.0, 100.0]
        self._blink      = True
        self._blink_tick = 0
        self._particles: list[list[float]] = []
        self._face_px: QPixmap | None = None
        self._load_face(face_path)

        self._tmr = QTimer(self)
        self._tmr.timeout.connect(self._step)
        # CPU-friendly: 30 fps invece di 60 fps per l'animazione del viso.
        self._tmr.start(33)

    def _load_face(self, path: str):
        try:
            from PIL import Image, ImageDraw
            import io
            img = Image.open(path).convert("RGBA")
            sz  = min(img.size)
            img = img.resize((sz, sz), Image.LANCZOS)
            mk  = Image.new("L", (sz, sz), 0)
            ImageDraw.Draw(mk).ellipse((2, 2, sz - 2, sz - 2), fill=255)
            img.putalpha(mk)
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            px = QPixmap(); px.loadFromData(buf.getvalue())
            self._face_px = px
        except Exception:
            self._face_px = None

    def _step(self):
        self._tick += 1
        now = time.time()
        if now - self._last_t > (0.12 if self.speaking else 0.5):
            if self.speaking:
                self._tgt_scale = random.uniform(1.06, 1.14)
                self._tgt_halo  = random.uniform(145, 190)
            elif self.muted:
                self._tgt_scale = random.uniform(0.998, 1.002)
                self._tgt_halo  = random.uniform(15, 28)
            else:
                self._tgt_scale = random.uniform(1.001, 1.008)
                self._tgt_halo  = random.uniform(48, 68)
            self._last_t = now

        sp = 0.38 if self.speaking else 0.15
        self._scale += (self._tgt_scale - self._scale) * sp
        self._halo  += (self._tgt_halo  - self._halo)  * sp

        speeds = [1.3, -0.9, 2.0] if self.speaking else [0.55, -0.35, 0.9]
        for i, spd in enumerate(speeds):
            self._rings[i] = (self._rings[i] + spd) % 360

        self._scan  = (self._scan  + (3.0 if self.speaking else 1.3)) % 360
        self._scan2 = (self._scan2 + (-2.0 if self.speaking else -0.75)) % 360

        fw  = min(self.width(), self.height())
        lim = fw * 0.74
        spd = 4.2 if self.speaking else 2.0
        self._pulses = [r + spd for r in self._pulses if r + spd < lim]
        if len(self._pulses) < 3 and random.random() < (0.07 if self.speaking else 0.025):
            self._pulses.append(0.0)

        if self.speaking and random.random() < 0.28:
            cx, cy = self.width() / 2, self.height() / 2
            ang = random.uniform(0, 2 * math.pi)
            r_s = fw * 0.28
            self._particles.append([
                cx + math.cos(ang) * r_s, cy + math.sin(ang) * r_s,
                math.cos(ang) * random.uniform(0.9, 2.4),
                math.sin(ang) * random.uniform(0.9, 2.4) - 0.4, 1.0,
            ])
        self._particles = [
            [p[0]+p[2], p[1]+p[3], p[2]*0.97, p[3]*0.97, p[4]-0.028]
            for p in self._particles if p[4] > 0
        ]

        self._blink_tick += 1
        if self._blink_tick >= 38:
            self._blink = not self._blink
            self._blink_tick = 0
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), qcol(C.BG))

        W, H = self.width(), self.height()
        cx, cy = W / 2, H / 2
        fw = min(W, H)

        # grid dots
        p.setPen(QPen(qcol(C.PRI_GHO), 1))
        for x in range(0, W, 48):
            for y in range(0, H, 48):
                p.drawPoint(x, y)

        r_face = fw * 0.31

        # halo glow
        for i in range(10):
            r   = r_face * (1.8 - i * 0.08)
            frc = 1.0 - i / 10
            a   = max(0, min(255, int(self._halo * 0.085 * frc)))
            col = qcol(C.MUTED_C if self.muted else C.PRI, a)
            p.setPen(QPen(col, 1.5)); p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QRectF(cx - r, cy - r, r * 2, r * 2))

        # pulse rings
        for pr in self._pulses:
            a   = max(0, int(230 * (1.0 - pr / (fw * 0.74))))
            col = qcol(C.MUTED_C if self.muted else C.PRI, a)
            p.setPen(QPen(col, 1.5)); p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QRectF(cx - pr, cy - pr, pr * 2, pr * 2))

        # spinning arc rings
        for idx, (r_frac, w_r, arc_l, gap) in enumerate(
            [(0.48, 3, 115, 78), (0.40, 2, 78, 55), (0.32, 1, 56, 40)]
        ):
            ring_r = fw * r_frac
            base   = self._rings[idx]
            a_val  = max(0, min(255, int(self._halo * (1.0 - idx * 0.18))))
            col    = qcol(C.MUTED_C if self.muted else C.PRI, a_val)
            p.setPen(QPen(col, w_r)); p.setBrush(Qt.BrushStyle.NoBrush)
            angle = base
            rect  = QRectF(cx - ring_r, cy - ring_r, ring_r * 2, ring_r * 2)
            while angle < base + 360:
                p.drawArc(rect, int(angle * 16), int(arc_l * 16))
                angle += arc_l + gap

        # scanners
        sr = fw * 0.50
        sa = min(255, int(self._halo * 1.5))
        ex = 75 if self.speaking else 44
        p.setPen(QPen(qcol(C.MUTED_C if self.muted else C.PRI, sa), 2.5))
        p.setBrush(Qt.BrushStyle.NoBrush)
        srect = QRectF(cx - sr, cy - sr, sr * 2, sr * 2)
        p.drawArc(srect, int(self._scan * 16), int(ex * 16))
        p.setPen(QPen(qcol(C.ACC, sa // 2), 1.5))
        p.drawArc(srect, int(self._scan2 * 16), int(ex * 16))

        # tick marks
        t_out, t_in = fw * 0.497, fw * 0.474
        p.setPen(QPen(qcol(C.PRI, 140), 1))
        for deg in range(0, 360, 10):
            rad = math.radians(deg)
            inn = t_in if deg % 30 == 0 else t_in + 6
            p.drawLine(
                QPointF(cx + t_out * math.cos(rad), cy - t_out * math.sin(rad)),
                QPointF(cx + inn  * math.cos(rad), cy - inn  * math.sin(rad)),
            )

        # crosshair
        ch_r, gap_h = fw * 0.51, fw * 0.16
        p.setPen(QPen(qcol(C.PRI, int(self._halo * 0.5)), 1))
        p.drawLine(QPointF(cx - ch_r, cy), QPointF(cx - gap_h, cy))
        p.drawLine(QPointF(cx + gap_h, cy), QPointF(cx + ch_r, cy))
        p.drawLine(QPointF(cx, cy - ch_r), QPointF(cx, cy - gap_h))
        p.drawLine(QPointF(cx, cy + gap_h), QPointF(cx, cy + ch_r))

        # corner brackets
        bl = 24
        bc = qcol(C.PRI, 210)
        hl, hr = cx - fw // 2, cx + fw // 2
        ht, hb = cy - fw // 2, cy + fw // 2
        p.setPen(QPen(bc, 2))
        for bx, by, dx, dy in [(hl,ht,1,1),(hr,ht,-1,1),(hl,hb,1,-1),(hr,hb,-1,-1)]:
            p.drawLine(QPointF(bx, by), QPointF(bx + dx * bl, by))
            p.drawLine(QPointF(bx, by), QPointF(bx, by + dy * bl))

        # face
        if self._face_px:
            fsz    = int(fw * 0.62 * self._scale)
            scaled = self._face_px.scaled(
                fsz, fsz,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            p.drawPixmap(int(cx - fsz / 2), int(cy - fsz / 2), scaled)
        else:
            orb_r = int(fw * 0.27 * self._scale)
            oc    = (200, 0, 50) if self.muted else (0, 60, 110)
            for i in range(8, 0, -1):
                r2  = int(orb_r * i / 8)
                frc = i / 8
                a   = max(0, min(255, int(self._halo * 1.1 * frc)))
                p.setBrush(QBrush(QColor(int(oc[0]*frc), int(oc[1]*frc), int(oc[2]*frc), a)))
                p.setPen(Qt.PenStyle.NoPen)
                p.drawEllipse(QRectF(cx - r2, cy - r2, r2 * 2, r2 * 2))
            p.setPen(QPen(qcol(C.PRI, min(255, int(self._halo * 2))), 1))
            p.setFont(QFont("Courier New", 13, QFont.Weight.Bold))
            p.drawText(QRectF(cx - 80, cy - 14, 160, 28),
                       Qt.AlignmentFlag.AlignCenter, "J.A.R.V.I.S")

        # particles
        for pt in self._particles:
            a = max(0, min(255, int(pt[4] * 255)))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(qcol(C.PRI, a)))
            p.drawEllipse(QPointF(pt[0], pt[1]), 2.5, 2.5)

        # status text
        sy = cy + fw * 0.40
        if self.muted:
            txt, col = "⊘  MUTED",     qcol(C.MUTED_C)
        elif self.speaking:
            txt, col = "●  SPEAKING",  qcol(C.ACC)
        elif self.state == "THINKING":
            sym = "◈" if self._blink else "◇"
            txt, col = f"{sym}  THINKING",   qcol(C.ACC2)
        elif self.state == "PROCESSING":
            sym = "▷" if self._blink else "▶"
            txt, col = f"{sym}  PROCESSING", qcol(C.ACC2)
        elif self.state == "LISTENING":
            sym = "●" if self._blink else "○"
            txt, col = f"{sym}  LISTENING",  qcol(C.GREEN)
        else:
            sym = "●" if self._blink else "○"
            txt, col = f"{sym}  {self.state}", qcol(C.PRI)

        p.setPen(QPen(col, 1))
        p.setFont(QFont("Courier New", 11, QFont.Weight.Bold))
        p.drawText(QRectF(0, sy, W, 26), Qt.AlignmentFlag.AlignCenter, txt)

        # waveform
        wy = sy + 30
        N, bw = 36, 8
        wx0 = (W - N * bw) / 2
        for i in range(N):
            if self.muted:
                hgt, cl = 2, qcol(C.MUTED_C)
            elif self.speaking:
                hgt = random.randint(3, 20)
                cl  = qcol(C.PRI) if hgt > 12 else qcol(C.PRI_DIM)
            else:
                hgt = int(3 + 2 * math.sin(self._tick * 0.09 + i * 0.6))
                cl  = qcol(C.BORDER_B)
            p.fillRect(QRectF(wx0 + i * bw, wy + 20 - hgt, bw - 1, hgt), cl)

class MetricBar(QWidget):

    def __init__(self, label: str, color: str = C.PRI, parent=None):
        super().__init__(parent)
        self._label = label
        self._color = color
        self._value = 0.0       # 0–100
        self._text  = "--"
        self.setFixedHeight(38)
        self.setMinimumWidth(80)

    def set_value(self, pct: float, text: str):
        self._value = max(0.0, min(100.0, pct))
        self._text  = text
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        W, H = self.width(), self.height()

        p.setBrush(QBrush(qcol(C.PANEL2)))
        p.setPen(QPen(qcol(C.BORDER_A), 1))
        p.drawRoundedRect(QRectF(1, 1, W - 2, H - 2), 4, 4)

        bar_h   = 4
        bar_y   = H - bar_h - 5
        bar_w   = W - 12
        bar_x   = 6
        fill_w  = int(bar_w * self._value / 100)

        p.setBrush(QBrush(qcol(C.BAR_BG)))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(QRectF(bar_x, bar_y, bar_w, bar_h), 2, 2)

        if self._value > 85:
            bar_col = qcol(C.RED)
        elif self._value > 65:
            bar_col = qcol(C.ACC)
        else:
            bar_col = qcol(self._color)

        if fill_w > 0:
            p.setBrush(QBrush(bar_col))
            p.drawRoundedRect(QRectF(bar_x, bar_y, fill_w, bar_h), 2, 2)

        p.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
        p.setPen(QPen(qcol(C.TEXT_DIM), 1))
        p.drawText(QRectF(8, 5, 50, 14), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self._label)

        p.setFont(QFont("Courier New", 9, QFont.Weight.Bold))
        p.setPen(QPen(bar_col if self._text != "--" else qcol(C.TEXT_DIM), 1))
        p.drawText(QRectF(0, 4, W - 6, 16), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, self._text)

class LogWidget(QTextEdit):
    _sig = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setFont(QFont("Courier New", 9))
        self.setStyleSheet(f"""
            QTextEdit {{
                background: {C.PANEL};
                color: {C.TEXT};
                border: 1px solid {C.BORDER};
                border-radius: 4px;
                padding: 6px;
                selection-background-color: {C.PRI_GHO};
            }}
            QScrollBar:vertical {{
                background: {C.BG};
                width: 8px;
                border: none;
            }}
            QScrollBar::handle:vertical {{
                background: {C.BORDER_B};
                border-radius: 4px;
                min-height: 20px;
            }}
        """)
        self._queue: list[str] = []
        self._typing  = False
        self._text    = ""
        self._pos     = 0
        self._tag     = "sys"
        self._tmr = QTimer(self)
        self._tmr.timeout.connect(self._step)
        self._sig.connect(self._enqueue)

    def append_log(self, text: str):
        self._sig.emit(text)

    def _enqueue(self, text: str):
        self._queue.append(text)
        if not self._typing:
            self._next()

    def _next(self):
        if not self._queue:
            self._typing = False
            return
        self._typing = True
        self._text   = self._queue.pop(0)
        self._pos    = 0
        tl = self._text.lower()
        if   tl.startswith("you:"):    self._tag = "you"
        elif tl.startswith("jarvis:"): self._tag = "ai"
        elif tl.startswith("file:"):   self._tag = "file"
        elif "err" in tl:              self._tag = "err"
        else:                          self._tag = "sys"
        # CPU-friendly: typewriter a ~40fps (25ms) invece di ~166fps (6ms).
        self._tmr.start(25)

    def _step(self):
        if self._pos < len(self._text):
            ch  = self._text[self._pos]
            cur = self.textCursor()
            fmt = cur.charFormat()
            col = {
                "you":  qcol(C.WHITE),
                "ai":   qcol(C.PRI),
                "err":  qcol(C.RED),
                "file": qcol(C.GREEN),
                "sys":  qcol(C.ACC2),
            }.get(self._tag, qcol(C.TEXT))
            fmt.setForeground(QBrush(col))
            cur.movePosition(cur.MoveOperation.End)
            cur.insertText(ch, fmt)
            self.setTextCursor(cur)
            self.ensureCursorVisible()
            self._pos += 1
        else:
            self._tmr.stop()
            cur = self.textCursor()
            cur.movePosition(cur.MoveOperation.End)
            cur.insertText("\n")
            self.setTextCursor(cur)
            self.ensureCursorVisible()
            QTimer.singleShot(20, self._next)

_FILE_ICONS = {
    "image":   ("🖼", "#00d4ff"), "video":   ("🎬", "#ff6b00"),
    "audio":   ("🎵", "#cc44ff"), "pdf":     ("📄", "#ff4444"),
    "word":    ("📝", "#4488ff"), "excel":   ("📊", "#44bb44"),
    "code":    ("💻", "#ffcc00"), "archive": ("📦", "#ff8844"),
    "pptx":    ("📊", "#ff6622"), "text":    ("📃", "#aaaaaa"),
    "data":    ("🔧", "#88ddff"), "unknown": ("📎", "#888888"),
}
_EXT_TO_CAT = {
    **dict.fromkeys(["jpg","jpeg","png","gif","webp","bmp","tiff","svg","ico"], "image"),
    **dict.fromkeys(["mp4","avi","mov","mkv","wmv","flv","webm","m4v"],         "video"),
    **dict.fromkeys(["mp3","wav","ogg","m4a","aac","flac","wma","opus"],        "audio"),
    **dict.fromkeys(["pdf"],                                                     "pdf"),
    **dict.fromkeys(["doc","docx"],                                              "word"),
    **dict.fromkeys(["xls","xlsx","ods"],                                        "excel"),
    **dict.fromkeys(["ppt","pptx"],                                              "pptx"),
    **dict.fromkeys(["py","js","ts","jsx","tsx","html","css","java","c","cpp",
                     "cs","go","rs","rb","php","swift","kt","sh","sql","lua"],   "code"),
    **dict.fromkeys(["zip","rar","tar","gz","7z","bz2","xz"],                   "archive"),
    **dict.fromkeys(["txt","md","rst","log"],                                    "text"),
    **dict.fromkeys(["csv","tsv","json","xml"],                                  "data"),
}

def _file_category(path: Path) -> str:
    return _EXT_TO_CAT.get(path.suffix.lower().lstrip("."), "unknown")

def _fmt_size(size: int) -> str:
    if   size < 1024:    return f"{size} B"
    elif size < 1024**2: return f"{size/1024:.1f} KB"
    elif size < 1024**3: return f"{size/1024**2:.1f} MB"
    else:                return f"{size/1024**3:.1f} GB"


class FileDropZone(QWidget):
    file_selected = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(100)
        self._current_file: str | None = None
        self._hovering  = False
        self._drag_over = False
        self._dash_offset = 0.0
        self._anim_tmr = QTimer(self)
        self._anim_tmr.timeout.connect(self._animate)
        self._anim_tmr.start(40)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self._canvas = _DropCanvas(self)
        layout.addWidget(self._canvas)

    def _animate(self):
        self._dash_offset = (self._dash_offset + 0.8) % 20
        self._canvas.update()

    def dragEnterEvent(self, e: QDragEnterEvent):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
            self._drag_over = True; self._canvas.update()

    def dragLeaveEvent(self, e):
        self._drag_over = False; self._canvas.update()

    def dropEvent(self, e: QDropEvent):
        self._drag_over = False
        urls = e.mimeData().urls()
        if urls:
            path = urls[0].toLocalFile()
            if Path(path).is_file():
                self._set_file(path)
        self._canvas.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._browse()

    def enterEvent(self, e):
        self._hovering = True; self._canvas.update()

    def leaveEvent(self, e):
        self._hovering = False; self._canvas.update()

    def current_file(self) -> str | None:
        return self._current_file

    def clear_file(self):
        self._current_file = None; self._canvas.update()

    def _browse(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select a file for JARVIS", str(Path.home()),
            "All Files (*.*);;"
            "Images (*.jpg *.jpeg *.png *.gif *.webp *.bmp *.svg);;"
            "Documents (*.pdf *.docx *.txt *.md *.pptx);;"
            "Data (*.csv *.xlsx *.json *.xml);;"
            "Code (*.py *.js *.ts *.html *.css *.java *.cpp *.go);;"
            "Audio (*.mp3 *.wav *.ogg *.m4a *.aac *.flac);;"
            "Video (*.mp4 *.avi *.mov *.mkv *.wmv *.webm);;"
            "Archives (*.zip *.rar *.tar *.gz *.7z)",
        )
        if path:
            self._set_file(path)

    def _set_file(self, path: str):
        self._current_file = path
        self._canvas.update()
        self.file_selected.emit(path)


class _DropCanvas(QWidget):
    def __init__(self, zone: FileDropZone):
        super().__init__(zone)
        self._z = zone

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        z    = self._z
        W, H = self.width(), self.height()
        pad  = 6
        rect = QRectF(pad, pad, W - pad * 2, H - pad * 2)

        bg_col = qcol("#001a24" if z._drag_over else ("#001218" if z._hovering else C.PANEL))
        p.setBrush(QBrush(bg_col)); p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(rect, 6, 6)

        if z._current_file:   border_col = qcol(C.GREEN, 200)
        elif z._drag_over:    border_col = qcol(C.PRI, 230)
        elif z._hovering:     border_col = qcol(C.BORDER_B, 200)
        else:                 border_col = qcol(C.BORDER, 160)

        pen = QPen(border_col, 1.5, Qt.PenStyle.DashLine)
        pen.setDashOffset(z._dash_offset)
        p.setPen(pen); p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(rect, 6, 6)

        if z._current_file:   self._paint_file(p, W, H)
        elif z._drag_over:    self._paint_drag_over(p, W, H)
        else:                 self._paint_idle(p, W, H, z._hovering)

    def _paint_idle(self, p, W, H, hover):
        cx, cy = W / 2, H / 2
        col = qcol(C.PRI_DIM if not hover else C.PRI)
        p.setPen(QPen(col, 2)); p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawLine(QPointF(cx, cy - 14), QPointF(cx, cy + 4))
        p.drawLine(QPointF(cx - 8, cy - 6), QPointF(cx, cy - 14))
        p.drawLine(QPointF(cx + 8, cy - 6), QPointF(cx, cy - 14))
        p.drawLine(QPointF(cx - 14, cy + 4), QPointF(cx + 14, cy + 4))
        p.setFont(QFont("Courier New", 8))
        p.setPen(QPen(qcol(C.PRI_DIM if not hover else C.TEXT), 1))
        p.drawText(QRectF(0, cy + 8, W, 16), Qt.AlignmentFlag.AlignCenter,
                   "Drop file here  or  Click to Browse")
        p.setFont(QFont("Courier New", 7))
        p.setPen(QPen(qcol("#1a4a5a"), 1))
        p.drawText(QRectF(0, cy + 24, W, 14), Qt.AlignmentFlag.AlignCenter,
                   "Images · Video · Audio · PDF · Docs · Code · Data")

    def _paint_drag_over(self, p, W, H):
        cx, cy = W / 2, H / 2
        p.setFont(QFont("Courier New", 20))
        p.setPen(QPen(qcol(C.PRI), 1))
        p.drawText(QRectF(0, cy - 24, W, 32), Qt.AlignmentFlag.AlignCenter, "⬇")
        p.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        p.setPen(QPen(qcol(C.PRI), 1))
        p.drawText(QRectF(0, cy + 12, W, 16), Qt.AlignmentFlag.AlignCenter, "Release to load")

    def _paint_file(self, p, W, H):
        path = Path(self._z._current_file)
        cat  = _file_category(path)
        icon, icon_col = _FILE_ICONS.get(cat, _FILE_ICONS["unknown"])
        size_str = _fmt_size(path.stat().st_size)
        ext_str  = path.suffix.upper().lstrip(".") or "FILE"

        block_x, block_w = 10, 60
        p.setFont(QFont("Segoe UI Emoji", 22) if _OS == "Windows" else QFont("Arial", 22))
        p.setPen(QPen(qcol(icon_col), 1))
        p.drawText(QRectF(block_x, 0, block_w, H), Qt.AlignmentFlag.AlignCenter, icon)

        tx = block_x + block_w + 6
        tw = W - tx - 38

        p.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        p.setPen(QPen(qcol(C.WHITE), 1))
        name = path.name if len(path.name) <= 34 else path.name[:31] + "..."
        p.drawText(QRectF(tx, H * 0.18, tw, 16),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, name)

        p.setFont(QFont("Courier New", 7))
        p.setPen(QPen(qcol(C.TEXT_DIM), 1))
        p.drawText(QRectF(tx, H * 0.18 + 18, tw, 14),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   f"{ext_str}  ·  {size_str}")

        p.setFont(QFont("Courier New", 6))
        p.setPen(QPen(qcol("#1e5c6a"), 1))
        par = str(path.parent)
        if len(par) > 42: par = "…" + par[-41:]
        p.drawText(QRectF(tx, H * 0.18 + 34, tw, 12),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, par)

        p.setFont(QFont("Courier New", 9, QFont.Weight.Bold))
        p.setPen(QPen(qcol(C.RED, 180), 1))
        p.drawText(QRectF(W - 34, 0, 28, H), Qt.AlignmentFlag.AlignCenter, "✕")

    def mousePressEvent(self, e):
        z = self._z
        if z._current_file and e.pos().x() > self.width() - 34:
            z.clear_file()
        else:
            z.mousePressEvent(e)


class SetupOverlay(QWidget):
    done = pyqtSignal(str, str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"""
            SetupOverlay {{
                background: rgba(0, 6, 10, 245);
                border: 1px solid {C.BORDER_B};
                border-radius: 6px;
            }}
        """)

        detected = {"darwin": "mac", "windows": "windows"}.get(
            _OS.lower(), "linux"
        )
        self._sel_os = detected

        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 22, 30, 22)
        layout.setSpacing(8)

        def _lbl(txt, font_size=9, bold=False, color=C.PRI,
                 align=Qt.AlignmentFlag.AlignCenter):
            w = QLabel(txt)
            w.setAlignment(align)
            w.setFont(QFont("Courier New", font_size,
                            QFont.Weight.Bold if bold else QFont.Weight.Normal))
            w.setStyleSheet(f"color: {color}; background: transparent;")
            return w

        layout.addWidget(_lbl("◈  INITIALISATION REQUIRED", 13, True))
        layout.addWidget(_lbl("Configure J.A.R.V.I.S. before first boot.", 9, color=C.PRI_DIM))
        layout.addSpacing(6)

        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {C.BORDER};"); layout.addWidget(sep)
        layout.addSpacing(4)

        layout.addWidget(_lbl("GEMINI API KEY", 8, color=C.TEXT_DIM,
                               align=Qt.AlignmentFlag.AlignLeft))
        self._key_input = QLineEdit()
        self._key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self._key_input.setPlaceholderText("AIza…")
        self._key_input.setFont(QFont("Courier New", 10))
        self._key_input.setFixedHeight(32)
        self._key_input.setStyleSheet(f"""
            QLineEdit {{
                background: #000d12; color: {C.TEXT};
                border: 1px solid {C.BORDER}; border-radius: 3px; padding: 4px 8px;
            }}
            QLineEdit:focus {{ border: 1px solid {C.PRI}; }}
        """)
        layout.addWidget(self._key_input)
        layout.addSpacing(8)

        layout.addWidget(_lbl("OPENROUTER API KEY", 8, color=C.TEXT_DIM,
                       align=Qt.AlignmentFlag.AlignLeft))
        self._or_input = QLineEdit()
        self._or_input.setEchoMode(QLineEdit.EchoMode.Password)
        self._or_input.setPlaceholderText("sk-or-…")
        self._or_input.setFont(QFont("Courier New", 10))
        self._or_input.setFixedHeight(32)
        self._or_input.setStyleSheet(f"""
            QLineEdit {{
                background: #000d12; color: {C.TEXT};
                border: 1px solid {C.BORDER}; border-radius: 3px; padding: 4px 8px;
            }}
            QLineEdit:focus {{ border: 1px solid {C.ACC2}; }}
        """)
        layout.addWidget(self._or_input)

        layout.addSpacing(12)

        sep2 = QFrame(); sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setStyleSheet(f"color: {C.BORDER};"); layout.addWidget(sep2)
        layout.addSpacing(4)

        layout.addWidget(_lbl("OPERATING SYSTEM", 8, color=C.TEXT_DIM,
                               align=Qt.AlignmentFlag.AlignLeft))
        det_name = {"windows": "Windows", "mac": "macOS", "linux": "Linux"}[detected]
        layout.addWidget(_lbl(f"Auto-detected: {det_name}", 8, color=C.ACC2,
                               align=Qt.AlignmentFlag.AlignLeft))

        os_row = QHBoxLayout(); os_row.setSpacing(6)
        self._os_btns: dict[str, QPushButton] = {}
        for key, label in [("windows","⊞  Windows"),("mac","  macOS"),("linux","🐧  Linux")]:
            btn = QPushButton(label)
            btn.setFont(QFont("Courier New", 9, QFont.Weight.Bold))
            btn.setFixedHeight(32)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _, k=key: self._sel(k))
            os_row.addWidget(btn)
            self._os_btns[key] = btn
        layout.addLayout(os_row)
        self._sel(detected)
        layout.addSpacing(12)

        init_btn = QPushButton("▸  INITIALISE SYSTEMS")
        init_btn.setFont(QFont("Courier New", 10, QFont.Weight.Bold))
        init_btn.setFixedHeight(36)
        init_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        init_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {C.PRI};
                border: 1px solid {C.PRI_DIM}; border-radius: 3px;
            }}
            QPushButton:hover {{
                background: {C.PRI_GHO}; border: 1px solid {C.PRI};
            }}
        """)
        init_btn.clicked.connect(self._submit)
        layout.addWidget(init_btn)

    def _sel(self, key: str):
        self._sel_os = key
        pal = {"windows":(C.PRI,"#001a22"),"mac":(C.ACC2,"#1a1400"),"linux":(C.GREEN,"#001a0d")}
        for k, btn in self._os_btns.items():
            if k == key:
                fg, bg = pal[k]
                btn.setStyleSheet(f"""
                    QPushButton {{
                        background: {fg}; color: {bg};
                        border: none; border-radius: 3px; font-weight: bold;
                    }}
                """)
            else:
                btn.setStyleSheet(f"""
                    QPushButton {{
                        background: #000d12; color: {C.TEXT_DIM};
                        border: 1px solid {C.BORDER}; border-radius: 3px;
                    }}
                    QPushButton:hover {{ color: {C.TEXT}; border: 1px solid {C.BORDER_B}; }}
                """)

    def _submit(self):
        key = self._key_input.text().strip()
        or_key = self._or_input.text().strip()
        if not key:
            self._key_input.setStyleSheet(
                self._key_input.styleSheet() +
                f" QLineEdit {{ border: 1px solid {C.RED}; }}"
            )
            return
        if not or_key:
            self._or_input.setStyleSheet(
                self._or_input.styleSheet() +
                f" QLineEdit {{ border: 1px solid {C.RED}; }}"
            )
            return
        self.done.emit(key, or_key, self._sel_os)


class MainWindow(QMainWindow):
    _log_sig   = pyqtSignal(str)
    _state_sig = pyqtSignal(str)
    _map_sig   = pyqtSignal(dict)
    _chat_sig  = pyqtSignal()
    _stats_sig = pyqtSignal()
    _whatsapp_sig = pyqtSignal(dict)
    _wa_new_msg_sig = pyqtSignal(str)  # nome contatto che ha mandato un nuovo messaggio
    _home_sig  = pyqtSignal()

    def __init__(self, face_path: str):
        super().__init__()
        self.setWindowTitle("J.A.R.V.I.S — MARK XXXIX")
        self.setMinimumSize(_MIN_W, _MIN_H)
        self.resize(_DEFAULT_W, _DEFAULT_H)

        screen = QApplication.primaryScreen().availableGeometry()
        self.move(
            (screen.width()  - _DEFAULT_W) // 2,
            (screen.height() - _DEFAULT_H) // 2,
        )

        self.on_text_command  = None
        self._muted           = False
        self._current_file: str | None = None

        central = QWidget()
        central.setStyleSheet(f"background: {C.BG};")
        self.setCentralWidget(central)

        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._build_header())

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)

        self._left_panel = self._build_left_panel()
        body.addWidget(self._left_panel, stretch=0)

        self.hud = HudCanvas(face_path)
        self.hud.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        body.addWidget(self.hud, stretch=5)

        self._right_panel = self._build_right_panel()
        body.addWidget(self._right_panel, stretch=0)

        root.addLayout(body, stretch=1)
        root.addWidget(self._build_footer())

        self._clock_tmr = QTimer(self)
        self._clock_tmr.timeout.connect(self._tick_clock)
        self._clock_tmr.start(1000)
        self._tick_clock()

        # Metrik güncelleme timer'ı — CPU-friendly: ogni 5s anziche' 2s.
        self._metric_tmr = QTimer(self)
        self._metric_tmr.timeout.connect(self._update_metrics)
        self._metric_tmr.start(5000)
        self._update_metrics()

        self._log_sig.connect(self._on_log_line)
        self._state_sig.connect(self._apply_state)

        # ---- Overlays per richiesta utente: map / chat / stats / whatsapp ----
        self._map_overlay  = None
        self._chat_overlay = None
        self._whatsapp_overlay = None
        self._wa_pending_reply: str | None = None  # ultimo mittente non letto
        self._wa_new_msg_cb = None                  # callback registrata da main
        self._map_sig.connect(self._show_map_overlay)
        self._chat_sig.connect(self._toggle_chat_overlay)
        self._stats_sig.connect(self._toggle_stats_overlay)
        self._whatsapp_sig.connect(self._handle_whatsapp_signal)
        self._wa_new_msg_sig.connect(self._on_wa_new_msg)
        self._home_sig.connect(self._reset_to_home)

        self._overlay: SetupOverlay | None = None
        self._ready = self._check_config()
        if not self._ready:
            self._show_setup()

        # Bootstrap automatico dell'overlay WhatsApp (NASCOSTO):
        # serve a far partire il polling dei messaggi non letti senza
        # richiedere all'utente di aprire manualmente la finestra.
        # Cosi' JARVIS puo' annunciare vocalmente "Signore, nuovo
        # messaggio da X" anche con WhatsApp non visibile.
        QTimer.singleShot(1500, self._bootstrap_whatsapp_hidden)

        sc_mute = QShortcut(QKeySequence("F4"), self)
        sc_mute.activated.connect(self._toggle_mute)
        sc_full = QShortcut(QKeySequence("F11"), self)
        sc_full.activated.connect(self._toggle_fullscreen)

    def _toggle_fullscreen(self):
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._overlay and self._overlay.isVisible():
            ow, oh = 460, 390
            cw = self.centralWidget()
            self._overlay.setGeometry(
                (cw.width()  - ow) // 2,
                (cw.height() - oh) // 2,
                ow, oh,
            )

    def _update_metrics(self):
        snap = _metrics.snapshot()

        # CPU
        cpu = snap["cpu"]
        self._bar_cpu.set_value(cpu, f"{cpu:.0f}%")

        # MEM
        mem = snap["mem"]
        self._bar_mem.set_value(mem, f"{mem:.0f}%")

        # NET
        net = snap["net"]
        if net < 1.0:
            net_str = f"{net*1024:.0f}KB/s"
        else:
            net_str = f"{net:.1f}MB/s"
        net_pct = min(100, net * 10)  # 10 MB/s = %100
        self._bar_net.set_value(net_pct, net_str)

        # GPU
        gpu = snap["gpu"]
        if gpu >= 0:
            self._bar_gpu.set_value(gpu, f"{gpu:.0f}%")
        else:
            self._bar_gpu.set_value(0, "N/A")

        # TMP
        tmp = snap["tmp"]
        if tmp >= 0:
            tmp_pct = min(100, (tmp / 100) * 100)
            self._bar_tmp.set_value(tmp_pct, f"{tmp:.0f}°C")
        else:
            self._bar_tmp.set_value(0, "N/A")

        try:
            boot_t  = psutil.boot_time()
            elapsed = time.time() - boot_t
            h = int(elapsed // 3600)
            m = int((elapsed % 3600) // 60)
            self._uptime_lbl.setText(f"UP  {h:02d}:{m:02d}")
        except Exception:
            self._uptime_lbl.setText("UP  --:--")

        try:
            proc_count = len(psutil.pids())
            self._proc_lbl.setText(f"PROC  {proc_count}")
        except Exception:
            self._proc_lbl.setText("PROC  --")


    def _build_header(self) -> QWidget:
        w = QWidget()
        w.setFixedHeight(54)
        w.setStyleSheet(f"background: {C.DARK}; border-bottom: 1px solid {C.BORDER_B};")
        lay = QHBoxLayout(w)
        lay.setContentsMargins(16, 0, 16, 0)

        def _badge(txt, color=C.TEXT_MED):
            l = QLabel(txt)
            l.setFont(QFont("Courier New", 8))
            l.setStyleSheet(f"color: {color}; background: transparent;")
            return l

        lay.addWidget(_badge("MARK XXXIX", C.PRI_DIM))
        lay.addStretch()

        mid = QVBoxLayout(); mid.setSpacing(1)
        title = QLabel("J.A.R.V.I.S")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setFont(QFont("Courier New", 17, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {C.PRI}; background: transparent;")
        mid.addWidget(title)
        sub = QLabel("Just A Rather Very Intelligent System")
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub.setFont(QFont("Courier New", 7))
        sub.setStyleSheet(f"color: {C.PRI_DIM}; background: transparent;")
        mid.addWidget(sub)
        lay.addLayout(mid)
        lay.addStretch()

        right_col = QVBoxLayout(); right_col.setSpacing(2)
        self._clock_lbl = QLabel("00:00:00")
        self._clock_lbl.setFont(QFont("Courier New", 14, QFont.Weight.Bold))
        self._clock_lbl.setStyleSheet(f"color: {C.PRI}; background: transparent;")
        self._clock_lbl.setAlignment(Qt.AlignmentFlag.AlignRight)
        right_col.addWidget(self._clock_lbl)
        self._date_lbl = QLabel("")
        self._date_lbl.setFont(QFont("Courier New", 7))
        self._date_lbl.setStyleSheet(f"color: {C.TEXT_DIM}; background: transparent;")
        self._date_lbl.setAlignment(Qt.AlignmentFlag.AlignRight)
        right_col.addWidget(self._date_lbl)
        lay.addLayout(right_col)
        return w

    def _tick_clock(self):
        self._clock_lbl.setText(time.strftime("%H:%M:%S"))
        self._date_lbl.setText(time.strftime("%a %d %b %Y"))

    def _build_left_panel(self) -> QWidget:
        w = QWidget()
        w.setFixedWidth(_LEFT_W)
        w.setStyleSheet(f"background: {C.DARK}; border-right: 1px solid {C.BORDER};")
        lay = QVBoxLayout(w)
        lay.setContentsMargins(8, 10, 8, 10)
        lay.setSpacing(6)

        hdr = QLabel("◈ SYS MONITOR")
        hdr.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
        hdr.setStyleSheet(f"color: {C.PRI}; background: transparent; "
                          f"border-bottom: 1px solid {C.BORDER}; padding-bottom: 4px;")
        lay.addWidget(hdr)
        lay.addSpacing(2)

        self._bar_cpu = MetricBar("CPU", C.PRI)
        self._bar_mem = MetricBar("MEM", C.ACC2)
        self._bar_net = MetricBar("NET", C.GREEN)
        self._bar_gpu = MetricBar("GPU", C.ACC)
        self._bar_tmp = MetricBar("TMP", "#ff6688")

        for bar in [self._bar_cpu, self._bar_mem, self._bar_net,
                    self._bar_gpu, self._bar_tmp]:
            lay.addWidget(bar)

        lay.addSpacing(4)

        info_panel = QWidget()
        info_panel.setStyleSheet(
            f"background: {C.PANEL2}; border: 1px solid {C.BORDER}; border-radius: 4px;"
        )
        ip_lay = QVBoxLayout(info_panel)
        ip_lay.setContentsMargins(6, 5, 6, 5)
        ip_lay.setSpacing(3)

        self._uptime_lbl = QLabel("UP  --:--")
        self._uptime_lbl.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        self._uptime_lbl.setStyleSheet(f"color: {C.GREEN}; background: transparent; border: none;")
        ip_lay.addWidget(self._uptime_lbl)

        self._proc_lbl = QLabel("PROC  --")
        self._proc_lbl.setFont(QFont("Courier New", 8))
        self._proc_lbl.setStyleSheet(f"color: {C.TEXT_MED}; background: transparent; border: none;")
        ip_lay.addWidget(self._proc_lbl)

        os_name = {"Windows": "WIN", "Darwin": "macOS", "Linux": "LINUX"}.get(_OS, _OS.upper())
        os_lbl = QLabel(f"OS  {os_name}")
        os_lbl.setFont(QFont("Courier New", 8))
        os_lbl.setStyleSheet(f"color: {C.ACC2}; background: transparent; border: none;")
        ip_lay.addWidget(os_lbl)

        lay.addWidget(info_panel)
        lay.addStretch()

        for txt, col in [
            ("AI CORE\nACTIVE",     C.GREEN),
            ("SEC\nCLEARED",        C.PRI),
            ("PROTOCOL\nXXXVIII",   C.TEXT_DIM),
        ]:
            lbl = QLabel(txt)
            lbl.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setStyleSheet(
                f"color: {col}; background: {C.PANEL2};"
                f"border: 1px solid {C.BORDER_A}; border-radius: 3px; padding: 4px;"
            )
            lay.addWidget(lbl)

        return w
    def _build_right_panel(self) -> QWidget:
        w = QWidget()
        w.setFixedWidth(_RIGHT_W)
        w.setStyleSheet(f"background: {C.DARK}; border-left: 1px solid {C.BORDER};")
        lay = QVBoxLayout(w)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(6)

        def _sec(txt):
            l = QLabel(f"▸ {txt}")
            l.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
            l.setStyleSheet(f"color: {C.TEXT_MED}; background: transparent;")
            return l

        lay.addWidget(_sec("ACTIVITY LOG"))
        self._log = LogWidget()
        lay.addWidget(self._log, stretch=1)

        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {C.BORDER}; margin: 2px 0;")
        lay.addWidget(sep)

        lay.addWidget(_sec("FILE UPLOAD"))
        self._drop_zone = FileDropZone()
        self._drop_zone.file_selected.connect(self._on_file_selected)
        lay.addWidget(self._drop_zone)

        self._file_hint = QLabel("No file loaded — drop or click above to upload")
        self._file_hint.setFont(QFont("Courier New", 7))
        self._file_hint.setStyleSheet(f"color: {C.TEXT_MED}; background: transparent;")
        self._file_hint.setWordWrap(True)
        lay.addWidget(self._file_hint)

        sep2 = QFrame(); sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setStyleSheet(f"color: {C.BORDER}; margin: 2px 0;")
        lay.addWidget(sep2)

        lay.addWidget(_sec("COMMAND INPUT"))
        lay.addLayout(self._build_input_row())

        self._mute_btn = QPushButton("🎙  MICROPHONE ACTIVE")
        self._mute_btn.setFixedHeight(30)
        self._mute_btn.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        self._mute_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._mute_btn.clicked.connect(self._toggle_mute)
        self._style_mute_btn()
        lay.addWidget(self._mute_btn)

        fs_btn = QPushButton("⛶  FULLSCREEN  [F11]")
        fs_btn.setFixedHeight(26)
        fs_btn.setFont(QFont("Courier New", 7))
        fs_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        fs_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {C.TEXT_MED};
                border: 1px solid {C.BORDER}; border-radius: 3px;
            }}
            QPushButton:hover {{
                color: {C.PRI}; border: 1px solid {C.BORDER_B};
            }}
        """)
        fs_btn.clicked.connect(self._toggle_fullscreen)
        lay.addWidget(fs_btn)

        return w

    def _build_input_row(self) -> QHBoxLayout:
        row = QHBoxLayout(); row.setSpacing(5)
        self._input = QLineEdit()
        self._input.setPlaceholderText("Type a command or question…")
        self._input.setFont(QFont("Courier New", 9))
        self._input.setFixedHeight(30)
        self._input.setStyleSheet(f"""
            QLineEdit {{
                background: #000d14; color: {C.WHITE};
                border: 1px solid {C.BORDER}; border-radius: 3px; padding: 3px 7px;
            }}
            QLineEdit:focus {{ border: 1px solid {C.PRI}; }}
        """)
        self._input.returnPressed.connect(self._send)
        row.addWidget(self._input)

        send = QPushButton("▸")
        send.setFixedSize(30, 30)
        send.setFont(QFont("Courier New", 11, QFont.Weight.Bold))
        send.setCursor(Qt.CursorShape.PointingHandCursor)
        send.setStyleSheet(f"""
            QPushButton {{
                background: {C.PANEL}; color: {C.PRI};
                border: 1px solid {C.PRI_DIM}; border-radius: 3px;
            }}
            QPushButton:hover {{ background: {C.PRI_GHO}; border: 1px solid {C.PRI}; }}
        """)
        send.clicked.connect(self._send)
        row.addWidget(send)
        return row

    def _build_footer(self) -> QWidget:
        w = QWidget()
        w.setFixedHeight(22)
        w.setStyleSheet(f"background: {C.DARK}; border-top: 1px solid {C.BORDER};")
        lay = QHBoxLayout(w); lay.setContentsMargins(14, 0, 14, 0)

        def _fl(txt, color=C.TEXT_MED):
            l = QLabel(txt); l.setFont(QFont("Courier New", 7))
            l.setStyleSheet(f"color: {color}; background: transparent;")
            return l

        lay.addWidget(_fl("[F4] Mute  ·  [F11] Fullscreen"))
        lay.addStretch()
        lay.addWidget(_fl("FatihMakes Industries  ·  MARK XXXIX  ·  CLASSIFIED"))
        lay.addStretch()
        lay.addWidget(_fl("© STARK INDUSTRIES", C.PRI_DIM))
        return w

    def _on_file_selected(self, path: str):
        self._current_file = path
        p    = Path(path)
        cat  = _file_category(p)
        icon, _ = _FILE_ICONS.get(cat, _FILE_ICONS["unknown"])
        size = _fmt_size(p.stat().st_size)
        self._file_hint.setText(f"{icon}  {p.name}  ·  {size}  ·  Tell JARVIS what to do with it")
        self._log.append_log(f"FILE: {p.name} ({size}) loaded")
        if self.on_text_command:
            msg = (
                f"[FILE_UPLOADED] path={path} | name={p.name} | "
                f"type={p.suffix.lstrip('.')} | size={size} | "
                f"Briefly tell the user you can see the file '{p.name}' "
                f"({size}) has been uploaded and ask what they'd like to do with it."
            )
            threading.Thread(target=self.on_text_command, args=(msg,), daemon=True).start()

    def _toggle_mute(self):
        self._muted = not self._muted
        self.hud.muted = self._muted
        self._style_mute_btn()
        if self._muted:
            self._apply_state("MUTED")
            self._log.append_log("SYS: Microphone muted.")
        else:
            self._apply_state("LISTENING")
            self._log.append_log("SYS: Microphone active.")

    def _style_mute_btn(self):
        if self._muted:
            self._mute_btn.setText("🔇  MICROPHONE MUTED")
            self._mute_btn.setStyleSheet(f"""
                QPushButton {{
                    background: #140006; color: {C.MUTED_C};
                    border: 1px solid {C.MUTED_C}; border-radius: 3px;
                }}
            """)
        else:
            self._mute_btn.setText("🎙  MICROPHONE ACTIVE")
            self._mute_btn.setStyleSheet(f"""
                QPushButton {{
                    background: #00140a; color: {C.GREEN};
                    border: 1px solid {C.GREEN}; border-radius: 3px;
                }}
                QPushButton:hover {{ background: #001f10; }}
            """)

    def _send(self):
        txt = self._input.text().strip()
        if not txt: return
        self._input.clear()
        self._log.append_log(f"You: {txt}")
        if self.on_text_command:
            threading.Thread(target=self.on_text_command, args=(txt,), daemon=True).start()

    def _apply_state(self, state: str):
        self.hud.state    = state
        self.hud.speaking = (state == "SPEAKING")

    def _check_config(self) -> bool:
        if not API_FILE.exists(): return False
        try:
            d = json.loads(API_FILE.read_text(encoding="utf-8"))
            return (bool(d.get("gemini_api_key")) and
                    bool(d.get("openrouter_api_key")) and
                    bool(d.get("os_system")))
        except Exception:
            return False

    def _show_setup(self):
        ov = SetupOverlay(self.centralWidget())
        cw = self.centralWidget()
        ow, oh = 460, 430
        ov.setGeometry(
            (cw.width()  - ow) // 2,
            (cw.height() - oh) // 2,
            ow, oh,
        )
        ov.done.connect(self._on_setup_done)
        ov.show()
        self._overlay = ov

    # Change signature:
    def _on_setup_done(self, key: str, or_key: str, os_name: str):
        os.makedirs(CONFIG_DIR, exist_ok=True)
        API_FILE.write_text(
            json.dumps({
                "gemini_api_key":    key,
                "openrouter_api_key": or_key,
                "os_system":         os_name,
            }, indent=4),
            encoding="utf-8",
        )
        self._ready = True
        if self._overlay:
            self._overlay.hide()
            self._overlay = None
        self._apply_state("LISTENING")
        self._log.append_log(f"SYS: Initialised. OS={os_name.upper()}. JARVIS online.")

    # =====================================================================
    # MAP OVERLAY (animazione fade-in stile JARVIS) -- richiesta utente.
    # Sostituisce la finestra Tk separata di jarvis_map.py.
    # =====================================================================
    def _show_map_overlay(self, data: dict):
        from PyQt6.QtCore import QPropertyAnimation, QEasingCurve
        from PyQt6.QtWidgets import QGraphicsOpacityEffect

        # Se gia' aperta, fai solo update dei contenuti (nessuna nuova finestra)
        if self._map_overlay is not None:
            try:
                self._map_overlay._update_data(data)
                return
            except Exception:
                self._close_map_invoke()

        cw = self.centralWidget()
        overlay = _MapOverlay(cw, data)
        self._map_overlay = overlay
        overlay.setGeometry(0, 0, cw.width(), cw.height())
        overlay.raise_()
        overlay.show()
        cw.installEventFilter(overlay)

        # Fade-in
        eff = QGraphicsOpacityEffect(overlay)
        overlay.setGraphicsEffect(eff)
        eff.setOpacity(0.0)
        anim = QPropertyAnimation(eff, b"opacity", overlay)
        anim.setDuration(380)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.start()
        overlay._anim = anim   # keep ref

        self._log.append_log(f"SYS: Tactical map -> {data.get('city','?').upper()}")

    def _close_map_invoke(self) -> bool:
        from PyQt6.QtCore import QPropertyAnimation, QEasingCurve
        from PyQt6.QtWidgets import QGraphicsOpacityEffect

        ov = self._map_overlay
        if ov is None or not ov.isVisible():
            return False

        eff = ov.graphicsEffect()
        if not isinstance(eff, QGraphicsOpacityEffect):
            eff = QGraphicsOpacityEffect(ov)
            ov.setGraphicsEffect(eff)

        anim = QPropertyAnimation(eff, b"opacity", ov)
        anim.setDuration(280)
        anim.setStartValue(eff.opacity())
        anim.setEndValue(0.0)
        anim.setEasingCurve(QEasingCurve.Type.InCubic)

        def _done():
            try:
                self.centralWidget().removeEventFilter(ov)
                ov.hide()
                ov.deleteLater()
            except Exception:
                pass
            self._map_overlay = None

        anim.finished.connect(_done)
        anim.start()
        ov._anim = anim
        return True

    def _on_log_line(self, line: str):
        """Riceve ogni riga di log: appende al pannello E inoltra alla chat."""
        try:
            self._log.append_log(line)
        except Exception:
            pass
        if not line:
            return
        # Inoltra alla chat overlay (se aperta)
        try:
            if line.startswith("Jarvis:"):
                self._append_chat_jarvis(line[len("Jarvis:"):].strip())
            elif line.startswith("You:"):
                self._append_chat_user(line[len("You:"):].strip())
        except Exception:
            pass

    def _toggle_chat_overlay(self):
        if self._chat_overlay is not None and self._chat_overlay.isVisible():
            self._chat_overlay.hide()
            return
        if self._chat_overlay is None:
            self._chat_overlay = _ChatOverlay(self.centralWidget(),
                                              on_send=self._send_chat_text)
        cw = self.centralWidget()
        ow, oh = 380, 460
        self._chat_overlay.setGeometry(
            cw.width() - ow - 24,
            (cw.height() - oh) // 2,
            ow, oh,
        )
        self._chat_overlay.raise_()
        self._chat_overlay.show()

    def _append_chat_jarvis(self, text: str):
        """Inoltra una risposta di JARVIS alla chat overlay (se aperta)."""
        ov = self._chat_overlay
        if ov is not None and ov.isVisible():
            try:
                ov.append_jarvis(text)
            except Exception:
                pass

    def _append_chat_user(self, text: str):
        """Inoltra il prompt utente alla chat overlay (se aperta)."""
        ov = self._chat_overlay
        if ov is not None and ov.isVisible():
            try:
                ov.append_user(text)
            except Exception:
                pass

    def _send_chat_text(self, text: str):
        cb = getattr(self, "on_text_command", None)
        if cb:
            try:
                cb(text)
            except Exception as e:
                self._log.append_log(f"ERR: chat send -> {e}")

    def _toggle_stats_overlay(self):
        """Apre/chiude un overlay con le statistiche del PC (CPU/MEM/NET/GPU/TMP)."""
        ov = getattr(self, "_stats_overlay", None)
        if ov is not None and ov.isVisible():
            ov.hide()
            return
        if ov is None:
            self._stats_overlay = _StatsOverlay(self.centralWidget(), self)
            ov = self._stats_overlay
        cw = self.centralWidget()
        ow, oh = 320, 360
        ov.setGeometry(24, (cw.height() - oh) // 2, ow, oh)
        ov.raise_()
        ov.show()
        try:
            ov.refresh()
        except Exception:
            pass

    def _bootstrap_whatsapp_hidden(self):
        """Crea l'overlay WhatsApp NASCOSTO all'avvio cosi' il polling
        dei messaggi in arrivo gira sempre, senza richiedere all'utente
        di aprire la finestra. La sessione WhatsApp Web e' persistente
        in ~/.jarvis_whatsapp_profile.
        """
        cw = self.centralWidget()
        if cw is None:
            return
        if self._whatsapp_overlay is None:
            try:
                self._whatsapp_overlay = _WhatsAppOverlay(
                    cw,
                    on_new_message=lambda name: self._wa_new_msg_sig.emit(name),
                )
            except Exception as e:
                self._log.append_log(f"ERR: whatsapp bootstrap -> {e}")
                return
        ov = self._whatsapp_overlay
        ow, oh = 460, 620
        ov.setGeometry(cw.width() - ow - 24, (cw.height() - oh) // 2, ow, oh)
        # Carica la web view ma resta nascosto. start_notifications()
        # bootstrappa dopo 6s e poi polla ogni 8s.
        ov.hide()
        try:
            ov.start_notifications()
        except Exception:
            pass

    def _on_wa_new_msg(self, name: str):
        """Slot thread-safe per nuovo messaggio WA in arrivo.

        - Logga in console JARVIS
        - Mostra un TOAST visuale verde in basso a destra (~5s)
        - Memorizza il contatto come ultimo "pending_reply"
        - Invoca, se presente, la callback registrata dal main
          (`on_whatsapp_new_message`) cosi' JarvisLive puo' parlare
          e iniettare contesto nel modello Gemini Live.
        """
        try:
            self._log.append_log(f"WA: nuovo messaggio da {name}")
        except Exception:
            pass
        # ---- Toast visuale (notifica popup verde-WhatsApp) -----------
        try:
            self._show_wa_toast(name)
        except Exception as e:
            try:
                self._log.append_log(f"ERR wa toast: {e}")
            except Exception:
                pass
        self._wa_pending_reply = name
        cb = getattr(self, "_wa_new_msg_cb", None)
        if callable(cb):
            try:
                cb(name)
            except Exception as e:
                try:
                    self._log.append_log(f"ERR wa cb: {e}")
                except Exception:
                    pass

    def _show_wa_toast(self, name: str):
        """Mostra una piccola finestrella di notifica verde-WhatsApp in
        basso a destra del central widget per ~5 secondi."""
        cw = self.centralWidget()
        if cw is None:
            return
        toast = QLabel(cw)
        toast.setText(f"WhatsApp  ●  Nuovo messaggio da\n{name}")
        toast.setAlignment(Qt.AlignmentFlag.AlignCenter)
        toast.setStyleSheet(
            "QLabel {"
            " background: rgba(0, 20, 14, 235);"
            " color: #25d366;"
            " border: 1px solid #25d366;"
            " padding: 10px 16px;"
            " font-family: Consolas, monospace;"
            " font-size: 12px;"
            " font-weight: bold;"
            "}"
        )
        toast.adjustSize()
        tw = max(toast.width(), 280)
        th = max(toast.height(), 56)
        toast.setFixedSize(tw, th)
        toast.move(cw.width() - tw - 24, cw.height() - th - 24)
        toast.raise_()
        toast.show()
        QTimer.singleShot(5000, toast.deleteLater)

    def _handle_whatsapp_signal(self, payload: dict):
        from PyQt6.QtCore import QTimer
        action = (payload or {}).get("action", "open")

        # Azione "close": chiudi/nascondi la finestra WhatsApp e basta.
        if action in ("close", "hide", "chiudi"):
            ov = getattr(self, "_whatsapp_overlay", None)
            if ov is not None:
                try:
                    ov.hide()
                except Exception:
                    pass
            return

        cw = self.centralWidget()
        if self._whatsapp_overlay is None:
            try:
                self._whatsapp_overlay = _WhatsAppOverlay(
                    cw,
                    on_new_message=lambda name: self._wa_new_msg_sig.emit(name),
                )
            except Exception as e:
                self._log.append_log(f"ERR: whatsapp init -> {e}")
                return
        ov = self._whatsapp_overlay

        # ---- Azioni fullscreen / minimize (toggle finestra <-> schermo intero)
        if action in ("fullscreen", "maximize", "schermo_intero", "fullscreen_on"):
            try:
                ov.set_fullscreen()
                ov.start_notifications()
            except Exception as e:
                self._log.append_log(f"ERR: whatsapp fullscreen -> {e}")
            return
        if action in ("minimize", "windowed", "restore", "finestra"):
            try:
                ov.set_windowed()
                ov.start_notifications()
            except Exception as e:
                self._log.append_log(f"ERR: whatsapp minimize -> {e}")
            return

        # ---- Open / default: mostra in modalita' windowed (a meno che
        # l'overlay sia gia' in fullscreen, in quel caso non cambiare).
        if not getattr(ov, "_is_fullscreen", False):
            ow, oh = 460, 620
            ov.setGeometry(cw.width() - ow - 24, (cw.height() - oh) // 2, ow, oh)
        ov.raise_()
        ov.show()
        # Avvia polling notifiche al primo show
        try:
            ov.start_notifications()
        except Exception:
            pass

        if action == "read_chats":
            QTimer.singleShot(2500, lambda: ov.read_unread_chats(
                callback=lambda txt: self._log.append_log(f"WA: {txt}")
            ))
        elif action == "send_message":
            # Invio COMPLETAMENTE vocale: nessuna dashboard, solo voce.
            # JARVIS deve passare recipient + message. La ricerca fa
            # fuzzy-match sui contatti (anche archiviati) via search di WA.
            recipient = (payload or {}).get("recipient", "")
            message   = (payload or {}).get("message", "")
            if recipient and message:
                # Attendi che la web view sia renderizzata (se appena aperta).
                # Il callback ora riceve (ok, raw) cosi' loggiamo la causa
                # del fallimento (es. "ERR: Contatto X non trovato").
                def _wa_send_done(ok, raw=""):
                    self._log.append_log(
                        f"WA: send {'OK' if ok else 'FAIL'} -> {recipient} [{raw}]"
                    )
                QTimer.singleShot(1800, lambda: ov.send_message(
                    recipient, message, callback=_wa_send_done
                ))
            else:
                self._log.append_log(
                    "WA: send_message richiede recipient e message (via voce)"
                )
        # 'open' o azione sconosciuta: la web view e' gia' visibile

    def _reset_to_home(self):
        """Riporta JARVIS allo stato iniziale: chiude TUTTI gli overlay."""
        try:
            self._close_map_invoke()
        except Exception:
            pass
        for attr in ("_chat_overlay", "_stats_overlay", "_whatsapp_overlay"):
            ov = getattr(self, attr, None)
            if ov is not None:
                try:
                    ov.hide()
                except Exception:
                    pass
        # Riassicura che il pannello destro (log + comandi) sia visibile
        rp = getattr(self, "_right_panel", None)
        if rp is not None:
            rp.setVisible(True)

class _MapOverlay(QFrame):
    """Overlay JARVIS che mostra la mappa 3D della citta' DENTRO la UI.

    Renderizza un vero web-view con OpenStreetMap + OSMBuildings (vista 3D
    degli edifici, free, nessuna API key). A destra restano coordinate,
    meteo, POI ed estratto Wikipedia.

    Se PyQt6-WebEngine non e' installato, mostra solo il pannello dati
    (fallback) cosi' la UI non si rompe.
    """
    def __init__(self, parent, data: dict):
        super().__init__(parent)
        self.setObjectName("MapOverlay")
        self.setStyleSheet(f"""
            QFrame#MapOverlay {{
                background: rgba(0, 6, 10, 245);
                border: 1px solid {C.PRI};
            }}
            QLabel {{ color: {C.TEXT}; }}
            QLabel#mapTitle {{ color: {C.PRI}; }}
            QLabel#mapDim   {{ color: {C.TEXT_DIM}; }}
            QListWidget {{
                background: {C.PANEL};
                color: {C.TEXT};
                border: 1px solid {C.BORDER};
            }}
            QPushButton {{
                background: {C.PANEL2};
                color: {C.PRI};
                border: 1px solid {C.PRI_DIM};
                padding: 6px 16px;
            }}
            QPushButton:hover {{ border-color: {C.PRI}; color: {C.WHITE}; }}
        """)
        self._web = None
        self._build(data)

    @staticmethod
    def _make_map_html(lat: float, lon: float, city: str, pois: list) -> str:
        """Genera l'HTML/JS della mappa stile Google Earth (Leaflet + tile
        satellitari Esri World Imagery, free, nessuna API key).

        Lo zoom va dalla vista globale (zoom 2) fino al dettaglio strada/edificio
        (zoom 19). Piu' si ingrandisce, piu' si vede: proprio come Google Earth.
        """
        markers = []
        for p in (pois or [])[:30]:
            try:
                la = float(p.get("lat"))
                lo = float(p.get("lon"))
                ti = (p.get("title") or "")
                markers.append({"lat": la, "lon": lo, "title": ti})
            except Exception:
                pass
        markers_json = json.dumps(markers, ensure_ascii=False)
        city_safe    = json.dumps(city, ensure_ascii=False)

        return f"""<!doctype html>
<html><head>
<meta charset="utf-8"/>
<title>JARVIS // EARTH // {city}</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<style>
  html,body {{ margin:0; padding:0; background:#000308; overflow:hidden;
               height:100%; width:100%; color:#7cd2ff;
               font-family:Consolas,monospace; }}
  #map {{ width:100vw; height:100vh; background:#000308; }}
  .leaflet-container {{ background:#000308; }}
  .jarvis-hud {{
    position:absolute; left:14px; top:14px; z-index:9999;
    color:#7cd2ff; font-size:11px; letter-spacing:1px;
    background:rgba(0,8,12,0.78); padding:6px 10px;
    border:1px solid #2bb6ff; pointer-events:none;
  }}
  .jarvis-corner {{
    position:absolute; right:14px; top:14px; z-index:9999;
    color:#7cd2ff; font-size:10px; letter-spacing:1px;
    background:rgba(0,8,12,0.68); padding:5px 8px;
    border:1px solid #2bb6ff; pointer-events:none;
  }}
  .jarvis-zoom {{
    position:absolute; right:14px; bottom:14px; z-index:9999;
    color:#7cd2ff; font-size:10px; letter-spacing:1px;
    background:rgba(0,8,12,0.68); padding:5px 8px;
    border:1px solid #2bb6ff; pointer-events:none;
  }}
  .jarvis-marker {{
    width:14px; height:14px; border-radius:50%;
    background:#2bb6ff; box-shadow:0 0 12px #2bb6ff,0 0 24px #2bb6ff;
    border:2px solid #fff;
  }}
  .jarvis-marker.poi {{
    width:10px; height:10px; background:#ffae42;
    box-shadow:0 0 8px #ffae42; border:1px solid #fff;
  }}
  .leaflet-control-attribution {{
    background:rgba(0,8,12,0.7) !important; color:#5ab8cc !important;
    font-size:9px !important;
  }}
  .leaflet-control-attribution a {{ color:#7cd2ff !important; }}
  .leaflet-control-zoom a {{
    background:rgba(0,8,12,0.85) !important; color:#2bb6ff !important;
    border:1px solid #2bb6ff !important;
  }}
  .leaflet-control-zoom a:hover {{ background:#02232f !important; color:#fff !important; }}
</style>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
</head>
<body>
<div id="map"></div>
<div class="jarvis-hud" id="hud">J.A.R.V.I.S // EARTH VIEW // <span id="cityName">{city.upper()}</span></div>
<div class="jarvis-corner" id="corner">LAT <span id="latV">{lat:.3f}</span>  LON <span id="lonV">{lon:.3f}</span></div>
<div class="jarvis-zoom">ZOOM <span id="zoomV">5</span> / 19</div>
<script>
  var INITIAL_POINTS = {markers_json};
  var INITIAL_LAT = {lat};
  var INITIAL_LON = {lon};
  var INITIAL_CITY = {city_safe};

  // Leaflet map, da vista globale (zoom 2) fino a dettaglio strada (zoom 19).
  var map = L.map('map', {{
    zoomControl: true,
    worldCopyJump: true,
    minZoom: 2,
    maxZoom: 19,
    zoomSnap: 0.25,
  }}).setView([INITIAL_LAT, INITIAL_LON], 5);

  // Esri World Imagery: satellite tiles free, no API key.
  // Mostra il globo da lontano e arriva fino al dettaglio dell'edificio.
  L.tileLayer(
    'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{{z}}/{{y}}/{{x}}',
    {{
      attribution: 'Tiles © Esri — Source: Esri, Maxar, Earthstar Geographics, and the GIS User Community',
      maxZoom: 19,
    }}
  ).addTo(map);

  // Overlay strade/etichette: appare e diventa piu' fitto man mano che si ingrandisce.
  L.tileLayer(
    'https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{{z}}/{{y}}/{{x}}',
    {{
      maxZoom: 19, opacity: 0.85,
    }}
  ).addTo(map);

  var primaryIcon = L.divIcon({{ className:'', html:'<div class="jarvis-marker"></div>', iconSize:[14,14], iconAnchor:[7,7] }});
  var poiIcon     = L.divIcon({{ className:'', html:'<div class="jarvis-marker poi"></div>', iconSize:[10,10], iconAnchor:[5,5] }});

  var primaryMarker = L.marker([INITIAL_LAT, INITIAL_LON], {{ icon: primaryIcon, title: INITIAL_CITY }})
    .bindPopup('<b>' + INITIAL_CITY + '</b>').addTo(map);

  var poiLayer = L.layerGroup().addTo(map);
  function renderPois(points) {{
    poiLayer.clearLayers();
    (points || []).forEach(function(p) {{
      try {{
        L.marker([+p.lat, +p.lon], {{ icon: poiIcon, title: p.title || '' }})
          .bindPopup(p.title || '').addTo(poiLayer);
      }} catch(e) {{}}
    }});
  }}
  renderPois(INITIAL_POINTS);

  // Cerchio target che pulsa
  var pulseLayer = L.circle([INITIAL_LAT, INITIAL_LON], {{
    radius: 250, color:'#2bb6ff', weight:1.5, fillColor:'#2bb6ff', fillOpacity:0.12,
  }}).addTo(map);

  function setZoomHud() {{
    document.getElementById('zoomV').textContent = map.getZoom().toFixed(0);
  }}
  map.on('zoomend', setZoomHud);
  setZoomHud();

  // Apertura: vola verso la citta' (zoom globale -> citta')
  setTimeout(function() {{
    map.flyTo([INITIAL_LAT, INITIAL_LON], 13, {{ duration: 2.2 }});
  }}, 350);

  // Bridge per Python: aggiorna citta' con animazione "earth-style".
  window.jarvisFlyTo = function(lat, lon, city, points) {{
    try {{
      document.getElementById('cityName').textContent = (city || '').toUpperCase();
      document.getElementById('latV').textContent = (+lat).toFixed(3);
      document.getElementById('lonV').textContent = (+lon).toFixed(3);
      // Step 1: zoom out a vista globo
      map.flyTo(map.getCenter(), 3, {{ duration: 0.9 }});
      // Step 2: scorri verso la nuova citta' e ingrandisci
      setTimeout(function() {{
        map.flyTo([+lat, +lon], 13, {{ duration: 2.4 }});
      }}, 950);
      primaryMarker.setLatLng([+lat, +lon]).bindPopup('<b>' + (city || '') + '</b>');
      pulseLayer.setLatLng([+lat, +lon]);
      renderPois(points || []);
    }} catch (e) {{
      console.error('jarvisFlyTo error', e);
    }}
  }};
</script>
</body></html>
"""

    def _build(self, data: dict):
        from PyQt6.QtWidgets import QListWidget, QListWidgetItem
        city = data.get("city", "?")
        geo  = data.get("geo")  or {}
        w    = data.get("weather") or {}
        wiki = data.get("wiki")    or {}
        pois = data.get("pois")    or []

        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 14, 14, 14)
        lay.setSpacing(8)

        # Header
        head = QHBoxLayout()
        title = QLabel(f"J.A.R.V.I.S  //  TACTICAL MAP  //  {city.upper()}")
        title.setObjectName("mapTitle")
        f = QFont("Consolas", 14); f.setBold(True); title.setFont(f)
        head.addWidget(title, stretch=1)

        btn_close = QPushButton("✕ HOME")
        btn_close.clicked.connect(lambda: self.window()._close_map_invoke())
        head.addWidget(btn_close, stretch=0)
        lay.addLayout(head)

        # Body: 3D map a sinistra (grande), telemetria a destra
        body = QHBoxLayout(); body.setSpacing(10)

        # --- Mappa 3D ---
        if _HAS_WEBENGINE and geo.get("lat") is not None and geo.get("lon") is not None:
            try:
                html = self._make_map_html(
                    float(geo["lat"]), float(geo["lon"]), city, pois
                )
                self._web = QWebEngineView(self)
                self._web.setStyleSheet("background:#00060a;")
                self._web.setMinimumHeight(360)
                # Usa baseUrl https per consentire il caricamento di tile/script esterni
                self._web.setHtml(html, QUrl("https://jarvis.local/"))
                body.addWidget(self._web, stretch=3)
            except Exception as e:
                print(f"[MapOverlay] webview error: {e}")
                self._web = None

        if self._web is None:
            fallback = QLabel(
                "MAPPA 3D NON DISPONIBILE\n\n"
                "Installa: pip install PyQt6-WebEngine\n"
                "per attivare la vista 3D della citta'."
            )
            fallback.setStyleSheet(f"color:{C.PRI}; border:1px dashed {C.PRI_DIM}; padding:24px;")
            fallback.setAlignment(Qt.AlignmentFlag.AlignCenter)
            body.addWidget(fallback, stretch=3)

        # --- Telemetria + POI a destra ---
        right = QVBoxLayout(); right.setSpacing(6)

        sub = QLabel("PRIMARY TARGET // LOCKED")
        sub.setObjectName("mapDim")
        sub.setFont(QFont("Consolas", 8))
        right.addWidget(sub)

        def _row(label, value):
            r = QHBoxLayout()
            l1 = QLabel(label); l1.setObjectName("mapDim")
            l1.setFont(QFont("Consolas", 9))
            l2 = QLabel(str(value))
            l2.setStyleSheet(f"color: {C.PRI};")
            l2.setFont(QFont("Consolas", 9, QFont.Weight.Bold))
            r.addWidget(l1); r.addStretch(1); r.addWidget(l2)
            right.addLayout(r)

        if geo.get("lat") is not None:
            _row("LAT", f"{geo['lat']:.5f}")
        if geo.get("lon") is not None:
            _row("LON", f"{geo['lon']:.5f}")
        if w.get("temperature") is not None:
            _row("TEMP", f"{w['temperature']} C")
        if w.get("windspeed") is not None:
            _row("WIND", f"{w['windspeed']} km/h")
        _row("POI", f"{len(pois)}")
        _row("STATUS", "LOCKED")

        extract = (wiki.get("extract") or "").strip()
        if extract:
            right.addSpacing(6)
            il = QLabel("INTEL"); il.setObjectName("mapDim")
            il.setFont(QFont("Consolas", 8))
            right.addWidget(il)
            ext = QLabel(extract[:260] + ("..." if len(extract) > 260 else ""))
            ext.setWordWrap(True)
            ext.setFont(QFont("Consolas", 9))
            right.addWidget(ext)

        right.addSpacing(6)
        ph = QLabel("POI . NEARBY"); ph.setObjectName("mapDim")
        ph.setFont(QFont("Consolas", 8))
        right.addWidget(ph)
        poi_list = QListWidget()
        poi_list.setFont(QFont("Consolas", 9))
        poi_list.setMaximumHeight(180)
        for p in pois[:10]:
            t = p.get("title") or ""
            poi_list.addItem(QListWidgetItem(f"> {t}"))
        if not pois:
            poi_list.addItem("-- no POI in radius --")
        right.addWidget(poi_list, stretch=1)

        right_wrap = QWidget()
        right_wrap.setLayout(right)
        right_wrap.setMaximumWidth(320)
        body.addWidget(right_wrap, stretch=1)

        lay.addLayout(body, stretch=1)

        foot = QLabel("MARK . XXXIX . OR   //   STATUS: ONLINE")
        foot.setObjectName("mapDim")
        foot.setFont(QFont("Consolas", 8))
        lay.addWidget(foot)

    def _update_data(self, data: dict):
        """Aggiorna la mappa: se il webview e' attivo, esegui flyTo via JS
        (animazione globo che ruota verso la nuova citta'); altrimenti rebuild.
        """
        web = getattr(self, "_web", None)
        city = data.get("city", "?")
        geo  = data.get("geo")  or {}
        pois = data.get("pois") or []
        if web is not None and geo.get("lat") is not None and geo.get("lon") is not None:
            try:
                lat = float(geo["lat"]); lon = float(geo["lon"])
                pts = [{"lat": lat, "lon": lon, "title": city, "primary": True}]
                for p in (pois or [])[:14]:
                    try:
                        pts.append({
                            "lat": float(p.get("lat")),
                            "lon": float(p.get("lon")),
                            "title": (p.get("title") or ""),
                        })
                    except Exception:
                        pass
                pts_json  = json.dumps(pts, ensure_ascii=False)
                city_json = json.dumps(city, ensure_ascii=False)
                web.page().runJavaScript(
                    f"window.jarvisFlyTo && window.jarvisFlyTo({lat}, {lon}, {city_json}, {pts_json});"
                )
                # Aggiorna pannello di telemetria a destra
                self._refresh_right_panel(data)
                return
            except Exception as e:
                print(f"[MapOverlay] flyTo error: {e}")

        # Fallback: ricostruisci da zero
        old = self.layout()
        if old is not None:
            while old.count():
                item = old.takeAt(0)
                w = item.widget()
                if w:
                    w.deleteLater()
            QWidget().setLayout(old)
        self._build(data)

    def _refresh_right_panel(self, data: dict):
        """No-op se non c'e' un pannello laterale da ridisegnare."""
        # In questa versione la telemetria a destra resta quella iniziale;
        # il globo si occupa di mostrare la nuova citta'.
        return

    def eventFilter(self, obj, event):
        # Auto-resize con il parent
        from PyQt6.QtCore import QEvent
        if event.type() == QEvent.Type.Resize:
            self.setGeometry(0, 0, obj.width(), obj.height())
        return False


class _ChatOverlay(QFrame):
    """Mini-chat spostabile con drag-and-drop dell'header."""
    def __init__(self, parent, on_send):
        super().__init__(parent)
        self._on_send = on_send
        self._drag_pos = None
        self.setObjectName("ChatOverlay")
        self.setStyleSheet(f"""
            QFrame#ChatOverlay {{
                background: rgba(1, 13, 20, 240);
                border: 1px solid {C.PRI};
            }}
            QLabel {{ color: {C.TEXT}; }}
            QLabel#chatHead {{
                color: {C.PRI}; background: {C.PANEL2};
                padding: 6px 10px;
                border-bottom: 1px solid {C.BORDER};
            }}
            QTextEdit, QLineEdit {{
                background: {C.PANEL};
                color: {C.TEXT};
                border: 1px solid {C.BORDER};
                padding: 6px;
            }}
            QPushButton {{
                background: {C.PRI_GHO}; color: {C.PRI};
                border: 1px solid {C.PRI_DIM}; padding: 6px 12px;
            }}
            QPushButton:hover {{ color: {C.WHITE}; border-color: {C.PRI}; }}
        """)
        lay = QVBoxLayout(self); lay.setContentsMargins(0,0,0,0); lay.setSpacing(0)
        head = QLabel("J.A.R.V.I.S  //  CHAT   (drag me)")
        head.setObjectName("chatHead")
        head.setFont(QFont("Consolas", 9, QFont.Weight.Bold))
        head.setCursor(Qt.CursorShape.SizeAllCursor)
        self._head = head
        lay.addWidget(head)

        self._txt = QTextEdit(); self._txt.setReadOnly(True)
        lay.addWidget(self._txt, stretch=1)

        bot = QHBoxLayout(); bot.setContentsMargins(8,6,8,8)
        self._inp = QLineEdit(); self._inp.setPlaceholderText("Type to JARVIS...")
        self._inp.returnPressed.connect(self._send)
        send = QPushButton("SEND"); send.clicked.connect(self._send)
        bot.addWidget(self._inp, stretch=1); bot.addWidget(send)
        lay.addLayout(bot)

    def _send(self):
        text = self._inp.text().strip()
        if not text:
            return
        self.append_user(text)
        self._inp.clear()
        try:
            self._on_send(text)
        except Exception:
            pass

    def append_user(self, text: str):
        if not text:
            return
        # Evita duplicati consecutivi
        if getattr(self, "_last_user", "") == text:
            return
        self._last_user = text
        self._txt.append(f"<span style='color:{C.PRI};'><b>You:</b></span> {self._esc(text)}")
        self._scroll_bottom()

    def append_jarvis(self, text: str):
        if not text:
            return
        if getattr(self, "_last_jarvis", "") == text:
            return
        self._last_jarvis = text
        self._txt.append(
            f"<span style='color:#7cd2ff;'><b>JARVIS:</b></span> "
            f"<span style='color:#dff3ff;'>{self._esc(text)}</span>"
        )
        self._scroll_bottom()

    @staticmethod
    def _esc(s: str) -> str:
        return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))

    def _scroll_bottom(self):
        try:
            sb = self._txt.verticalScrollBar()
            sb.setValue(sb.maximum())
        except Exception:
            pass

    def mousePressEvent(self, e):
        if self._head.geometry().contains(e.position().toPoint()):
            self._drag_pos = e.globalPosition().toPoint() - self.frameGeometry().topLeft()
            e.accept()

    def mouseMoveEvent(self, e):
        if self._drag_pos is not None and (e.buttons() & Qt.MouseButton.LeftButton):
            new_p = e.globalPosition().toPoint() - self._drag_pos
            local = self.parent().mapFromGlobal(new_p)
            x = max(0, min(local.x(), self.parent().width()  - self.width()))
            y = max(0, min(local.y(), self.parent().height() - self.height()))
            self.move(x, y)

    def mouseReleaseEvent(self, e):
        self._drag_pos = None


class _StatsOverlay(QFrame):
    """Pannello flottante con CPU/MEM/NET/GPU/TMP/UPTIME del PC."""
    def __init__(self, parent, main_window):
        super().__init__(parent)
        self._win = main_window
        self._drag_pos = None
        self.setObjectName("StatsOverlay")
        self.setStyleSheet(f"""
            QFrame#StatsOverlay {{
                background: rgba(0, 10, 16, 245);
                border: 1px solid {C.PRI};
            }}
            QLabel {{ color: {C.TEXT}; background: transparent; }}
            QLabel#statsHead {{
                color: {C.PRI}; background: {C.PANEL2};
                padding: 6px 10px;
                border-bottom: 1px solid {C.BORDER};
            }}
            QPushButton {{
                background: {C.PRI_GHO}; color: {C.PRI};
                border: 1px solid {C.PRI_DIM}; padding: 4px 10px;
            }}
            QPushButton:hover {{ color: {C.WHITE}; border-color: {C.PRI}; }}
        """)
        lay = QVBoxLayout(self); lay.setContentsMargins(0,0,0,0); lay.setSpacing(0)

        head_row = QHBoxLayout(); head_row.setContentsMargins(0,0,0,0); head_row.setSpacing(0)
        head = QLabel("J.A.R.V.I.S  //  SYSTEM STATS   (drag)")
        head.setObjectName("statsHead")
        head.setFont(QFont("Consolas", 9, QFont.Weight.Bold))
        head.setCursor(Qt.CursorShape.SizeAllCursor)
        self._head = head
        head_row.addWidget(head, stretch=1)

        head_wrap = QWidget(); head_wrap.setLayout(head_row)
        lay.addWidget(head_wrap)

        body = QWidget()
        bl = QVBoxLayout(body); bl.setContentsMargins(12, 12, 12, 12); bl.setSpacing(8)

        self._bars = {}
        for k, (label, col) in [
            ("cpu", ("CPU", C.PRI)),
            ("mem", ("MEM", C.ACC2)),
            ("net", ("NET", C.GREEN)),
            ("gpu", ("GPU", C.ACC)),
            ("tmp", ("TMP", "#ff6688")),
        ]:
            mb = MetricBar(label, col)
            self._bars[k] = mb
            bl.addWidget(mb)

        self._uptime_lbl = QLabel("UP  --:--")
        self._uptime_lbl.setFont(QFont("Courier New", 9, QFont.Weight.Bold))
        self._uptime_lbl.setStyleSheet(f"color: {C.GREEN}; background: transparent;")
        bl.addWidget(self._uptime_lbl)

        self._proc_lbl = QLabel("PROC  --")
        self._proc_lbl.setFont(QFont("Courier New", 9))
        self._proc_lbl.setStyleSheet(f"color: {C.TEXT_MED}; background: transparent;")
        bl.addWidget(self._proc_lbl)

        bl.addStretch(1)
        bot = QHBoxLayout()
        btn = QPushButton("CLOSE")
        btn.clicked.connect(self.hide)
        bot.addStretch(1); bot.addWidget(btn)
        bl.addLayout(bot)

        lay.addWidget(body, stretch=1)

        self._tmr = QTimer(self)
        self._tmr.timeout.connect(self.refresh)
        self._tmr.start(2000)
        self.refresh()

    def refresh(self):
        try:
            snap = _metrics.snapshot()
        except Exception:
            return
        cpu = snap["cpu"]; self._bars["cpu"].set_value(cpu, f"{cpu:.0f}%")
        mem = snap["mem"]; self._bars["mem"].set_value(mem, f"{mem:.0f}%")
        net = snap["net"]
        net_str = (f"{net*1024:.0f}KB/s" if net < 1.0 else f"{net:.1f}MB/s")
        self._bars["net"].set_value(min(100, net * 10), net_str)
        gpu = snap["gpu"]
        if gpu >= 0:
            self._bars["gpu"].set_value(gpu, f"{gpu:.0f}%")
        else:
            self._bars["gpu"].set_value(0, "N/A")
        tmp = snap["tmp"]
        if tmp >= 0:
            self._bars["tmp"].set_value(min(100, tmp), f"{tmp:.0f}°C")
        else:
            self._bars["tmp"].set_value(0, "N/A")
        try:
            elapsed = time.time() - psutil.boot_time()
            h = int(elapsed // 3600); m = int((elapsed % 3600) // 60)
            self._uptime_lbl.setText(f"UP  {h:02d}:{m:02d}")
        except Exception:
            pass
        try:
            self._proc_lbl.setText(f"PROC  {len(psutil.pids())}")
        except Exception:
            pass

    def mousePressEvent(self, e):
        if self._head.geometry().contains(e.position().toPoint()):
            self._drag_pos = e.globalPosition().toPoint() - self.frameGeometry().topLeft()
            e.accept()
    def mouseMoveEvent(self, e):
        if self._drag_pos is not None and (e.buttons() & Qt.MouseButton.LeftButton):
            new_p = e.globalPosition().toPoint() - self._drag_pos
            local = self.parent().mapFromGlobal(new_p)
            x = max(0, min(local.x(), self.parent().width()  - self.width()))
            y = max(0, min(local.y(), self.parent().height() - self.height()))
            self.move(x, y)
    def mouseReleaseEvent(self, e):
        self._drag_pos = None


class _WhatsAppOverlay(QFrame):
    """Mini-finestra WhatsApp Web spostabile con dashboard contatti.

    Modalita':
      - "web"      : carica web.whatsapp.com dentro un QWebEngineView con
                     profilo persistente (la QR-scan resta valida).
      - "dashboard": mostra la lista di TUTTI i contatti estratti da
                     WhatsApp Web + casella per comporre il messaggio.
                     Si attiva con l'azione `send_message`.

    Espone anche un polling che riconosce nuove chat non lette e notifica
    JARVIS via callback (`on_new_message`).
    """
    _STORAGE = str(Path.home() / ".jarvis_whatsapp_profile")

    def __init__(self, parent, on_new_message=None):
        super().__init__(parent)
        self._drag_pos = None
        self._on_new_message = on_new_message
        self._seen_unread = set()  # nomi chat gia' notificate
        self._notify_started = False
        # Stato schermo intero / finestrella. _normal_geom conserva la
        # geometria "windowed" cosi' un minimize la ripristina identica.
        self._is_fullscreen = False
        self._normal_geom = None
        self.setObjectName("WhatsAppOverlay")
        self.setStyleSheet(f"""
            QFrame#WhatsAppOverlay {{
                background: rgba(0, 10, 16, 250);
                border: 1px solid #25d366;
            }}
            QLabel#waHead {{
                color: #25d366; background: {C.PANEL2};
                padding: 6px 10px;
                border-bottom: 1px solid {C.BORDER};
            }}
            QLabel#waDashTitle {{
                color: #25d366; padding: 6px 10px;
                border-bottom: 1px solid #1a8a47;
            }}
            QPushButton {{
                background: {C.PANEL2}; color: #25d366;
                border: 1px solid #1a8a47; padding: 4px 10px;
            }}
            QPushButton:hover {{ color: white; border-color: #25d366; }}
            QListWidget#waContacts {{
                background: {C.PANEL}; color: #b6f0c8;
                border: 1px solid #1a8a47;
                font-family: Consolas, monospace; font-size: 11px;
            }}
            QListWidget#waContacts::item:selected {{
                background: #1a8a47; color: white;
            }}
            QLineEdit#waSearch, QTextEdit#waMsg {{
                background: {C.PANEL}; color: #d8f8ff;
                border: 1px solid #1a8a47; padding: 6px;
                font-family: Consolas, monospace; font-size: 11px;
            }}
        """)
        lay = QVBoxLayout(self); lay.setContentsMargins(0,0,0,0); lay.setSpacing(0)
        head = QLabel("J.A.R.V.I.S  //  WHATSAPP   (drag)")
        head.setObjectName("waHead")
        head.setFont(QFont("Consolas", 9, QFont.Weight.Bold))
        head.setCursor(Qt.CursorShape.SizeAllCursor)
        self._head = head
        lay.addWidget(head)

        # --- SOLO WhatsApp Web (dashboard rimossa: tutto via voce) -------
        if not _HAS_WEBENGINE:
            lbl = QLabel("PyQt6-WebEngine non installato.\n"
                         "Installa: pip install PyQt6-WebEngine")
            lbl.setStyleSheet("color:#ffae42; padding:24px;")
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lay.addWidget(lbl, stretch=1)
            self._web = None
        else:
            from PyQt6.QtWebEngineCore import QWebEngineProfile, QWebEnginePage
            os.makedirs(self._STORAGE, exist_ok=True)
            self._profile = QWebEngineProfile("JarvisWhatsApp", self)
            self._profile.setPersistentStoragePath(self._STORAGE)
            self._profile.setCachePath(self._STORAGE + "/cache")
            self._profile.setHttpUserAgent(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
            self._page = QWebEnginePage(self._profile, self)
            self._web = QWebEngineView(self)
            self._web.setPage(self._page)
            self._web.setUrl(QUrl("https://web.whatsapp.com/"))
            lay.addWidget(self._web, stretch=1)

        bot = QHBoxLayout(); bot.setContentsMargins(8, 6, 8, 8)
        btn_reload = QPushButton("RELOAD")
        btn_reload.clicked.connect(lambda: self._web and self._web.reload())
        bot.addWidget(btn_reload)
        bot.addStretch(1)
        btn_close = QPushButton("CLOSE")
        btn_close.clicked.connect(self.hide)
        bot.addWidget(btn_close)
        lay.addLayout(bot)

        # Polling notifiche (ogni 8s) per messaggi nuovi.
        # Gira ANCHE quando la finestra e' nascosta, cosi' JARVIS puo'
        # annunciare vocalmente messaggi in arrivo senza overlay aperto.
        self._notify_timer = QTimer(self)
        self._notify_timer.timeout.connect(self._poll_notifications)

    # ----- Notifiche messaggi in arrivo ------------------------------
    def start_notifications(self):
        if self._notify_started:
            return
        self._notify_started = True
        # Bootstrap dopo 6s per dare tempo al QR scan, poi ogni 15s (CPU-friendly).
        QTimer.singleShot(6000, lambda: self._notify_timer.start(15000))

    def _poll_notifications(self):
        # IMPORTANTE: gira anche se la finestra e' nascosta — JARVIS deve
        # annunciare i nuovi messaggi senza richiedere l'apertura del
        # pannello WhatsApp. Richiede solo che il QWebEngineView esista
        # e WhatsApp Web sia loggato (QR gia' scansionato — la sessione
        # e' persistente in _STORAGE).
        if not self._web:
            return
        js = r"""
        (function() {
            try {
                var out = [];
                // Cerca in TUTTI i pane laterali (chat normali + archiviate +
                // pannello "Risultati ricerca").
                var items = document.querySelectorAll(
                  '#pane-side [role="listitem"], #side [role="listitem"], '
                  + '[aria-label="Chat list"] [role="listitem"], '
                  + '[aria-label*="Elenco chat" i] [role="listitem"]'
                );
                var seen = {};
                items.forEach(function(it) {
                    // 1) badge classico con aria-label "N unread message(s)" / "non lett*"
                    var badge = it.querySelector(
                      'span[aria-label$="unread message"], ' +
                      'span[aria-label$="unread messages"], ' +
                      'span[aria-label*="non letto" i], ' +
                      'span[aria-label*="non lett" i], ' +
                      'span[aria-label*="ungelesen" i], ' +
                      'span[aria-label*="no leid" i]'
                    );
                    // 2) Fallback: badge numerico (qualsiasi span con
                    //    aria-label numerico dentro un listitem chat)
                    if (!badge) {
                        var spans = it.querySelectorAll('span[aria-label]');
                        for (var i = 0; i < spans.length; i++) {
                            var al = (spans[i].getAttribute('aria-label')||'').trim();
                            // Match "1", "2", "12+", ecc. -> badge unread
                            if (/^\d+\+?$/.test(al)) { badge = spans[i]; break; }
                        }
                    }
                    if (!badge) return;
                    var nm = it.querySelector('span[dir="auto"][title]');
                    var name = nm ? (nm.getAttribute('title') || nm.textContent) : '';
                    name = (name || '').trim();
                    if (name && !seen[name]) { seen[name] = 1; out.push(name); }
                });
                return JSON.stringify(out);
            } catch(e) { return '[]'; }
        })();
        """
        def _done(r):
            try:
                import json as _json
                names = _json.loads(r or "[]")
            except Exception:
                names = []
            new_ones = [n for n in names if n not in self._seen_unread]
            for n in new_ones:
                self._seen_unread.add(n)
                if callable(self._on_new_message):
                    try:
                        self._on_new_message(n)
                    except Exception:
                        pass
            # se una chat non e' piu' unread, rimuovila per riconoscerla la prossima volta
            self._seen_unread = self._seen_unread.intersection(set(names))
        self._run_js(js, _done)

    def _run_js(self, code: str, callback=None):
        if not self._web:
            if callback: callback(None)
            return
        if callback is None:
            self._page.runJavaScript(code)
        else:
            self._page.runJavaScript(code, callback)

    def read_unread_chats(self, callback=None):
        """Estrae nome/conteggio dalle chat non lette di WhatsApp Web."""
        js = r"""
        (function() {
            try {
                var rows = document.querySelectorAll('[role="listitem"], [aria-label*="Chat"], [data-testid="chat-list"] > div > div');
                var out = [];
                rows.forEach(function(r) {
                    var bad = r.querySelector('[aria-label*="unread message"], span[aria-label$="unread message"], span[aria-label$="unread messages"]');
                    if (!bad) return;
                    var nm = r.querySelector('span[dir="auto"][title], span[title]');
                    var name = nm ? (nm.getAttribute('title') || nm.textContent) : '';
                    var cnt = bad.textContent || bad.getAttribute('aria-label') || '';
                    if (name) out.push(name + ' (' + cnt.trim() + ')');
                });
                if (!out.length) return 'Nessuna chat non letta.';
                return 'Chat non lette: ' + out.join(', ');
            } catch(e) { return 'Errore lettura: ' + e.message; }
        })();
        """
        self._run_js(js, callback or (lambda _r: None))

    def send_message(self, recipient: str, message: str, callback=None):
        """Cerca il contatto e invia il messaggio iniettando eventi nella UI.

        FIX: usa input/beforeinput events compatibili con il React di
        WhatsApp Web, clicca il bottone 'Send' come metodo PRIMARIO (non
        piu' fallback) e seleziona la chat corretta filtrando per nome.
        """
        rec = (recipient or "").replace("\\", "\\\\").replace("'", "\\'")
        msg = (message   or "").replace("\\", "\\\\").replace("'", "\\'").replace("\n", "\\n")
        js = r"""
        (async function() {
          function sleep(ms){return new Promise(r=>setTimeout(r,ms));}

          // React-friendly setter per contenteditable di WhatsApp Web.
          // Simula i beforeinput/input events che React Lexical ascolta.
          function setEditableValue(el, val) {
            el.focus();
            // Pulisci eventuale testo presente
            try {
              var range = document.createRange();
              range.selectNodeContents(el);
              var sel = window.getSelection();
              sel.removeAllRanges();
              sel.addRange(range);
            } catch(e) {}
            try { document.execCommand('delete', false); } catch(e) {}

            // Inserisci il testo: prima prova execCommand (compat),
            // poi forza un input event con il valore.
            try { document.execCommand('insertText', false, val); } catch(e) {}

            // Se il contenuto non e' stato impostato, fallback DOM diretto
            if ((el.innerText || '').indexOf(val) === -1) {
              el.textContent = val;
            }

            // Notifica React/Lexical del cambiamento
            try {
              el.dispatchEvent(new InputEvent('beforeinput', {
                bubbles: true, cancelable: true, inputType: 'insertText', data: val
              }));
              el.dispatchEvent(new InputEvent('input', {
                bubbles: true, cancelable: true, inputType: 'insertText', data: val
              }));
            } catch(e) {}
          }

          function normalize(s) {
            return (s || '').toLowerCase()
              .normalize('NFD').replace(/[\u0300-\u036f]/g, '');
          }

          function findBestChat(name) {
            // I risultati della search appaiono in #pane-side, ma anche
            // in eventuali pannelli "Risultati ricerca" / "Archiviate".
            // Ci copriamo TUTTI i listitem visibili sotto #side.
            var items = document.querySelectorAll(
              '#side [role="listitem"], #pane-side [role="listitem"]'
            );
            var q = normalize(name);
            if (!q) return null;
            var exact = null, contains = null, prefix = null, fuzzy = null;
            items.forEach(function(it) {
              var t = it.querySelector('span[dir="auto"][title]');
              if (!t) return;
              var raw = (t.getAttribute('title') || t.textContent || '').trim();
              var n = normalize(raw);
              if (!n) return;
              if (!exact && n === q) exact = it;
              else if (!prefix && n.indexOf(q) === 0) prefix = it;
              else if (!contains && n.indexOf(q) !== -1) contains = it;
              else if (!fuzzy) {
                // match fuzzy: tutti i caratteri di q presenti in ordine in n
                var i = 0, j = 0;
                while (i < q.length && j < n.length) {
                  if (q[i] === n[j]) i++;
                  j++;
                }
                if (i === q.length) fuzzy = it;
              }
            });
            return exact || prefix || contains || fuzzy || items[0] || null;
          }

          try {
            // ── 1. Cerca contatto (la search di WA include archiviati) ─
            // I selettori della search box cambiano spesso (data-tab="3",
            // aria-label "Cerca o inizia una nuova chat", o solo role=textbox).
            function pickSearchBox() {
              return document.querySelector(
                '[contenteditable="true"][data-tab="3"], '
                + 'div[contenteditable="true"][aria-label*="erca" i], '
                + 'div[contenteditable="true"][aria-label*="earch" i], '
                + 'header [contenteditable="true"][role="textbox"], '
                + '#side [contenteditable="true"][role="textbox"], '
                + 'div[contenteditable="true"][role="textbox"]'
              );
            }
            var search = pickSearchBox();
            if (!search) {
              await sleep(1200);
              search = pickSearchBox();
            }
            if (!search) return 'ERR: Search box non trovato — apri WhatsApp Web prima.';
            // Pulisci la search e digita
            setEditableValue(search, '');
            await sleep(150);
            setEditableValue(search, '__REC__');
            await sleep(1800);

            // ── 2. Click sulla chat migliore (fuzzy match), con retry ──
            var chat = findBestChat('__REC__');
            if (!chat) {
              await sleep(900);
              chat = findBestChat('__REC__');
            }
            if (!chat) return 'ERR: Contatto __REC__ non trovato.';
            // Click "vero" (pointer + click) per sbloccare apri-chat
            try {
              var r = chat.getBoundingClientRect();
              var x = r.left + r.width/2, y = r.top + r.height/2;
              ['pointerdown','mousedown','pointerup','mouseup','click'].forEach(function(t){
                chat.dispatchEvent(new MouseEvent(t, {bubbles:true, cancelable:true, clientX:x, clientY:y, button:0}));
              });
            } catch(e) { chat.click(); }
            await sleep(1400);

            // ── 3. Trova la casella messaggio (footer) ──────────
            // WhatsApp Web mette data-tab="10" sul footer compose,
            // o aria-label/placeholder contenente 'message'/'messaggio'.
            function pickMsgBox() {
              return document.querySelector(
                'footer [contenteditable="true"][data-tab="10"], '
                + 'footer div[contenteditable="true"][role="textbox"], '
                + '[contenteditable="true"][aria-label*="essag" i], '
                + '[contenteditable="true"][data-tab="10"], '
                + 'div[contenteditable="true"][aria-placeholder*="essag" i]'
              );
            }
            var msgBox = pickMsgBox();
            if (!msgBox) {
              await sleep(800);
              msgBox = pickMsgBox();
            }
            if (!msgBox) {
              // ultimo contenteditable della pagina (escludendo search)
              var all = document.querySelectorAll('[contenteditable="true"]');
              for (var i = all.length - 1; i >= 0; i--) {
                if (all[i] !== search) { msgBox = all[i]; break; }
              }
            }
            if (!msgBox) return 'ERR: Casella messaggio non trovata.';

            setEditableValue(msgBox, '__MSG__');
            await sleep(700);

            // ── 4. INVIO: click sul bottone Send (PRIMARIO) ─────
            function pickSendBtn() {
              return document.querySelector(
                'footer button[aria-label="Invia"], '
                + 'footer button[aria-label="Send"], '
                + 'footer button[aria-label*="nvia" i], '
                + 'footer button[aria-label*="end" i], '
                + 'footer span[data-icon="send"], '
                + 'footer span[data-icon="wds-ic-send-filled"], '
                + 'footer span[data-icon*="send" i], '
                + 'button[aria-label="Invia"], button[aria-label="Send"], '
                + 'span[data-icon="send"], span[data-icon="wds-ic-send-filled"], '
                + 'span[data-icon*="send" i]'
              );
            }
            var sendBtn = pickSendBtn();
            if (!sendBtn) { await sleep(400); sendBtn = pickSendBtn(); }
            if (sendBtn) {
              var btn = sendBtn.closest('button') || sendBtn;
              try {
                var rb = btn.getBoundingClientRect();
                var xb = rb.left + rb.width/2, yb = rb.top + rb.height/2;
                ['pointerdown','mousedown','pointerup','mouseup','click'].forEach(function(t){
                  btn.dispatchEvent(new MouseEvent(t, {bubbles:true, cancelable:true, clientX:xb, clientY:yb, button:0}));
                });
              } catch(e) { btn.click(); }
              return 'OK';
            }

            // ── 4-bis. Fallback: invio con Enter sintetico ──────
            msgBox.focus();
            ['keydown','keypress','keyup'].forEach(function(type){
              msgBox.dispatchEvent(new KeyboardEvent(type, {
                bubbles:true, cancelable:true, key:'Enter', code:'Enter',
                keyCode:13, which:13, charCode: (type==='keypress'?13:0)
              }));
            });
            return 'OK_ENTER';
          } catch(e) { return 'ERR: ' + e.message; }
        })();
        """.replace("__REC__", rec).replace("__MSG__", msg)
        # Wrapper che passa il risultato grezzo della JS (es. "OK", "OK_ENTER",
        # "ERR: ...") al callback come secondo argomento, e True/False come
        # primo. Cosi' il chiamante puo' loggare la causa del fallimento.
        def _done(r):
            raw = str(r) if r is not None else ""
            ok = ("OK" in raw)
            if callback:
                try:
                    callback(ok, raw)
                except TypeError:
                    # callback con la firma vecchia (solo ok)
                    callback(ok)
        self._run_js(js, _done)

    def set_fullscreen(self):
        """Espande la finestrella WhatsApp a tutto il central widget JARVIS.
        Conserva la geometria 'windowed' corrente per poterla ripristinare
        con set_windowed()."""
        try:
            par = self.parent()
            if par is None:
                return
            # Salva la geometria attuale SOLO se non eravamo gia' fullscreen,
            # cosi' minimizzare ripristina esattamente la finestrella.
            if not self._is_fullscreen:
                self._normal_geom = self.geometry()
            self.setGeometry(0, 0, par.width(), par.height())
            self._is_fullscreen = True
            self.raise_()
            self.show()
        except Exception:
            pass

    def set_windowed(self):
        """Ripristina la finestrella WhatsApp alle dimensioni originali."""
        try:
            par = self.parent()
            if par is None:
                return
            if self._normal_geom is not None:
                self.setGeometry(self._normal_geom)
            else:
                ow, oh = 460, 620
                self.setGeometry(par.width() - ow - 24,
                                 (par.height() - oh) // 2, ow, oh)
            self._is_fullscreen = False
            self.raise_()
            self.show()
        except Exception:
            pass

    def mousePressEvent(self, e):
        if self._head.geometry().contains(e.position().toPoint()):
            self._drag_pos = e.globalPosition().toPoint() - self.frameGeometry().topLeft()
            e.accept()
    def mouseMoveEvent(self, e):
        if self._drag_pos is not None and (e.buttons() & Qt.MouseButton.LeftButton):
            new_p = e.globalPosition().toPoint() - self._drag_pos
            local = self.parent().mapFromGlobal(new_p)
            x = max(0, min(local.x(), self.parent().width()  - self.width()))
            y = max(0, min(local.y(), self.parent().height() - self.height()))
            self.move(x, y)
    def mouseReleaseEvent(self, e):
        self._drag_pos = None


class _RootShim:
    def __init__(self, app: QApplication):
        self._app = app
    def mainloop(self):
        self._app.exec()
    def protocol(self, *_):
        pass


class JarvisUI:
    def __init__(self, face_path: str, size=None):
        self._app = QApplication.instance() or QApplication(sys.argv)
        self._app.setStyle("Fusion")
        self._win = MainWindow(face_path)
        self._win.show()
        self.root = _RootShim(self._app)

    @property
    def muted(self) -> bool:
        return self._win._muted

    @muted.setter
    def muted(self, v: bool):
        if v != self._win._muted:
            self._win._toggle_mute()

    @property
    def current_file(self) -> str | None:
        return self._win._drop_zone.current_file()

    @property
    def on_text_command(self):
        return self._win.on_text_command

    @on_text_command.setter
    def on_text_command(self, cb):
        self._win.on_text_command = cb

    def set_state(self, state: str):
        self._win._state_sig.emit(state)

    def write_log(self, text: str):
        self._win._log_sig.emit(text)

    def wait_for_api_key(self):
        while not self._win._ready:
            time.sleep(0.1)

    def start_speaking(self):
        self.set_state("SPEAKING")

    def stop_speaking(self):
        if not self.muted:
            self.set_state("LISTENING")

    # =====================================================================
    # MAP / CHAT / STATS OVERLAYS  (richiesta utente)
    # API thread-safe: emette segnali che vengono processati sul main
    # thread Qt. Sostituiscono la finestra Tk separata del vecchio
    # jarvis_map.py (FIX CPU 100%).
    # =====================================================================
    def show_map(self, city, geo, weather=None, wiki=None, pois=None):
        self._win._map_sig.emit({
            "city":    city,
            "geo":     geo or {},
            "weather": weather or {},
            "wiki":    wiki or {},
            "pois":    pois or [],
        })

    def close_map(self) -> bool:
        return bool(self._win._close_map_invoke())

    def is_map_open(self) -> bool:
        ov = getattr(self._win, "_map_overlay", None)
        return bool(ov and ov.isVisible())

    def show_chat_overlay(self):
        self._win._chat_sig.emit()

    def show_stats_overlay(self):
        self._win._stats_sig.emit()

    def show_whatsapp_overlay(self, action: str = "open",
                              recipient: str = "", message: str = ""):
        self._win._whatsapp_sig.emit({
            "action":    action,
            "recipient": recipient,
            "message":   message,
        })

    # ===== Notifiche WhatsApp in arrivo ==================================
    @property
    def wa_pending_reply(self) -> str | None:
        """Nome dell'ultimo contatto WhatsApp che ha mandato un nuovo
        messaggio non ancora gestito. None se nessuno."""
        return getattr(self._win, "_wa_pending_reply", None)

    def clear_wa_pending_reply(self):
        """Da chiamare dopo aver risposto al pending contact."""
        try:
            self._win._wa_pending_reply = None
        except Exception:
            pass

    def set_on_whatsapp_new_message(self, cb):
        """Registra una callback `cb(name)` chiamata sul main thread Qt
        ogni volta che arriva un nuovo messaggio WhatsApp non letto."""
        self._win._wa_new_msg_cb = cb

    def return_home(self) -> bool:
        self._win._home_sig.emit()
        return True