import os
import sys
import threading
import time
import types

from typing import Optional, Dict, Type  # noqa

from chalice.compat import reload


class Reloader(threading.Thread):
    def __init__(self, autoreload_interval):
        # type: (int) -> None
        super(Reloader, self).__init__()
        self.autoreload_interval = autoreload_interval
        self.triggered = False
        self.mtimes = {}  # type: Dict[str, float]

    def __enter__(self):
        # type: () -> Reloader
        self.setDaemon(True)
        self.start()
        return self

    def __exit__(self,
                 exc_type,  # type: Optional[Type[BaseException]]
                 exc_value,  # type: Optional[BaseException]
                 traceback  # type: Optional[types.TracebackType]
                 ):
        # type: (...) -> None
        if exc_type is KeyboardInterrupt and self.triggered:
            sys.exit(1)

    def run(self):
        # type: () -> None
        while True:
            time.sleep(self.autoreload_interval)
            if self.find_changes():
                self.reload()

    def find_changes(self):
        # type: () -> bool
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
        return False

    def reload(self):
        # type: () -> None
        self.triggered = True
        reload()
