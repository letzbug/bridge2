"""Minimal PySide6 stand-in used ONLY for the structural GUI check when real PySide6 is unavailable.

It executes the application's own Python code paths (construction, wiring, event handlers) but renders
nothing. It does not validate Qt API usage or appearance.
"""
import re

INT_METHODS = {"x": 0, "y": 0, "width": 1920, "height": 1040, "value": 0, "maximum": 0, "minimum": 0,
               "currentIndex": 0, "currentRow": -1, "row": 0, "count": 0, "addTab": 0, "exec": 0,
               "rowCount": 0, "columnCount": 0, "findData": -1, "findText": -1,
               "pointSizeF": 9.5, "devicePixelRatio": 1}
STR_METHODS = {"text", "toPlainText", "currentText", "toString", "windowTitle", "placeholderText", "objectName"}
BOOL_FALSE = {"isChecked", "isVisible", "isHidden", "isMinimized", "isIconic"}
NONE_METHODS = {"currentData", "sender", "itemData"}
LIST_METHODS = {"selectedIndexes", "selectedItems", "children", "findChildren"}
TUPLE_METHODS = {"getSaveFileName": ("", ""), "getOpenFileName": ("", "")}
_SNAKE_INNER = re.compile(r"^_|[a-z0-9]_[a-z]")

class Anything:
    def __init__(self, *a, **k):
        pass
    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return Method(name)
    def __call__(self, *a, **k):
        return Anything()
    def __or__(self, o): return Anything()
    __ror__ = __and__ = __rand__ = __xor__ = __or__
    def __invert__(self): return Anything()
    def __int__(self): return 0
    def __index__(self): return 0
    def __float__(self): return 0.0
    def __bool__(self): return True
    def __lt__(self, o): return False
    __le__ = __gt__ = __ge__ = __lt__
    def __iter__(self): return iter(())
    def __len__(self): return 0
    def __bytes__(self): return b""
    def __str__(self): return ""

class Method:
    def __init__(self, name):
        self.name = name
    def __call__(self, *a, **k):
        n = self.name
        if n in INT_METHODS: return INT_METHODS[n]
        if n in STR_METHODS: return ""
        if n in BOOL_FALSE: return False
        if n in NONE_METHODS: return None
        if n in LIST_METHODS: return []
        if n in TUPLE_METHODS: return TUPLE_METHODS[n]
        if n.startswith("is") or n.startswith("has"): return True
        return Anything()
    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return Method(name)
    def connect(self, *a, **k): return Anything()
    def emit(self, *a, **k): return None
    def __or__(self, o): return Anything()
    __ror__ = __and__ = __rand__ = __or__
    def __int__(self): return 0
    def __index__(self): return 0
    def __bool__(self): return True

class Meta(type):
    def __getattr__(cls, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return Method(name)
    def __or__(cls, o): return Anything()

class QtBase(metaclass=Meta):
    def __init__(self, *a, **k):
        pass
    def __getattr__(self, name):
        # Qt API names are camelCase; snake_case misses are bugs in OUR code -> raise
        if name.startswith("__") or _SNAKE_INNER.search(name):
            raise AttributeError(f"{type(self).__name__!s} has no attribute {name!r}")
        return Method(name)
    def __bool__(self): return True

class BoundSignal:
    def __init__(self):
        self._handlers = []
    def connect(self, fn, *a, **k):
        self._handlers.append(fn)
    def disconnect(self, *a):
        self._handlers.clear()
    def emit(self, *args):
        import inspect
        for fn in list(self._handlers):
            try:
                params = inspect.signature(fn).parameters.values()
                if any(p.kind == p.VAR_POSITIONAL for p in params):
                    n = len(args)
                else:
                    n = len([p for p in params if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)])
            except (TypeError, ValueError):
                n = len(args)
            fn(*args[:n])

class Signal:
    def __init__(self, *types, **k):
        self._name = None
    def __set_name__(self, owner, name):
        self._name = "_sig_" + name
    def __get__(self, obj, objtype=None):
        if obj is None:
            return self
        d = obj.__dict__
        if self._name not in d:
            d[self._name] = BoundSignal()
        return d[self._name]

def Slot(*a, **k):
    return lambda fn: fn

def make_module_getattr(module_name):
    cache = {}
    def __getattr__(name):
        if name.startswith("__"):
            raise AttributeError(name)
        if name not in cache:
            cache[name] = Meta(name, (QtBase,), {"__module__": module_name})
        return cache[name]
    return __getattr__


