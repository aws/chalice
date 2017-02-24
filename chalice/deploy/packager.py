import hashlib
import inspect
import os
import shutil
import subprocess
import sys
import zipfile

import virtualenv

import chalice
from chalice import compat, app


class LambdaDeploymentPackager(object):
    _CHALICE_LIB_DIR = 'chalicelib'
    _VENDOR_DIR = 'vendor'

    def _create_virtualenv(self, venv_dir):
        # type: (str) -> None
        # The original implementation used Popen(['virtualenv', ...])
        # However, it's hard to make assumptions about how a users
        # PATH is set up.  This could result in using old versions
        # of virtualenv that give confusing error messages.
        # To fix this issue, we're calling directly into the
        # virtualenv package.  The main() method doesn't accept
        # args, so we need to patch out sys.argv with the venv
        # dir.  The original sys.argv is replaced on exit.
        original = sys.argv
        sys.argv = ['', venv_dir, '--quiet']
        try:
            virtualenv.main()
        finally:
            sys.argv = original

    def create_deployment_package(self, project_dir):
        # type: (str) -> str
        print "Creating deployment package."
        # pip install -t doesn't work out of the box with homebrew and
        # python, so we're using virtualenvs instead which works in
        # more cases.
        venv_dir = os.path.join(project_dir, '.chalice', 'venv')
        self._create_virtualenv(venv_dir)
        pip_exe = compat.pip_script_in_venv(venv_dir)
        assert os.path.isfile(pip_exe)
        # Next install any requirements specified by the app.
        requirements_file = os.path.join(project_dir, 'requirements.txt')
        deployment_package_filename = self.deployment_package_filename(
            project_dir)
        if self._has_at_least_one_package(requirements_file) and not \
                os.path.isfile(deployment_package_filename):
            p = subprocess.Popen([pip_exe, 'install', '-r', requirements_file],
                                 stdout=subprocess.PIPE)
            p.communicate()
        deps_dir = compat.site_packages_dir_in_venv(venv_dir)
        assert os.path.isdir(deps_dir)
        # Now we need to create a zip file and add in the site-packages
        # dir first, followed by the app_dir contents next.
        if not os.path.isdir(os.path.dirname(deployment_package_filename)):
            os.makedirs(os.path.dirname(deployment_package_filename))
        with zipfile.ZipFile(deployment_package_filename, 'w',
                             compression=zipfile.ZIP_DEFLATED) as z:
            self._add_py_deps(z, deps_dir)
            self._add_app_files(z, project_dir)
            self._add_vendor_files(z, os.path.join(project_dir,
                                                   self._VENDOR_DIR))
        return deployment_package_filename

    def _add_vendor_files(self, zipped, dirname):
        # type: (zipfile.ZipFile, str) -> None
        if not os.path.isdir(dirname):
            return
        prefix_len = len(dirname) + 1
        for root, _, filenames in os.walk(dirname):
            for filename in filenames:
                full_path = os.path.join(root, filename)
                zip_path = full_path[prefix_len:]
                zipped.write(full_path, zip_path)

    def _has_at_least_one_package(self, filename):
        # type: (str) -> bool
        if not os.path.isfile(filename):
            return False
        with open(filename, 'r') as f:
            # This is meant to be a best effort attempt.
            # This can return True and still have no packages
            # actually being specified, but those aren't common
            # cases.
            for line in f:
                line = line.strip()
                if line and not line.startswith('#'):
                    return True
        return False

    def deployment_package_filename(self, project_dir):
        # type: (str) -> str
        # Computes the name of the deployment package zipfile
        # based on a hash of the requirements file.
        # This is done so that we only "pip install -r requirements.txt"
        # when we know there's new dependencies we need to install.
        requirements_file = os.path.join(project_dir, 'requirements.txt')
        hash_contents = self._hash_project_dir(
            requirements_file, os.path.join(project_dir, self._VENDOR_DIR))
        deployment_package_filename = os.path.join(
            project_dir, '.chalice', 'deployments', hash_contents + '.zip')
        return deployment_package_filename

    def _add_py_deps(self, zip, deps_dir):
        # type: (zipfile.ZipFile, str) -> None
        prefix_len = len(deps_dir) + 1
        for root, dirnames, filenames in os.walk(deps_dir):
            if root == deps_dir and 'chalice' in dirnames:
                # Don't include any chalice deps.  We cherry pick
                # what we want to include in _add_app_files.
                dirnames.remove('chalice')
            for filename in filenames:
                full_path = os.path.join(root, filename)
                zip_path = full_path[prefix_len:]
                zip.write(full_path, zip_path)

    def _add_app_files(self, zip, project_dir):
        # type: (zipfile.ZipFile, str) -> None
        chalice_router = inspect.getfile(app)
        if chalice_router.endswith('.pyc'):
            chalice_router = chalice_router[:-1]
        zip.write(chalice_router, 'chalice/app.py')

        chalice_init = inspect.getfile(chalice)
        if chalice_init.endswith('.pyc'):
            chalice_init = chalice_init[:-1]
        zip.write(chalice_init, 'chalice/__init__.py')

        zip.write(os.path.join(project_dir, 'app.py'),
                  'app.py')
        self._add_chalice_lib_if_needed(project_dir, zip)

    def _hash_project_dir(self, requirements_file, vendor_dir):
        # type: (str, str) -> str
        if not os.path.isfile(requirements_file):
            contents = ''
        else:
            with open(requirements_file) as f:
                contents = f.read()
        h = hashlib.md5(contents)
        if os.path.isdir(vendor_dir):
            self._hash_vendor_dir(vendor_dir, h)
        return h.hexdigest()

    def _hash_vendor_dir(self, vendor_dir, md5):
        # type: (str, Any) -> None
        for rootdir, dirnames, filenames in os.walk(vendor_dir):
            for filename in filenames:
                fullpath = os.path.join(rootdir, filename)
                with open(fullpath, 'rb') as f:
                    for chunk in iter(lambda: f.read(1024 * 1024), b''):
                        md5.update(chunk)

    def inject_latest_app(self, deployment_package_filename, project_dir):
        # type: (str, str) -> None
        """Inject latest version of chalice app into a zip package.

        This method takes a pre-created deployment package and injects
        in the latest chalice app code.  This is useful in the case where
        you have no new package deps but have updated your chalice app code.

        :type deployment_package_filename: str
        :param deployment_package_filename: The zipfile of the
            preexisting deployment package.

        :type project_dir: str
        :param project_dir: Path to chalice project dir.

        """
        # Use the premade zip file and replace the app.py file
        # with the latest version.  Python's zipfile does not have
        # a way to do this efficiently so we need to create a new
        # zip file that has all the same stuff except for the new
        # app file.
        print "Regen deployment package..."
        tmpzip = deployment_package_filename + '.tmp.zip'
        with zipfile.ZipFile(deployment_package_filename, 'r') as inzip:
            with zipfile.ZipFile(tmpzip, 'w') as outzip:
                for el in inzip.infolist():
                    if self._needs_latest_version(el.filename):
                        continue
                    else:
                        contents = inzip.read(el.filename)
                        outzip.writestr(el, contents)
                # Then at the end, add back the app.py, chalicelib,
                # and runtime files.
                self._add_app_files(outzip, project_dir)
        shutil.move(tmpzip, deployment_package_filename)

    def _needs_latest_version(self, filename):
        # type: (str) -> bool
        return filename == 'app.py' or filename.startswith(
            ('chalicelib/', 'chalice/'))

    def _add_chalice_lib_if_needed(self, project_dir, zip):
        # type: (str, zipfile.ZipFile) -> None
        libdir = os.path.join(project_dir, self._CHALICE_LIB_DIR)
        if os.path.isdir(libdir):
            for rootdir, dirnames, filenames in os.walk(libdir):
                for filename in filenames:
                    fullpath = os.path.join(rootdir, filename)
                    zip_path = os.path.join(
                        self._CHALICE_LIB_DIR,
                        fullpath[len(libdir) + 1:])
                    zip.write(fullpath, zip_path)