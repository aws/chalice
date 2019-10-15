import os
import subprocess

import pytest
from chalice.utils import OSUtils

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.join(
    os.path.dirname(CURRENT_DIR),
    'aws',
    'testapp',
)


@pytest.fixture
def local_app(tmpdir):
    temp_dir_path = str(tmpdir)
    OSUtils().copytree(PROJECT_DIR, temp_dir_path)
    old_dir = os.getcwd()
    try:
        os.chdir(temp_dir_path)
        yield temp_dir_path
    finally:
        os.chdir(old_dir)


def test_stack_trace_printed_on_error(local_app):
    app_file = os.path.join(local_app, 'app.py')
    with open(app_file, 'w') as f:
        f.write(
            'from chalice import Chalice\n'
            'app = Chalice(app_name="test")\n'
            'foobarbaz\n'
        )
    p = subprocess.Popen(['chalice', 'local', '--no-autoreload'],
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    stderr = p.communicate()[1].decode('ascii')
    rc = p.returncode

    assert rc == 2
    assert 'Traceback' in stderr
    assert 'foobarbaz' in stderr
