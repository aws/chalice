import os
import time

from chalice.cli.filewatch import stat


class FakeOSUtils(object):
    def __init__(self):
        self.initial_scan = True

    def walk(self, rootdir):
        yield 'rootdir', [], ['bad-file', 'no-file', 'baz']
        if self.initial_scan:
            self.initial_scan = False

    def joinpath(self, *parts):
        return os.path.join(*parts)

    def mtime(self, path):
        if path.endswith('no-file'):
            raise FileNotFoundError()
        if self.initial_scan:
            return 1
        if path.endswith('bad-file'):
            raise OSError("Bad file")
        return 2


def test_can_ignore_stat_errors():
    calls = []

    def callback(*args, **kwargs):
        calls.append((args, kwargs))

    watcher = stat.StatFileWatcher(FakeOSUtils())
    watcher.watch_for_file_changes('rootdir', callback)
    for _ in range(10):
        if len(calls) == 1:
            break
        time.sleep(0.2)
    else:
        raise AssertionError("Expected callback to be invoked but was not.")
