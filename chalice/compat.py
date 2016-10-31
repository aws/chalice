import os
import platform


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
