import subprocess
import tempfile
import time
import sys

code = b"""
from chalice.cli.reload import Reloader

with Reloader(0) as r:
    r.join()
"""

modified_code = b'print("reloaded")'


def test_reload():
    with tempfile.NamedTemporaryFile() as program_file:
        program_file.write(code)
        program_file.flush()
        args = [sys.executable, program_file.name]
        program = subprocess.Popen(args, stdout=subprocess.PIPE)
        time.sleep(1)
        program_file.seek(0)
        program_file.truncate()
        program_file.write(modified_code)
        program_file.flush()
        assert b'reloaded' in program.stdout.read()
