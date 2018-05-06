import subprocess
import tempfile
import sys

code = b"""
from chalice.cli.reload import Reloader

with Reloader() as r:
    r.join()
"""

modified_code = b'print("reloaded")'


def test_reload():
    with tempfile.NamedTemporaryFile(buffering=0) as program_file:
        program_file.write(code)
        args = [sys.executable, program_file.name]
        with subprocess.Popen(args, stdout=subprocess.PIPE) as program:
            program_file.seek(0)
            program_file.truncate()
            program_file.write(modified_code)
            assert b'reloaded' in program.stdout.read()
