from PyQt5.QtCore import QByteArray, Qt
from PyQt5.QtGui import QColor, QIcon, QPainter, QPixmap
from PyQt5.QtSvg import QSvgRenderer
from PyQt5.QtWidgets import QGraphicsDropShadowEffect, QPushButton


def style_icon_button(button: QPushButton):
    button.setFixedSize(42, 36)
    button.setCursor(Qt.PointingHandCursor)
    button.setFlat(False)
    shadow = QGraphicsDropShadowEffect(button)
    shadow.setBlurRadius(14)
    shadow.setOffset(2, 2)
    shadow.setColor(QColor(0, 0, 0, 140))
    button.setGraphicsEffect(shadow)


def make_icon(svg_markup: str, size: int = 18) -> QIcon:
    renderer = QSvgRenderer(QByteArray(svg_markup.encode("utf-8")))
    pix = QPixmap(size, size)
    pix.fill(Qt.transparent)
    painter = QPainter(pix)
    renderer.render(painter)
    painter.end()
    return QIcon(pix)


ICONS = {
    "play": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path fill="#FFFFFF" d="M8 5v14l11-7z"/></svg>',
    "pause": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path fill="#FFFFFF" d="M6 5h4v14H6zm8 0h4v14h-4z"/></svg>',
    "stop": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><rect x="6" y="6" width="12" height="12" fill="#FFFFFF"/></svg>',
    "add": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path fill="#FFFFFF" d="M11 5h2v6h6v2h-6v6h-2v-6H5v-2h6z"/></svg>',
    "copy": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path fill="#FFFFFF" d="M8 8h11v11H8z"/><path fill="#FFFFFF" d="M5 5h11v2H7v9H5z"/></svg>',
    "paste": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path fill="#FFFFFF" d="M9 4h6l1 2h3v14H5V6h3zM7 8v10h10V8z"/></svg>',
    "splice": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path fill="#FFFFFF" d="M5 7h5l2 3 2-3h5v2h-4l-2 3 2 3h4v2h-5l-2-3-2 3H5v-2h4l2-3-2-3H5z"/></svg>',
    "cut": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path fill="#FFFFFF" d="M9 4a3 3 0 1 0 0 6 3 3 0 0 0 0-6zm6 10a3 3 0 1 0 0 6 3 3 0 0 0 0-6z"/><path fill="#FFFFFF" d="M21 5 13 11l-2 2-6 6-2-2 6-6 2-2 8-6z"/></svg>',
    "export": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path fill="#FFFFFF" d="M12 3 7 8h3v6h4V8h3z"/><path fill="#FFFFFF" d="M5 15h14v6H5z"/></svg>',
    "delete": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path fill="#FFFFFF" d="M7 7h10l-1 13H8z"/><path fill="#FFFFFF" d="M9 4h6l1 2h4v2H4V6h4z"/></svg>',
    "record": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><circle cx="12" cy="12" r="6" fill="#FFFFFF"/></svg>',
    "mute": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path fill="#FFFFFF" d="M4 10h4l5-4v12l-5-4H4z"/><path fill="#FFFFFF" d="m17 9 4 6-1.7 1.1-4-6z"/></svg>',
}
