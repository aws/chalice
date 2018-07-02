import logging
import threading
import time

from typing import Callable, Dict, Optional  # noqa

from chalice.cli.filewatch import FileWatcher, WorkerProcess
from chalice.utils import OSUtils


LOGGER = logging.getLogger(__name__)


class StatWorkerProcess(WorkerProcess):
    def _start_file_watcher(self, project_dir):
        # type: (str) -> None
        watcher = StatFileWatcher()
        watcher.watch_for_file_changes(project_dir, self._on_file_change)

    def _on_file_change(self):
        # type: () -> None
        self._restart_event.set()


class StatFileWatcher(FileWatcher):
    POLL_INTERVAL = 1

    def __init__(self):
        # type: () -> None
        self._mtime_cache = {}  # type: Dict[str, int]
        self._shutdown_event = threading.Event()
        self._thread = None  # type: Optional[threading.Thread]
        self._osutils = OSUtils()

    def watch_for_file_changes(self, root_dir, callback):
        # type: (str, Callable[[], None]) -> None
        t = threading.Thread(target=self.poll_for_changes_until_shutdown,
                             args=(root_dir, callback))
        t.daemon = True
        t.start()
        self._thread = t
        LOGGER.debug("Stat file watching: %s, with callback: %s",
                     root_dir, callback)

    def shutdown(self):
        # type: () -> None
        self._shutdown_event.set()
        if self._thread is not None:
            self._thread.join()

    def poll_for_changes_until_shutdown(self, root_dir, callback):
        # type: (str, Callable[[], None]) -> None
        self._seed_mtime_cache(root_dir)
        while not self._shutdown_event.isSet():
            self._single_pass_poll(root_dir, callback)
            time.sleep(self.POLL_INTERVAL)

    def _seed_mtime_cache(self, root_dir):
        # type: (str) -> None
        for rootdir, _, filenames in self._osutils.walk(root_dir):
            for filename in filenames:
                path = self._osutils.joinpath(rootdir, filename)
                self._mtime_cache[path] = self._osutils.mtime(path)

    def _single_pass_poll(self, root_dir, callback):
        # type: (str, Callable[[], None]) -> None
        mtime_cache = self._mtime_cache
        new_mtimes = {}
        for rootdir, _, filenames in self._osutils.walk(root_dir):
            for filename in filenames:
                path = self._osutils.joinpath(rootdir, filename)
                last_mtime = mtime_cache.get(path)
                if last_mtime is None:
                    # New file added, we don't need to look any further.
                    mtime_cache[path] = self._osutils.mtime(path)
                    LOGGER.debug("File added: %s, triggering restart.",
                                 path)
                    callback()
                    return
                try:
                    new_mtime = self._osutils.mtime(path)
                    if new_mtime > last_mtime:
                        # File has been updated.
                        mtime_cache[path] = new_mtime
                        LOGGER.debug("File updated: %s, triggering restart.",
                                     path)
                        callback()
                        return
                    new_mtimes[path] = new_mtime
                except OSError:
                    pass
        if new_mtimes != mtime_cache:
            # Files were removed.
            LOGGER.debug("Files removed, triggering restart.")
            self._mtime_cache = new_mtimes
            callback()
            return
