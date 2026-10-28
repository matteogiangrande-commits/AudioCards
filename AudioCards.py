"""PyInstaller entry point. End users run the packaged AudioCards.exe, not this script."""
import multiprocessing
import os
from pathlib import Path
import traceback


def _report_startup_failure(error):
    """Write opt-in local diagnostic; never send user data or contact a server."""
    path = os.environ.get("AUDIOCARDS_BOOTSTRAP_LOG")
    if not path:
        return
    try:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            "".join(traceback.format_exception(type(error), error, error.__traceback__)),
            encoding="utf-8",
        )
    except OSError:
        pass


if __name__ == "__main__":
    multiprocessing.freeze_support()
    try:
        from audiocards.__main__ import main
        raise SystemExit(main())
    except Exception as exc:
        _report_startup_failure(exc)
        raise
