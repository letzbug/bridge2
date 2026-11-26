"""Local application logs (rotating file). Message contents are never logged."""

from __future__ import annotations

import logging
import logging.handlers
import sys

from . import paths


def setup_logging(verbose: bool = False) -> str:
    paths.ensure_dirs()
    log_file = paths.logs_dir() / "emergence-lab.log"
    root = logging.getLogger()
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    fh = logging.handlers.RotatingFileHandler(log_file, maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    fh.setFormatter(fmt)
    root.addHandler(fh)
    if sys.stderr is not None:
        sh = logging.StreamHandler(sys.stderr)
        sh.setFormatter(fmt)
        sh.setLevel(logging.WARNING)
        root.addHandler(sh)
    logging.getLogger("asyncio").setLevel(logging.WARNING)
    return str(log_file)
