import os
import subprocess
import sys
import threading
import time
import types

import six

from chalice.constants import AUTORELOAD_INTERVAL


class Reloader(threading.Thread):
    def __init__(self, autoreload=True):
        super(Reloader, self).__init__()
        self.autoreload = autoreload
        self.triggered = False
        self.mtimes = {}

    def __enter__(self):
        if self.autoreload:
            self.setDaemon(True)
            self.start()

    def __exit__(self, exc_type, exc_value, traceback):
        if exc_type is KeyboardInterrupt and self.triggered:
            sys.exit(1)

    def run(self):
        while True:
            time.sleep(AUTORELOAD_INTERVAL)
            if self.find_changes():
                self.reload()

    def find_changes(self):
        for module in list(sys.modules.values()):
            if not isinstance(module, types.ModuleType):
                continue
            path = getattr(module, '__file__', None)
            if not path:
                continue
            if path.endswith('.pyc') or path.endswith('.pyo'):
                path = path[:-1]
            try:
                mtime = os.path.getmtime(path)
            except OSError:
                continue
            old_time = self.mtimes.setdefault(path, mtime)
            if mtime > old_time:
                return True

    def reload(self):
        self.triggered = True
        if sys.platform == 'win32':
            subprocess.Popen(sys.argv, close_fds=True)
            six.moves._thread.interrupt_main()
        else:
            os.execv(sys.executable, [sys.executable] + sys.argv)
