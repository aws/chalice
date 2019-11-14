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
import logging
import copy

from typing import MutableMapping, Type, Callable, Optional, List  # noqa

from chalice.cli.filewatch import RESTART_REQUEST_RC, WorkerProcess
from chalice.local import LocalDevServer, HTTPServerThread  # noqa


LOGGER = logging.getLogger(__name__)
WorkerProcType = Optional[Type[WorkerProcess]]


def get_best_worker_process():
    # type: () -> Type[WorkerProcess]
    try:
        from chalice.cli.filewatch.eventbased import WatchdogWorkerProcess
        LOGGER.debug("Using watchdog worker process.")
        return WatchdogWorkerProcess
    except ImportError:
        from chalice.cli.filewatch.stat import StatWorkerProcess
        LOGGER.debug("Using stat() based worker process.")
        return StatWorkerProcess


def start_parent_process(args, env):
    # type: (List[str], MutableMapping) -> None
    process = ParentProcess(args, env, subprocess.Popen)
    process.main()


def start_worker_process(server_factory, root_dir, worker_process_cls=None):
    # type: (Callable[[], LocalDevServer], str, WorkerProcType) -> int
    if worker_process_cls is None:
        worker_process_cls = get_best_worker_process()
    t = HTTPServerThread(server_factory)
    worker = worker_process_cls(t)
    LOGGER.debug("Starting worker...")
    rc = worker.main(root_dir)
    LOGGER.info("Restarting local dev server.")
    return rc


class ParentProcess(object):
    """Spawns a child process and restarts it as needed."""
    def __init__(self, args, env, popen):
        # type: (List[str], MutableMapping, Type[subprocess.Popen]) -> None
        self._args = self._filter_args(args)
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
            process = self._popen(self._args, env=self._env)
            try:
                process.communicate()
                if process.returncode != RESTART_REQUEST_RC:
                    return
            except KeyboardInterrupt:
                process.terminate()
                raise

    def _filter_args(self, args):
        # type: (List[str]) -> List[str]
        """Remove --project-dir and positional argument from args list.

        Since os.chdir has already been called on the project_dir, and the
        child process will inherit our current working directory, we must
        remove the --project-dir argument. If not removed, and it was a
        relative path it will be appended again to the working directory
        resulting in a stutter at the end of working directory in the worker
        process.

        Absolute paths are not affected since they will not be appended to the
        current working directory.
        """
        try:
            marker = args.index('--project-dir')
            new_args = args[:marker] + args[marker + 2:]
        except ValueError:
            new_args = args
        return new_args


def run_with_reloader(server_factory, args, env, root_dir,
                      worker_process_cls=None):
    # type: (Callable, List[str], MutableMapping, str, WorkerProcType) -> int
    # This function is invoked in two possible modes, as the parent process
    # or as a chalice worker.
    try:
        if env.get('CHALICE_WORKER') is not None:
            # This is a chalice worker.  We need to start the main dev server
            # in a daemon thread and install a file watcher.
            return start_worker_process(server_factory, root_dir,
                                        worker_process_cls)
        else:
            # This is the parent process.  It's just is to spawn an identical
            # process but with the ``CHALICE_WORKER`` env var set.  It then
            # will monitor this process and restart it if it exits with a
            # RESTART_REQUEST exit code.
            start_parent_process(args, env)
    except KeyboardInterrupt:
        pass
    return 0
