import mock
import threading

from chalice.cli import reloader


DEFAULT_DELAY = 0.1
MAX_TIMEOUT = 5.0


def modify_file_after_n_seconds(filename, contents, delay=DEFAULT_DELAY):
    t = threading.Timer(delay, function=modify_file, args=(filename, contents))
    t.daemon = True
    t.start()


def modify_file(filename, contents):
    if filename is None:
        return
    with open(filename, 'w') as f:
        f.write(contents)


def assert_reload_happens(root_dir, when_modified_file):
    http_thread = mock.Mock(spec=reloader.HTTPServerThread)
    p = reloader.WorkerProcess(http_thread)
    modify_file_after_n_seconds(when_modified_file, 'contents')
    rc = p.main(root_dir, MAX_TIMEOUT)
    assert rc == reloader.RESTART_REQUEST_RC


def test_can_reload_when_file_created(tmpdir):
    top_level_file = str(tmpdir.join('foo'))
    assert_reload_happens(str(tmpdir), when_modified_file=top_level_file)


def test_can_reload_when_subdir_file_created(tmpdir):
    subdir_file = str(tmpdir.join('subdir').mkdir().join('foo.txt'))
    assert_reload_happens(str(tmpdir), when_modified_file=subdir_file)


def test_rc_0_when_no_file_modified(tmpdir):
    http_thread = mock.Mock(spec=reloader.HTTPServerThread)
    p = reloader.WorkerProcess(http_thread)
    rc = p.main(str(tmpdir), timeout=0.2)
    assert rc == 0
