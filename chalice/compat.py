import os
import platform
import socket
import six

from six import StringIO


if six.PY3:
    from urllib.parse import urlparse, parse_qs

    def is_broken_pipe_error(error):
        # type: (Exception) -> bool
        return isinstance(error, BrokenPipeError)  # noqa
else:
    from urlparse import urlparse, parse_qs

    def is_broken_pipe_error(error):
        # type: (Exception) -> bool

        # In python3, this is a BrokenPipeError. However in python2, this
        # is a socket.error that has the message 'Broken pipe' in it. So we
        # don't want to be assuming all socket.error are broken pipes so just
        # check if the message has 'Broken pipe' in it.
        return isinstance(error, socket.error) and 'Broken pipe' in str(error)


if platform.system() == 'Windows':
    def pip_script_in_venv(venv_dir):
        # type: (str) -> str
        pip_exe = os.path.join(venv_dir, 'Scripts', 'pip.exe')
        return pip_exe

    def site_packages_dir_in_venv(venv_dir):
        # type: (str) -> str
        deps_dir = os.path.join(venv_dir, 'Lib', 'site-packages')
        return deps_dir

else:
    # Posix platforms.

    def pip_script_in_venv(venv_dir):
        # type: (str) -> str
        pip_exe = os.path.join(venv_dir, 'bin', 'pip')
        return pip_exe

    def site_packages_dir_in_venv(venv_dir):
        # type: (str) -> str
        python_dir = os.listdir(os.path.join(venv_dir, 'lib'))[0]
        deps_dir = os.path.join(venv_dir, 'lib', python_dir, 'site-packages')
        return deps_dir