# --- stateful widgets (enough to exercise load/store logic) -------------------------------
class _Visible(QtBase):
    def __init__(self, *a, **k):
        self._visible = False
        self._enabled = True
        self._props = {}
    def show(self): self._visible = True
    def hide(self): self._visible = False
    def setVisible(self, v): self._visible = bool(v)
    def isVisible(self): return self._visible
    def setEnabled(self, v): self._enabled = bool(v)
    def isEnabled(self): return self._enabled
    def setProperty(self, k, v): self._props[k] = v
    def property(self, k): return self._props.get(k)
    def blockSignals(self, b): return False


class QComboBox(_Visible):
    currentIndexChanged = Signal(int)
    currentTextChanged = Signal(str)
    def __init__(self, *a, **k):
        super().__init__()
        self._items = []
        self._index = -1
        self._edit_text = ""
    def addItem(self, text, data=None):
        self._items.append((text, data))
        if self._index < 0:
            self._index = 0
    def clear(self):
        self._items, self._index = [], -1
    def count(self): return len(self._items)
    def findData(self, data):
        for i, (_, d) in enumerate(self._items):
            if d == data:
                return i
        return -1
    def setCurrentIndex(self, i):
        if 0 <= i < len(self._items) and i != self._index:
            self._index = i
            self.currentIndexChanged.emit(i)
    def currentIndex(self): return self._index
    def currentData(self): return self._items[self._index][1] if 0 <= self._index < len(self._items) else None
    def currentText(self):
        return self._items[self._index][0] if 0 <= self._index < len(self._items) else self._edit_text
    def setCurrentText(self, t): self._edit_text = t
    def itemData(self, i): return self._items[i][1]
    def setEditable(self, b): pass


class QLineEdit(_Visible):
    editingFinished = Signal()
    textChanged = Signal(str)
    def __init__(self, text="", *a, **k):
        super().__init__()
        self._text = text if isinstance(text, str) else ""
    def text(self): return self._text
    def setText(self, t): self._text = t


class QPlainTextEdit(_Visible):
    textChanged = Signal()
    def __init__(self, text="", *a, **k):
        super().__init__()
        self._text = text if isinstance(text, str) else ""
    def toPlainText(self): return self._text
    def setPlainText(self, t): self._text = t
    def clear(self): self._text = ""
    def appendPlainText(self, t): self._text += t + "\n"


class QLabel(_Visible):
    def __init__(self, text="", *a, **k):
        super().__init__()
        self._text = text if isinstance(text, str) else ""
    def text(self): return self._text
    def setText(self, t): self._text = t


class QCheckBox(_Visible):
    toggled = Signal(bool)
    def __init__(self, text="", *a, **k):
        super().__init__()
        self._checked = False
    def isChecked(self): return self._checked
    def setChecked(self, v):
        if bool(v) != self._checked:
            self._checked = bool(v)
            self.toggled.emit(self._checked)


class QPushButton(QCheckBox):
    clicked = Signal(bool)
    def __init__(self, text="", *a, **k):
        super().__init__()
        self._text = text if isinstance(text, str) else ""
        self._checkable = False
    def setCheckable(self, b): self._checkable = b
    def text(self): return self._text
    def setText(self, t): self._text = t
    def click(self): self.clicked.emit(False)


class QToolButton(QPushButton):
    pass


class _Spin(_Visible):
    valueChanged = Signal(object)
    def __init__(self, *a, **k):
        super().__init__()
        self._v, self._lo, self._hi = 0, 0, 99
    def setRange(self, lo, hi): self._lo, self._hi = lo, hi
    def setValue(self, v): self._v = max(self._lo, min(self._hi, v))
    def value(self): return self._v


class QSpinBox(_Spin):
    pass


class QDoubleSpinBox(_Spin):
    pass


class QSlider(_Spin):
    pass


class QTabWidget(_Visible):
    def __init__(self, *a, **k):
        super().__init__()
        self._n = 0
    def addTab(self, w, title):
        self._n += 1
        return self._n - 1


_STATEFUL = {c.__name__: c for c in (QComboBox, QLineEdit, QPlainTextEdit, QLabel, QCheckBox, QPushButton,
                                      QToolButton, QSpinBox, QDoubleSpinBox, QSlider, QTabWidget)}


def make_widgets_getattr(module_name):
    base = make_module_getattr(module_name)
    def __getattr__(name):
        if name in _STATEFUL:
            return _STATEFUL[name]
        if name in ("QWidget", "QFrame", "QDialog", "QMainWindow", "QTextBrowser", "QProgressBar", "QScrollArea",
                    "QGroupBox", "QTableWidget", "QSplitter", "QDialogButtonBox", "QKeySequenceEdit"):
            cls = base(name)
            if not issubclass(cls, _Visible):
                cls = Meta(name, (_Visible,), {"__module__": module_name})
                _STATEFUL[name] = cls
            return cls
        return base(name)
    return __getattr__
