import threading

from typing import Callable, Optional, Type  # noqa
from chalice.local import HTTPServerThread  # noqa


RESTART_REQUEST_RC = 3


class FileWatcher(object):
    """Base class for watching files for changes."""

    def watch_for_file_changes(self, root_dir, callback):
        # type: (str, Callable[[], None]) -> None
        """Recursively watch directory for changes.

        When a changed file is detected, the provided callback
        is immediately invoked and the current scan stops.

        """
        raise NotImplementedError("watch_for_file_changes")


class WorkerProcess(object):
    """Worker that runs the chalice dev server."""
    def __init__(self, http_thread):
        # type: (HTTPServerThread) -> None
        self._http_thread = http_thread
        self._restart_event = threading.Event()

    def main(self, project_dir, timeout=None):
        # type: (str, Optional[int]) -> int
        self._http_thread.start()
        self._start_file_watcher(project_dir)
        if self._restart_event.wait(timeout):
            self._http_thread.shutdown()
            return RESTART_REQUEST_RC
        return 0

    def _start_file_watcher(self, project_dir):
        # type: (str) -> None
        raise NotImplementedError("_start_file_watcher")
