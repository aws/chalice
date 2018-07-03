import os

from chalice.cli.filewatch import stat


class FakeOSUtils(object):
    def __init__(self):
        self.initial_scan = True

    def walk(self, rootdir):
        yield 'rootdir', [], ['bad-file', 'baz']
        if self.initial_scan:
            self.initial_scan = False

    def joinpath(self, *parts):
        return os.path.join(*parts)

    def mtime(self, path):
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
    assert len(calls) == 1
