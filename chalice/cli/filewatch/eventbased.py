import threading  # noqa

from typing import Callable, Optional  # noqa
import watchdog.observers  # pylint: disable=import-error
from watchdog import events  # pylint: disable=import-error

from chalice.cli.filewatch import FileWatcher, WorkerProcess


class WatchdogWorkerProcess(WorkerProcess):
    """Worker that runs the chalice dev server."""

    def _start_file_watcher(self, project_dir):
        # type: (str) -> None
        restart_callback = WatchdogRestarter(self._restart_event)
        watcher = WatchdogFileWatcher()
        watcher.watch_for_file_changes(
            project_dir, restart_callback)


class WatchdogFileWatcher(FileWatcher):
    def watch_for_file_changes(self, root_dir, callback):
        # type: (str, Callable[[], None]) -> None
        observer = watchdog.observers.Observer()
        observer.schedule(callback, root_dir, recursive=True)
        observer.start()


class WatchdogRestarter(events.FileSystemEventHandler):

    def __init__(self, restart_event):
        # type: (threading.Event) -> None
        # The reason we're using threading
        self.restart_event = restart_event

    def on_any_event(self, event):
        # type: (events.FileSystemEvent) -> None
        # If we modify a file we'll get a FileModifiedEvent
        # as well as a DirectoryModifiedEvent.
        # We only care about reloading is a file is modified.
        if event.is_directory:
            return
        self()

    def __call__(self):
        # type: () -> None
        self.restart_event.set()
