"""Thread bridge between the Qt GUI thread and the asyncio engine thread.

* Engine/bus events are emitted from the engine thread and delivered to the GUI
  thread through a queued signal.
* GUI actions run controller coroutines in the engine thread; results and
  errors are delivered back to the GUI thread.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from PySide6.QtCore import QObject, Qt, Signal, Slot

from app.async_runner import AsyncRunner
from app.controller import BridgeController, StartError
from app.events import Event, EventBus
from app.settings import Settings

log = logging.getLogger(__name__)


class QtBridge(QObject):
    event = Signal(object)            # GUI-thread delivery of app.events.Event
    _raw_event = Signal(object)
    _done = Signal(object, object, object)

    def __init__(self, settings: Settings, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.settings = settings
        self.runner = AsyncRunner()
        self.runner.start()
        self.bus = EventBus()
        self._raw_event.connect(self._dispatch, Qt.ConnectionType.QueuedConnection)
        self._done.connect(self._deliver, Qt.ConnectionType.QueuedConnection)
        self.bus.subscribe(self._raw_event.emit)
        self.controller = BridgeController(settings, self.bus)

    @Slot(object)
    def _dispatch(self, ev: Event) -> None:
        self.event.emit(ev)

    @Slot(object, object, object)
    def _deliver(self, fut: Any, on_done: Callable | None, on_error: Callable | None) -> None:
        try:
            value = fut.result()
        except StartError as exc:
            if on_error:
                on_error(str(exc))
            return
        except Exception as exc:  # noqa: BLE001 - surfaced to the operator, never swallowed
            log.exception("background action failed")
            if on_error:
                on_error(f"{type(exc).__name__}: {exc}")
            return
        if on_done:
            on_done(value)

    def call(self, coro_factory: Callable[[], Any], on_done: Callable | None = None,
             on_error: Callable | None = None) -> None:
        """Run controller coroutine in the engine thread; callbacks run in the GUI thread."""
        fut = self.runner.submit(coro_factory())
        fut.add_done_callback(lambda f: self._done.emit(f, on_done, on_error))

    def emergency_stop(self) -> None:
        # deliberately synchronous: the gate closes before this method returns
        self.controller.emergency_stop_threadsafe()

    def shutdown(self) -> None:
        try:
            self.runner.run_sync(self.controller.shutdown(), timeout=20)
        except Exception:  # noqa: BLE001
            log.exception("shutdown failed")
        self.runner.stop()
