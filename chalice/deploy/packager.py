from __future__ import print_function
import sys
import hashlib
import inspect
import os
import shutil
import subprocess
import zipfile
import tempfile
import contextlib
import pip

import virtualenv
from typing import Any, List, Optional, Tuple, Iterable, Callable  # noqa
from chalice.compat import StringIO
from chalice.utils import OSUtils

import chalice
from chalice import compat, app


class InvalidSourceDistributionNameError(Exception):
    pass


class LambdaDeploymentPackager(object):
    _CHALICE_LIB_DIR = 'chalicelib'
    _VENDOR_DIR = 'vendor'

    def __init__(self, osutils=None):
        # type: (Optional[OSUtils]) -> None
        if osutils is None:
            osutils = OSUtils()
        self._osutils = osutils

    def _get_requirements_file(self, project_dir):
        # type: (str) -> str
        # Gets the path to a requirements.txt file out of a project dir path
        return os.path.join(project_dir, 'requirements.txt')

    def create_deployment_package(self, project_dir, package_filename=None,
                                  dependency_builder=None):
        # type: (str, Optional[str]) -> str
        print("Creating deployment package.")
        # Now we need to create a zip file and add in the site-packages
        # dir first, followed by the app_dir contents next.
        if dependency_builder is None:
            dependency_builder = DependencyBuilder(OSUtils())
        deployment_package_filename = self.deployment_package_filename(
            project_dir)
        if package_filename is None:
            package_filename = deployment_package_filename
        if not os.path.isfile(package_filename):
            dependency_builder.build_site_packages(project_dir)
        site_packages_dir = dependency_builder.site_package_dir(project_dir)
        dirname = os.path.dirname(os.path.abspath(package_filename))
        if not self._osutils.directory_exists(dirname):
            os.makedirs(dirname)
        with zipfile.ZipFile(package_filename, 'w',
                             compression=zipfile.ZIP_DEFLATED) as z:
            self._add_py_deps(z, site_packages_dir)
            self._add_app_files(z, project_dir)
            self._add_vendor_files(z, os.path.join(project_dir,
                                                   self._VENDOR_DIR))
            # TODO here we need to check that all the dependencies caluclated
            # during the add_app_files phase are included in the package or
            # warn the user. They can add pre-built amazon linux dependencies
            # in the vendor folder and rerun the deployment and it should
            # succeed. That warning/error should be issued here.
        return package_filename

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

    def deployment_package_filename(self, project_dir):
        # type: (str) -> str
        # Computes the name of the deployment package zipfile
        # based on a hash of the requirements file.
        # This is done so that we only "pip install -r requirements.txt"
        # when we know there's new dependencies we need to install.
        requirements_file = self._get_requirements_file(project_dir)
        hash_contents = self._hash_project_dir(
            requirements_file, os.path.join(project_dir, self._VENDOR_DIR))
        deployment_package_filename = os.path.join(
            project_dir, '.chalice', 'deployments', hash_contents + '.zip')
        return deployment_package_filename

    def _add_py_deps(self, zip_fileobj, deps_dir):
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
                zip_fileobj.write(full_path, zip_path)

    def _add_app_files(self, zip_fileobj, project_dir):
        # type: (zipfile.ZipFile, str) -> None
        chalice_router = inspect.getfile(app)
        if chalice_router.endswith('.pyc'):
            chalice_router = chalice_router[:-1]
        zip_fileobj.write(chalice_router, 'chalice/app.py')

        chalice_init = inspect.getfile(chalice)
        if chalice_init.endswith('.pyc'):
            chalice_init = chalice_init[:-1]
        zip_fileobj.write(chalice_init, 'chalice/__init__.py')

        zip_fileobj.write(os.path.join(project_dir, 'app.py'),
                          'app.py')
        self._add_chalice_lib_if_needed(project_dir, zip_fileobj)

    def _hash_project_dir(self, requirements_file, vendor_dir):
        # type: (str, str) -> str
        if not os.path.isfile(requirements_file):
            contents = b''
        else:
            with open(requirements_file, 'rb') as f:
                contents = f.read()
        h = hashlib.md5(contents)
        if os.path.isdir(vendor_dir):
            self._hash_vendor_dir(vendor_dir, h)
        return h.hexdigest()

    def _hash_vendor_dir(self, vendor_dir, md5):
        # type: (str, Any) -> None
        for rootdir, _, filenames in os.walk(vendor_dir):
            for filename in filenames:
                fullpath = os.path.join(rootdir, filename)
                with open(fullpath, 'rb') as f:
                    # Not actually an issue, but pylint will complain
                    # about the f var being used in the lambda function
                    # is being used in a loop.  This is ok because
                    # we're immediately using the lambda function.
                    # Also binding it as a default argument fixes
                    # pylint, but mypy will complain that it can't
                    # infer the types.  So the compromise here is to
                    # just write it the idiomatic way and have pylint
                    # ignore this warning.
                    # pylint: disable=cell-var-from-loop
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
        print("Regen deployment package...")
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

    def _add_chalice_lib_if_needed(self, project_dir, zip_fileobj):
        # type: (str, zipfile.ZipFile) -> None
        libdir = os.path.join(project_dir, self._CHALICE_LIB_DIR)
        if os.path.isdir(libdir):
            for rootdir, _, filenames in os.walk(libdir):
                for filename in filenames:
                    fullpath = os.path.join(rootdir, filename)
                    zip_path = os.path.join(
                        self._CHALICE_LIB_DIR,
                        fullpath[len(libdir) + 1:])
                    zip_fileobj.write(fullpath, zip_path)


