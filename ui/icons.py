"""Programmatic line icons (no image assets, no third-party logos)."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPainterPath, QPen, QPixmap, QPolygonF

from . import styles


def _canvas(size: int) -> tuple[QPixmap, QPainter]:
    pm = QPixmap(size * 2, size * 2)          # 2x for crisp rendering on HiDPI
    pm.setDevicePixelRatio(2.0)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    return pm, p


def _pen(color: str, width: float = 1.6) -> QPen:
    pen = QPen(QColor(color))
    pen.setWidthF(width)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    return pen


def pixmap(name: str, color: str | None = None, size: int = 18) -> QPixmap:
    color = color or styles.palette()["text"]
    pm, p = _canvas(size)
    s = float(size)
    p.setPen(_pen(color))
    c = QPointF(s / 2, s / 2)
    if name in ("play", "pause", "stop_circle"):
        p.drawEllipse(c, s * 0.42, s * 0.42)
    if name == "play":
        p.setBrush(QColor(color))
        p.drawPolygon(QPolygonF([QPointF(s * .42, s * .32), QPointF(s * .42, s * .68), QPointF(s * .7, s * .5)]))
    elif name == "pause":
        p.drawLine(QPointF(s * .41, s * .34), QPointF(s * .41, s * .66))
        p.drawLine(QPointF(s * .59, s * .34), QPointF(s * .59, s * .66))
    elif name == "stop":
        p.drawRoundedRect(QRectF(s * .24, s * .24, s * .52, s * .52), 2, 2)
    elif name == "emergency":
        path = QPainterPath()
        pts = [QPointF(s * .5, s * .1), QPointF(s * .92, s * .86), QPointF(s * .08, s * .86)]
        path.addPolygon(QPolygonF(pts + [pts[0]]))
        p.drawPath(path)
        p.drawLine(QPointF(s * .5, s * .38), QPointF(s * .5, s * .6))
        p.drawPoint(QPointF(s * .5, s * .73))
    elif name == "mic":
        p.drawRoundedRect(QRectF(s * .38, s * .14, s * .24, s * .44), s * .12, s * .12)
        path = QPainterPath()
        path.moveTo(s * .26, s * .46)
        path.cubicTo(s * .26, s * .78, s * .74, s * .78, s * .74, s * .46)
        p.drawPath(path)
        p.drawLine(QPointF(s * .5, s * .72), QPointF(s * .5, s * .86))
    elif name == "export":
        path = QPainterPath()
        path.moveTo(s * .28, s * .12)
        path.lineTo(s * .6, s * .12)
        path.lineTo(s * .74, s * .26)
        path.lineTo(s * .74, s * .88)
        path.lineTo(s * .28, s * .88)
        path.closeSubpath()
        p.drawPath(path)
        p.drawLine(QPointF(s * .51, s * .38), QPointF(s * .51, s * .7))
        p.drawPolyline(QPolygonF([QPointF(s * .4, s * .6), QPointF(s * .51, s * .71), QPointF(s * .62, s * .6)]))
    elif name == "human":
        p.drawEllipse(QPointF(s * .5, s * .32), s * .14, s * .14)
        path = QPainterPath()
        path.moveTo(s * .2, s * .86)
        path.cubicTo(s * .22, s * .56, s * .78, s * .56, s * .8, s * .86)
        p.drawPath(path)
    elif name == "next":
        p.drawPolyline(QPolygonF([QPointF(s * .26, s * .28), QPointF(s * .5, s * .5), QPointF(s * .26, s * .72)]))
        p.drawPolyline(QPolygonF([QPointF(s * .48, s * .28), QPointF(s * .72, s * .5), QPointF(s * .48, s * .72)]))
    elif name == "send":
        p.drawPolygon(QPolygonF([QPointF(s * .14, s * .2), QPointF(s * .88, s * .5), QPointF(s * .14, s * .8),
                                 QPointF(s * .28, s * .5)]))
    elif name == "browser":
        p.drawRoundedRect(QRectF(s * .12, s * .18, s * .76, s * .64), 2, 2)
        p.drawLine(QPointF(s * .12, s * .36), QPointF(s * .88, s * .36))
    elif name == "focus":
        p.drawPolyline(QPolygonF([QPointF(s * .14, s * .36), QPointF(s * .14, s * .14), QPointF(s * .36, s * .14)]))
        p.drawPolyline(QPolygonF([QPointF(s * .64, s * .14), QPointF(s * .86, s * .14), QPointF(s * .86, s * .36)]))
        p.drawPolyline(QPolygonF([QPointF(s * .86, s * .64), QPointF(s * .86, s * .86), QPointF(s * .64, s * .86)]))
        p.drawPolyline(QPolygonF([QPointF(s * .36, s * .86), QPointF(s * .14, s * .86), QPointF(s * .14, s * .64)]))
    elif name == "diagnose":
        p.drawEllipse(QPointF(s * .44, s * .44), s * .24, s * .24)
        p.drawLine(QPointF(s * .62, s * .62), QPointF(s * .86, s * .86))
    elif name == "settings":
        p.drawEllipse(c, s * .14, s * .14)
        for i in range(8):
            p.save()
            p.translate(c)
            p.rotate(i * 45)
            p.drawLine(QPointF(0, -s * .26), QPointF(0, -s * .38))
            p.restore()
        p.drawEllipse(c, s * .27, s * .27)
    elif name == "compact":
        p.drawRoundedRect(QRectF(s * .12, s * .2, s * .76, s * .6), 2, 2)
        p.drawLine(QPointF(s * .3, s * .5), QPointF(s * .7, s * .5))
    elif name == "sessions":
        for y in (.28, .5, .72):
            p.drawLine(QPointF(s * .2, s * y), QPointF(s * .8, s * y))
    elif name == "theme":
        p.drawEllipse(c, s * .32, s * .32)
        path = QPainterPath()
        path.moveTo(c.x(), c.y() - s * .32)
        path.arcTo(QRectF(c.x() - s * .32, c.y() - s * .32, s * .64, s * .64), 90, -180)
        path.closeSubpath()
        p.setBrush(QColor(color))
        p.drawPath(path)
    elif name == "copy":
        p.drawRoundedRect(QRectF(s * .32, s * .3, s * .48, s * .56), 2, 2)
        p.drawPolyline(QPolygonF([QPointF(s * .2, s * .68), QPointF(s * .2, s * .14), QPointF(s * .62, s * .14)]))
    elif name == "import":
        p.drawRoundedRect(QRectF(s * .16, s * .3, s * .68, s * .56), 2, 2)
        p.drawLine(QPointF(s * .5, s * .08), QPointF(s * .5, s * .56))
        p.drawPolyline(QPolygonF([QPointF(s * .38, s * .44), QPointF(s * .5, s * .56), QPointF(s * .62, s * .44)]))
    elif name == "new":
        p.drawLine(QPointF(s * .5, s * .2), QPointF(s * .5, s * .8))
        p.drawLine(QPointF(s * .2, s * .5), QPointF(s * .8, s * .5))
    elif name == "stop_circle":
        p.drawRect(QRectF(s * .38, s * .38, s * .24, s * .24))
    p.end()
    return pm


def icon(name: str, color: str | None = None, size: int = 18) -> QIcon:
    return QIcon(pixmap(name, color, size))


def monogram(letter: str, color: str, size: int = 30) -> QPixmap:
    """Neutral initial-letter mark for a participant (deliberately not a provider logo)."""
    pm, p = _canvas(size)
    s = float(size)
    pen = _pen(color, 1.4)
    p.setPen(pen)
    p.drawRoundedRect(QRectF(1.5, 1.5, s - 3, s - 3), 4, 4)
    f = QFont("Segoe UI")
    f.setPixelSize(int(s * 0.5))
    f.setWeight(QFont.Weight.DemiBold)
    p.setFont(f)
    p.drawText(QRectF(0, 0, s, s), Qt.AlignmentFlag.AlignCenter, (letter or "?")[:1].upper())
    p.end()
    return pm


def app_glyph(color: str, size: int = 22) -> QPixmap:
    """Three connected nodes – the EMERGENCE LAB mark."""
    pm, p = _canvas(size)
    s = float(size)
    p.setPen(_pen(color, 1.5))
    top, left, right = QPointF(s * .5, s * .22), QPointF(s * .22, s * .76), QPointF(s * .78, s * .76)
    p.drawLine(top, left)
    p.drawLine(top, right)
    p.drawLine(left, right)
    p.setBrush(QColor(styles.palette()["bg"]))
    for pt in (top, left, right):
        p.drawEllipse(pt, s * .12, s * .12)
    p.end()
    return pm


def dot(color: str, size: int = 10) -> QPixmap:
    pm, p = _canvas(size)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(color))
    p.drawEllipse(QPointF(size / 2, size / 2), size * .32, size * .32)
    p.end()
    return pm
