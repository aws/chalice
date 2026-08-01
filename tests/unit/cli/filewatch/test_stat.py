import os
import time

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
    for _ in range(10):
        if len(calls) == 1:
            break
        time.sleep(0.2)
    else:
        raise AssertionError("Expected callback to be invoked but was not.")


class FakeOSUtilsWithBrokenSymlink(object):
    """Simulates a broken symlink that fails os.stat during initial cache seed.

    This can happen with symlinks pointing to non-existent files, such as
    Emacs lock files (.#app.py) or other temporary symlinks.
    """
    def __init__(self):
        self.scan_count = 0

    def walk(self, rootdir):
        self.scan_count += 1
        yield 'rootdir', [], ['broken-symlink', 'good-file']

    def joinpath(self, *parts):
        return os.path.join(*parts)

    def mtime(self, path):
        if path.endswith('broken-symlink'):
            raise FileNotFoundError("No such file or directory")
        return 1


def test_can_handle_broken_symlink_during_initial_scan():
    """Test that broken symlinks during initial cache seeding are handled.

    This is a regression test for issue #997 where symlinks to non-existent
    files (like Emacs .#app.py files) would crash the file watcher during
    the initial _seed_mtime_cache call.
    """
    osutils = FakeOSUtilsWithBrokenSymlink()
    watcher = stat.StatFileWatcher(osutils)
    # This should not raise an exception
    watcher._seed_mtime_cache('rootdir')
    # The good file should be in the cache, the broken symlink should not
    assert len(watcher._mtime_cache) == 1
    assert 'rootdir/good-file' in watcher._mtime_cache or \
           os.path.join('rootdir', 'good-file') in watcher._mtime_cache