class DependencyBuilder(object):
    """Build site-packages by manually downloading and unpacking whls.

    Pip is used to download all the dependency sdists. Then wheels that
    compatible with lambda are downloaded. Any source packages that do not
    have a matching wheel file are built into a wheel and that file is checked
    for compatibility with the lambda python runtime environment.

    All compatible wheels that are downloaded/built this way are unpacked
    into a site-packages directory, to be included in the bundle by the
    packager.
    """
    _MANYLINUX_COMPATIBLE_PLAT = {'any', 'linux_x86_64', 'manylinux1_x86_64'}

    def __init__(self, osutils, pip_runner=None):
        self._osutils = osutils
        if pip_runner is None:
            pip_runner = PipRunner(pip)
        self._pip = pip_runner

    def _valid_lambda_whl(self, filename):
        # type: (str) -> bool
        whl = filename[:-4]
        implementation, abi, platform = whl.split('-')[-3:]
        # Verify platform is compatible
        if platform not in self._MANYLINUX_COMPATIBLE_PLAT:
            return False
        # Verify that the ABI is compatible with lambda. Either none or the
        # correct type for the python version cp27mu for py27 and cp36m for
        # py36.
        if abi == 'none':
            return True
        prefix_version = implementation[:3]
        if prefix_version == 'cp3':
            # Deploying python 3 function which means we need cp36m abi
            return abi == 'cp36m'
        elif prefix_version == 'cp2':
            # Deploying to python 2 function which means we need cp27mu abi
            return abi == 'cp27mu'
        # Don't know what we have but it didn't pass compatibility tests.
        return False

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

    @contextlib.contextmanager
    def _tempdir(self):
        # type: () -> Any
        tempdir = tempfile.mkdtemp()
        try:
            yield tempdir
        finally:
            shutil.rmtree(tempdir)

    def _download_dependencies(self, directory, requirements_file):
        # type: (str, str) -> List[Package]
        # Download raw source dependences to get the transitive closure over
        # the dependency graph. Once all have been download (as .tar.gz, .zip
        # files) the wheels can be downloaded for the target platform
        # manylinux1_x86_64 and using the python version from the current
        # python environment, as it is assumed that is the environment that is
        # being deployed to lambda.
        self._pip.download_all_dependencies(requirements_file, directory)

        # Try to get binary whls for each package downloaded above.
        sdists = {Package(filename) for filename
                  in self._osutils.get_directory_contents(directory)}
        self._pip.download_manylinux_whls(
            [pkg.identifier for pkg in sdists], directory)

        # Now that `directory` has all the manylinux1 compatible binary
        # wheels we could get, and all the source distributions. We need to
        # find all the source dists that do not have a mathcing wheel file,
        # and try to build it to a wheel file.
        whls = {Package(filename) for filename
                in self._osutils.get_directory_contents(directory)
                if filename.endswith('.whl')}
        missing_whls = sdists - whls

        # Try to build the missing whl files
        for missing_whl in missing_whls:
            path_to_sdist = os.path.join(directory, missing_whl.filename)
            self._pip.build_wheel(path_to_sdist, directory)

        # Final pass through the directory to ensure that all whl files
        # are present and compatible with the lambda environment.
        final_whls = [Package(filename) for filename
                      in self._osutils.get_directory_contents(directory)
                      if filename.endswith('.whl')]
        valid_whls, invalid_whls = [], []
        for whl in final_whls:
            if self._valid_lambda_whl(whl.filename):
                valid_whls.append(whl)
            else:
                invalid_whls.append(whl)

        return valid_whls

    def _install_whls(self, src_dir, dst_dir, whls):
        # type: (str, str, List[Package]) -> None
        if os.path.isdir(dst_dir):
            shutil.rmtree(dst_dir)
        os.makedirs(dst_dir)
        for whl in whls:
            zipfile_path = os.path.join(src_dir, whl.filename)
            with zipfile.ZipFile(zipfile_path, 'r') as z:
                z.extractall(dst_dir)

    def build_site_packages(self, project_dir):
        # type: (str) -> str
        requirements_file = os.path.join(project_dir, 'requirements.txt')
        deps_dir = self.site_package_dir(project_dir)
        print(deps_dir)
        if self._has_at_least_one_package(requirements_file):
            with self._tempdir() as tempdir:
                tempdir = os.path.abspath('whls')
                whls = self._download_dependencies(tempdir, requirements_file)
                self._install_whls(tempdir, deps_dir, whls)
        return deps_dir

    def site_package_dir(self, project_dir):
        # type: (str) -> str
        """Returns the path to the site packages directory."""
        deps_dir = os.path.join(project_dir, '.chalice', 'site-packages')
        return deps_dir


