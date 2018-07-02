import logging
from typing import Callable  # noqa

from chalice.cli.filewatch import FileWatcher, WorkerProcess


LOGGER = logging.getLogger(__name__)


class StatWorkerProcess(WorkerProcess):
    def _start_file_watcher(self, project_dir):
        # type: (str) -> None
        LOGGER.debug("Fake watching: %s", project_dir)


class StatFileWatcher(FileWatcher):
    def watch_for_file_changes(self, root_dir, callback):
        # type: (str, Callable[[], None]) -> None
        LOGGER.debug("Stat file watching: %s, with callback: %s",
                     root_dir, callback)
