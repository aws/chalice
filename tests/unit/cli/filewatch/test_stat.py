import os
import time
import threading

from chalice.cli.filewatch import stat


class BlockingFakeOSUtils(object):
    """This version will **always** block in walk() until a value is
    provided by the test runner that is used **until the next** walk()
    is called. Thus this will cause a barrier synchronization and
    serialization wrt StatFileWatcher.

    If the files_mtimes value is integer, it is returned, otherwise it
    is assumed to be an exception and is raised.

    """
    def __init__(self):
        self.calls = []
        self.data = None
        self.update_event = threading.Event()
        self.walk_event = threading.Event()

    def wait(self):
        self.walk_event.wait()

    def update(self, file_mtimes):
        self.walk_event.wait()
        self.walk_event.clear()
        self.data = file_mtimes
        self.calls = []
        self.update_event.set()

    def walk(self, rootdir):
        self.walk_event.set()
        self.update_event.wait()
        self.update_event.clear()

        self.calls.append(('walk', rootdir))

        yield 'rootdir', [], list(self.data.keys())

    def joinpath(self, *parts):
        return os.path.join(*parts)

    def mtime(self, path):
        name = os.path.basename(path)
        self.calls.append(('mtime', name))
        value = self.data[name]
        if isinstance(value, int):
            return value
        raise value


# Note: Test runner tests for no callback case automatically by
# redoing the fileset, and checking that number of change cbs is zero,
# so no need to add them here explicitly.
detect_changes_cases = [
    # no files, should result only in walk call
    ({}, 1, 0),
    # new file, should result in two os calls (walk + mtime) and
    # change callback
    ({'file': 1}, 2, 1),
    # funny file, but no changes otherwise, os.calls only, no change cb
    ({'file': 1, 'ifle': OSError('No such file')}, 3, 0),
    # funny file turns real,
    ({'file': 1, 'ifle': 2}, 3, 1),
    # real update on multiple files, only one change cb
    ({'file': 4, 'ifle': 4}, 3, 1),
    # new bad file, no changes to others
    ({'file': 4, 'ifle': 4, 'flie': OSError('Bad file system')}, 4, 0),
    # even with bad file, but real change, should react
    ({'file': 4, 'ifle': 5, 'flie': OSError('Bad file system')}, 4, 1),
    # bad file disappearing
    ({'file': 4, 'ifle': 5}, 3, 0),
    # good file turning bad
    ({'file': 4, 'ifle': OSError('Zoomotron failed')}, 3, 1),
    # only one left and going fast
    ({'file': 4}, 2, 0),
    ({}, 1, 1)
]

def test_detects_changes():
    calls = []
    def callback(*args, **kwargs):
        calls.append((args, kwargs))

    os = BlockingFakeOSUtils()
    watcher = stat.StatFileWatcher(os)
    watcher.POLL_INTERVAL = 0  # doesn't matter, it is barrier synchronized
    watcher.watch_for_file_changes('rootdir', callback)

    os.wait()
    assert len(os.calls) == 0
    assert len(calls) == 0

    for file_mtimes, os_calls, cb_calls in detect_changes_cases:
        print("test case:", "file_mtimes", file_mtimes,
              "os_calls", os_calls, "cb_calls", cb_calls)
        del calls[:]
        os.update(file_mtimes)
        os.wait()
        assert len(os.calls) == os_calls
        assert len(calls) == cb_calls

        # redoing the same immediately should not result in same os
        # calls, but no callback!
        del calls[:]
        os.update(file_mtimes)
        os.wait()
        assert len(os.calls) == os_calls
        assert len(calls) == 0