class Package(object):
    PYPI_SDIST_EXTS = ['.zip', '.tar.gz']

    def __init__(self, filename):
        # type: (str) -> None
        self.dist_type = 'whl' if filename.endswith('whl') else 'sdist'
        self.filename = filename
        self.identifier = self._calculate_identifier()

    def __str__(self):
        # type: () -> str
        return '%s(%s)' % (self.identifier, self.dist_type)

    def __repr__(self):
        # type: () -> str
        return str(self)

    def __eq__(self, other):
        # type: (Any) -> bool
        return self.identifier == other.identifier

    def __hash__(self):
        # type: () -> int
        return hash(self.identifier)

    def _calculate_identifier(self):
        # type: () -> str
        # Identiifer that can be fed into pip ie "name==version"
        if self.dist_type == 'whl':
            # From the wheel spec (PEP 427)
            # {distribution}-{version}(-{build tag})?-{python tag}-{abi tag}-
            # {platform tag}.whl
            name, version = self.filename.split('-')[:2]
        else:
            name, version = self._parse_sdist_filename(self.filename)
        return '%s==%s' % (name, version)

    def _parse_sdist_filename(self, filename):
        # type: (str) -> Tuple[str, str]
        # Filenames are in the format {name}-{version}.tar.gz OR
        # {name}-{version}.zip. These are the only two formats supported by
        # PyPi for source distributions.
        for ext in self.PYPI_SDIST_EXTS:
            if filename.endswith(ext):
                name, version = filename[:-len(ext)].split('-')
                return name, version
        raise InvalidSourceDistributionNameError(filename)


class PipRunner(object):
    """Wrapper around pip calls."""

    def __init__(self, pip_module):
        # type: (Any) -> None
        self._pip = pip_module

    @contextlib.contextmanager
    def _consume_stdout_and_stderr(self):
        # type: () -> Any
        try:
            out, err = sys.stdout, sys.stderr
            temp_out, temp_err = StringIO(), StringIO()
            sys.stdout, sys.stderr = temp_out, temp_err
            yield temp_out, temp_err
        finally:
            sys.stdout, sys.stderr = out, err

    def _execute(self, command, args):
        # type: (str, List[str]) -> int
        """Executes a pip command with the given arguments.

        As an implementation detail this class assumes that pip was imported
        and uses pip.main. This gives us the correct version of python that
        the user is intending to deploy for free, but relies on the pip main
        function not changing, which is very unlikely.
        """
        final_command = [command]
        final_command.extend(args)
        # Call pip and hide stdout/stderr
        with self._consume_stdout_and_stderr():
            rc = self._pip.main(final_command)
        return rc

    def build_wheel(self, wheel, directory):
        # type: (str, str) -> int
        """This command builds an sdist into a wheel file."""
        arguments = ['--no-deps', '--wheel-dir', directory, wheel]
        return self._execute('wheel', arguments)

    def download_all_dependencies(self, requirements_file, directory):
        # type: (str, str) -> int
        """This command downloads all dependencies as sdists."""
        # None of these should fail so we can request non-binary versions of
        # all the packages in one call to `pip download`
        arguments = ['--no-binary=:all:', '-r', requirements_file, '--dest',
                     directory]
        return self._execute('download', arguments)

    def download_manylinux_whls(self, packages, directory):
        # type: (List[str], str) -> None
        """Downloads wheel files for manylinux for all the given packages."""
        # If any one of these dependencies fails pip will bail out. Since we
        # are only interested in all the ones we can download, we need to feed
        # each package to pip individually. The return code of pip doesn't
        # matter here since we will inspect the working directory to see which
        # wheels were downloaded. We are only interested in wheel files
        # compatible with lambda, which means manylinux1_x86_64 platform and
        # cpython implementation. The compatible abi depends on the python
        # version and is checked later.
        for package in packages:
            arguments = ['--only-binary=:all:', '--no-deps', '--platform',
                         'manylinux1_x86_64', '--implementation', 'cp',
                         '--dest', directory, package]
            self._execute('download', arguments)
