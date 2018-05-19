"""Automatically reload chalice app when files change.

How It Works
============

This approach borrow from what django, flask, and other frameworks do.
Essentially, with reloading enabled ``chalice local`` will start up
a worker process that runs the dev http server.  This means there will
be a total of two processes running (both will show as ``chalice local``
in ps).  One process is the parent process.  It's job is to start up a child
process and restart it if it exits (due to a restart request).  The child
process is the process that actually starts up the web server for local mode.
The child process also sets up a watcher thread.  It's job is to monitor
directories for changes.  If a change is encountered it sys.exit()s the process
with a known RC (the RESTART_REQUEST_RC constant in the module).

The parent process runs in an infinite loop.  If the child process exits with
an RC of RESTART_REQUEST_RC the parent process starts up another child process.

The child worker is denoted by setting the ``CHALICE_WORKER`` env var.
If this env var is set, the process is intended to be a worker process (as
opposed the parent process which just watches for restart requests from the
worker process).

"""
import subprocess
import threading
import logging
import copy
import sys

import watchdog.observers
from watchdog.events import FileSystemEventHandler
from watchdog.events import FileSystemEvent  # noqa
from typing import MutableMapping, Type, Callable, Optional  # noqa

from chalice.local import LocalDevServer  # noqa


RESTART_REQUEST_RC = 3
LOGGER = logging.getLogger(__name__)


def start_parent_process(env):
    # type: (MutableMapping) -> None
    process = ParentProcess(env, subprocess.Popen)
    process.main()


class Restarter(FileSystemEventHandler):

    def __init__(self, restart_event):
        # type: (threading.Event) -> None
        # The reason we're using threading
        self.restart_event = restart_event

    def on_any_event(self, event):
        # type: (FileSystemEvent) -> None
        # If we modify a file we'll get a FileModifiedEvent
        # as well as a DirectoryModifiedEvent.
        # We only care about reloading is a file is modified.
        if event.is_directory:
            return
        self.restart_event.set()


def start_worker_process(server_factory, root_dir):
    # type: (Callable[[], LocalDevServer], str) -> int
    t = HTTPServerThread(server_factory)
    worker = WorkerProcess(t)
    LOGGER.debug("Starting worker...")
    rc = worker.main(root_dir)
    LOGGER.info("Restarting local dev server.")
    return rc


class HTTPServerThread(threading.Thread):
    """Thread that manages starting/stopping local HTTP server.

    This is a small wrapper around a normal threading.Thread except
    that it adds shutdown capability of the HTTP server, which is
    not part of the normal threading.Thread interface.

    """
    def __init__(self, server_factory):
        # type: (Callable[[], LocalDevServer]) -> None
        threading.Thread.__init__(self)
        self._server_factory = server_factory
        self._server = None  # type: Optional[LocalDevServer]
        self.daemon = True

    def run(self):
        # type: () -> None
        self._server = self._server_factory()
        self._server.serve_forever()

    def shutdown(self):
        # type: () -> None
        if self._server is not None:
            self._server.shutdown()


class ParentProcess(object):
    """Spawns a child process and restarts it as needed."""
    def __init__(self, env, popen):
        # type: (MutableMapping, Type[subprocess.Popen]) -> None
        self._env = copy.copy(env)
        self._popen = popen

    def main(self):
        # type: () -> None
        # This method launches a child worker and restarts it if it
        # exits with RESTART_REQUEST_RC.  This method doesn't return.
        # A user can Ctrl-C to stop the parent process.
        while True:
            self._env['CHALICE_WORKER'] = 'true'
            LOGGER.debug("Parent process starting child worker process...")
            process = self._popen(sys.argv, env=self._env)
            try:
                process.communicate()
                if process.returncode != RESTART_REQUEST_RC:
                    return
            except KeyboardInterrupt:
                process.terminate()
                raise


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
        observer = watchdog.observers.Observer()
        restarter = Restarter(self._restart_event)
        observer.schedule(restarter, project_dir, recursive=True)
        observer.start()


def run_with_reloader(server_factory, env, root_dir):
    # type: (Callable, MutableMapping, str) -> int
    # This function is invoked in two possible modes, as the parent process
    # or as a chalice worker.
    try:
        if env.get('CHALICE_WORKER') is not None:
            # This is a chalice worker.  We need to start the main dev server
            # in a daemon thread and install a file watcher.
            return start_worker_process(server_factory, root_dir)
        else:
            # This is the parent process.  It's just is to spawn an identical
            # process but with the ``CHALICE_WORKER`` env var set.  It then
            # will monitor this process and restart it if it exits with a
            # RESTART_REQUEST exit code.
            start_parent_process(env)
    except KeyboardInterrupt:
        pass
    return 0
