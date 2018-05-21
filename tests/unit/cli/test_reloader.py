import threading
from subprocess import Popen

import mock
import pytest
from watchdog.events import FileSystemEvent, DirModifiedEvent

from chalice.cli import reloader
from chalice.local import LocalDevServer


# NOTE: Most of the reloader module relies on threads, subprocesses,
# and process exiting with specific return codes.  This is quite difficult
# to unit test, so the more realistic tests are over in function/test_local.py.
class RecordingPopen(object):
    def __init__(self, process, return_codes=None):
        self.process = process
        self.recorded_args = []
        if return_codes is None:
            return_codes = []
        self.return_codes = return_codes

    def __call__(self, *args, **kwargs):
        self.recorded_args.append((args, kwargs))
        if self.return_codes:
            rc = self.return_codes.pop(0)
            self.process.returncode = rc
        return self.process


def test_restarter_triggers_event():
    restart_event = threading.Event()
    restarter = reloader.Restarter(restart_event)
    app_modified = FileSystemEvent(src_path='./app.py')
    restarter.on_any_event(app_modified)
    assert restart_event.is_set()


def test_directory_events_ignored():
    restart_event = threading.Event()
    restarter = reloader.Restarter(restart_event)
    app_modified = DirModifiedEvent(src_path='./')
    restarter.on_any_event(app_modified)
    assert not restart_event.is_set()


def test_http_server_thread_starts_server_and_shutsdown():
    server = mock.Mock(spec=LocalDevServer)
    thread = reloader.HTTPServerThread(lambda: server)
    thread.run()
    thread.shutdown()
    server.serve_forever.assert_called_with()
    server.shutdown.assert_called_with()


def test_shutdown_noop_if_server_not_started():
    server = mock.Mock(spec=LocalDevServer)
    thread = reloader.HTTPServerThread(lambda: server)
    thread.shutdown()
    assert not server.shutdown.called


def test_parent_process_starts_child_with_worker_env_var():
    process = mock.Mock(spec=Popen)
    process.returncode = 0
    popen = RecordingPopen(process)
    env = {'original-env': 'foo'}
    parent = reloader.ParentProcess(env, popen)

    parent.main()

    assert len(popen.recorded_args) == 1
    kwargs = popen.recorded_args[-1][1]
    assert kwargs == {'env': {'original-env': 'foo',
                              'CHALICE_WORKER': 'true'}}


def test_assert_child_restarted_until_not_restart_rc():
    process = mock.Mock(spec=Popen)
    popen = RecordingPopen(
        process, return_codes=[reloader.RESTART_REQUEST_RC, 0])
    parent = reloader.ParentProcess({}, popen)

    parent.main()

    # The child process should have been invoked twice, the first one
    # was with RESTART_REQUEST_RC so that should trigger a restart,
    # then second one was rc 0 the process should just exit.
    assert len(popen.recorded_args) == 2


def test_ctrl_c_kill_child_process():
    process = mock.Mock(spec=Popen)
    process.communicate.side_effect = KeyboardInterrupt
    popen = RecordingPopen(process)
    parent = reloader.ParentProcess({}, popen)

    with pytest.raises(KeyboardInterrupt):
        parent.main()

    assert process.terminate.called
