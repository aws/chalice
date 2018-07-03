import pytest
import mock
import threading
import os
import unittest
import time

from chalice.cli.filewatch.stat import StatWorkerProcess
try:
    from chalice.cli.filewatch.eventbased import WatchdogWorkerProcess
    WATCHDOG_AVAILABLE = True
except ImportError:
    WATCHDOG_AVAILABLE = False

import chalice.local


DEFAULT_DELAY = 0.1
SETTLE_DELAY = 1
MAX_TIMEOUT = 5.0
use_all_watcher_types = pytest.mark.parametrize(
    ['worker_class_type'], [('watchdog',), ('stat',)])


def modify_file_after_n_seconds(filename, contents, delay=DEFAULT_DELAY):
    t = threading.Timer(delay, function=modify_file, args=(filename, contents))
    t.daemon = True
    t.start()


def delete_file_after_n_seconds(filename, delay=DEFAULT_DELAY):
    t = threading.Timer(delay, function=os.remove, args=(filename,))
    t.daemon = True
    t.start()


def modify_file(filename, contents):
    if filename is None:
        return
    with open(filename, 'w') as f:
        f.write(contents)


def assert_reload_happens(root_dir, when_modified_file, using_worker_class):
    http_thread = mock.Mock(spec=chalice.local.HTTPServerThread)
    worker_cls = get_worker_cls(using_worker_class)
    p = worker_cls(http_thread)
    if isinstance(when_modified_file, tuple):
        if when_modified_file[1] == 'is_deleted':
            delete_file_after_n_seconds(when_modified_file[0])
    else:
        modify_file_after_n_seconds(when_modified_file, 'contents')
    rc = p.main(root_dir, MAX_TIMEOUT)
    assert rc == chalice.cli.filewatch.RESTART_REQUEST_RC


def get_worker_cls(worker_class_name):
    if worker_class_name == 'watchdog':
        if not WATCHDOG_AVAILABLE:
            raise unittest.SkipTest("Test requires watchdog package.")
        else:
            return WatchdogWorkerProcess
    elif worker_class_name == 'stat':
        return StatWorkerProcess
    else:
        raise RuntimeError("Unknown worker class type name: %s"
                           % worker_class_name)


@use_all_watcher_types
def test_can_reload_when_file_created(tmpdir, worker_class_type):
    top_level_file = str(tmpdir.join('foo'))
    assert_reload_happens(str(tmpdir), when_modified_file=top_level_file,
                          using_worker_class=worker_class_type)


@use_all_watcher_types
def test_can_reload_when_subdir_file_created(tmpdir, worker_class_type):
    subdir_file = str(tmpdir.join('subdir').mkdir().join('foo.txt'))
    assert_reload_happens(str(tmpdir), when_modified_file=subdir_file,
                          using_worker_class=worker_class_type)


@use_all_watcher_types
def test_can_reload_when_file_modified(tmpdir, worker_class_type):
    top_level_file = tmpdir.join('foo')
    top_level_file.write('original contents')
    # If you write to the file and immediately start the reloader, it
    # won't see the initial write() above.  I tried out a few delay options,
    # and a separate SETTLE_DELAY was necessary in order to prevent
    # intermittent failures.
    time.sleep(SETTLE_DELAY)
    assert_reload_happens(str(tmpdir), when_modified_file=str(top_level_file),
                          using_worker_class=worker_class_type)


@use_all_watcher_types
def test_can_reload_when_file_removed(tmpdir, worker_class_type):
    top_level_file = tmpdir.join('foo')
    top_level_file.write('original contents')
    assert_reload_happens(
        str(tmpdir), when_modified_file=(str(top_level_file), 'is_deleted'),
        using_worker_class=worker_class_type
    )


@use_all_watcher_types
def test_rc_0_when_no_file_modified(tmpdir, worker_class_type):
    http_thread = mock.Mock(spec=chalice.local.HTTPServerThread)
    worker_cls = get_worker_cls(worker_class_type)
    p = worker_cls(http_thread)
    rc = p.main(str(tmpdir), timeout=0.2)
    assert rc == 0
