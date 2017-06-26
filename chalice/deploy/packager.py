from __future__ import print_function
import sys
import hashlib
import inspect
import os
import re
import shutil
import zipfile
import tarfile
import subprocess
from email.parser import FeedParser
from email.message import Message  # noqa

from typing import Any, Set, List, Optional, Tuple, Iterable, Callable  # noqa
from chalice.compat import lambda_abi
from chalice.utils import OSUtils
from chalice.constants import MISSING_DEPENDENCIES_TEMPLATE

import chalice
from chalice import app


class InvalidSourceDistributionNameError(Exception):
    pass


class MissingDependencyError(Exception):
    def __init__(self, missing):
        # type: (Set[Package]) -> None
        self.missing = missing


class PipError(Exception):
    pass


class LambdaDeploymentPackager(object):
    _CHALICE_LIB_DIR = 'chalicelib'
    _VENDOR_DIR = 'vendor'

    def __init__(self, dependency_builder=None):
        # type: (Optional[DependencyBuilder]) -> None
        self._osutils = OSUtils()
        if dependency_builder is None:
            dependency_builder = DependencyBuilder(self._osutils)
        self._dependency_builder = dependency_builder

    def _get_requirements_file(self, project_dir):
        # type: (str) -> str
        # Gets the path to a requirements.txt file out of a project dir path
        return self._osutils.joinpath(project_dir, 'requirements.txt')

    def create_deployment_package(self, project_dir, package_filename=None):
        # type: (str, Optional[str]) -> str
        print("Creating deployment package.")
        # Now we need to create a zip file and add in the site-packages
        # dir first, followed by the app_dir contents next.
        deployment_package_filename = self.deployment_package_filename(
            project_dir)
        if package_filename is None:
            package_filename = deployment_package_filename
        try:
            self._dependency_builder.build_site_packages(project_dir)
        except MissingDependencyError as e:
            missing_packages = '\n'.join([p.identifier for p
                                          in e.missing])
            print(MISSING_DEPENDENCIES_TEMPLATE % missing_packages)
        site_packages_dir = self._dependency_builder.site_package_dir(
            project_dir)
        dirname = self._osutils.dirname(
            self._osutils.abspath(package_filename))
        if not self._osutils.directory_exists(dirname):
            self._osutils.makedirs(dirname)
        with zipfile.ZipFile(package_filename, 'w',
                             compression=zipfile.ZIP_DEFLATED) as z:
            self._add_py_deps(z, site_packages_dir)
            self._add_app_files(z, project_dir)
            self._add_vendor_files(z, self._osutils.joinpath(project_dir,
                                                             self._VENDOR_DIR))
        return package_filename

    def _add_vendor_files(self, zipped, dirname):
        # type: (zipfile.ZipFile, str) -> None
        if not self._osutils.directory_exists(dirname):
            return
        prefix_len = len(dirname) + 1
        for root, _, filenames in self._osutils.walk(dirname):
            for filename in filenames:
                full_path = self._osutils.joinpath(root, filename)
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
            requirements_file, self._osutils.joinpath(project_dir,
                                                      self._VENDOR_DIR))
        deployment_package_filename = self._osutils.joinpath(
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
                full_path = self._osutils.joinpath(root, filename)
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

        zip_fileobj.write(self._osutils.joinpath(project_dir, 'app.py'),
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
            with zipfile.ZipFile(tmpzip, 'w', zipfile.ZIP_DEFLATED) as outzip:
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
        # type: (OSUtils, Optional[PipRunner]) -> None
        self._osutils = osutils
        if pip_runner is None:
            pip_runner = PipRunner(SubprocessPip())
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
        if not self._osutils.file_exists(filename):
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

    def _download_all_dependencies(self, requirements_file, directory):
        # type: (str, str) -> set[Package]
        # Download dependencies prefering wheel files but falling back to
        # raw source dependences to get the transitive closure over
        # the dependency graph. Return the set of all package objects
        # which will serve as the master list of dependencies needed to deploy
        # successfully.
        self._pip.download_all_dependencies(requirements_file, directory)
        deps = {Package(directory, filename) for filename
                in self._osutils.get_directory_contents(directory)}
        return deps

    def _download_binary_wheels(self, packages, directory):
        # type: (set[Package], str) -> None
        # Try to get binary whls for each package that isn't compatible.
        self._pip.download_manylinux_whls(
            [pkg.identifier for pkg in packages], directory)

    def _build_sdists(self, sdists, directory):
        # type: (set[Package], str) -> None
        for sdist in sdists:
            path_to_sdist = self._osutils.joinpath(directory, sdist.filename)
            self._pip.build_wheel(path_to_sdist, directory)

    def _categorize_whl_files(self, directory):
        # type: (str) -> Tuple[Set[Package], Set[Package]]
        final_whls = [Package(directory, filename) for filename
                      in self._osutils.get_directory_contents(directory)
                      if filename.endswith('.whl')]
        valid_whls, invalid_whls = set(), set()
        for whl in final_whls:
            if self._valid_lambda_whl(whl.filename):
                valid_whls.add(whl)
            else:
                invalid_whls.add(whl)
        return valid_whls, invalid_whls

    def _download_dependencies(self, directory, requirements_file):
        # type: (str, str) -> Tuple[Set[Package], Set[Package]]
        # Download all dependencies we can, letting pip choose what to download
        deps = self._download_all_dependencies(requirements_file, directory)

        # Sort the downloaded packages into three categories:
        # - sdists (Pip could not get a wheel so it gave us a sdist)
        # - valid whls (lambda compatbile wheel files)
        # - invalid whls (lambda incompatible wheel files)
        valid_whls, invalid_whls = self._categorize_whl_files(directory)
        sdists = deps - valid_whls - invalid_whls

        # Find which packages we do not yet have a valid whl file for. And
        # try to download them specifically with lambda.
        missing_whls = sdists | invalid_whls
        self._download_binary_wheels(missing_whls, directory)

        # Re-count the whl files after the second download pass. Anything
        # that has a sdist but not a valid whl file is still missing and needs
        # to be built from source into a wheel file.
        valid_whls, invalid_whls = self._categorize_whl_files(directory)
        missing_whls = sdists - valid_whls
        self._build_sdists(missing_whls, directory)

        # Final pass to find the valid whl files and see if there are any
        # unmet dependencies left over. At this point there is nothing we can
        # do about any missing wheel files.
        valid_whls, _ = self._categorize_whl_files(directory)
        missing_whls = deps - valid_whls
        return valid_whls, missing_whls

    def _install_purelib_and_platlib(self, whl, root):
        # type: (Package, str) -> None
        # Take a wheel package and the directory it was just unpacked into and
        # properly unpackage the purelib and platlib subdirectories if they
        # are present.
        data_dir = self._osutils.joinpath(root, whl.data_dir)
        if not self._osutils.directory_exists(data_dir):
            return
        unpack_dirs = {'purelib', 'platlib'}
        data_contents = self._osutils.get_directory_contents(data_dir)
        for content_name in data_contents:
            if content_name in unpack_dirs:
                source = self._osutils.joinpath(data_dir, content_name)
                self._osutils.copytree(source, root)
                # No reason to keep the purelib/platlib source directory around
                # so we delete it to conserve space in the package.
                self._osutils.rmtree(source)

    def _install_whls(self, src_dir, dst_dir, whls):
        # type: (str, str, Set[Package]) -> None
        if os.path.isdir(dst_dir):
            shutil.rmtree(dst_dir)
        os.makedirs(dst_dir)
        for whl in whls:
            zipfile_path = self._osutils.joinpath(src_dir, whl.filename)
            with zipfile.ZipFile(zipfile_path, 'r') as z:
                z.extractall(dst_dir)
            self._install_purelib_and_platlib(whl, dst_dir)

    def build_site_packages(self, project_dir):
        # type: (str) -> None
        requirements_file = self._osutils.joinpath(
            project_dir, 'requirements.txt')
        deps_dir = self.site_package_dir(project_dir)
        if self._has_at_least_one_package(requirements_file):
            with self._osutils.tempdir() as tempdir:
                valid_whls, missing_whls = self._download_dependencies(
                    tempdir, requirements_file)
                self._install_whls(tempdir, deps_dir, valid_whls)
            if missing_whls:
                raise MissingDependencyError(missing_whls)

    def site_package_dir(self, project_dir):
        # type: (str) -> str
        """Return path to the site packages directory."""
        deps_dir = self._osutils.joinpath(
            project_dir, '.chalice', 'site-packages')
        return deps_dir


class Package(object):
    PYPI_SDIST_EXTS = ['.zip', '.tar.gz']

    def __init__(self, directory, filename):
        # type: (str, str) -> None
        self.dist_type = 'whl' if filename.endswith('whl') else 'sdist'
        self.filename = filename
        self._directory = directory
        self._name, self._version = self._calculate_name_and_version()

    @property
    def data_dir(self):
        # type: () -> str
        # The directory format is {distribution}-{version}.data
        return '%s-%s.data' % (self._name, self._version)

    @property
    def identifier(self):
        # type: () -> str
        return '%s==%s' % (self._name, self._version)

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

    def _calculate_name_and_version(self):
        # type: () -> Tuple[str, str]
        if self.dist_type == 'whl':
            # From the wheel spec (PEP 427)
            # {distribution}-{version}(-{build tag})?-{python tag}-{abi tag}-
            # {platform tag}.whl
            name, version = self.filename.split('-')[:2]
        else:
            info_fetcher = SdistMetadataFetcher()
            name, version = info_fetcher.get_package_name_and_version(
                self._directory, self.filename)
        return name, version


class SdistMetadataFetcher(object):
    """This is the "correct" way to get name and version from an sdist."""
    # https://git.io/vQkwV
    _SETUPTOOLS_SHIM = (
        "import setuptools, tokenize;__file__=%r;"
        "f=getattr(tokenize, 'open', open)(__file__);"
        "code=f.read().replace('\\r\\n', '\\n');"
        "f.close();"
        "exec(compile(code, __file__, 'exec'))"
    )

    def __init__(self, osutils=None):
        # type: (OSUtils) -> None
        if osutils is None:
            osutils = OSUtils()
        self._osutils = osutils

    def _parse_pkg_info_file(self, filepath):
        # type: (str) -> Message
        with open(filepath, 'r') as f:
            data = f.read()
        parser = FeedParser()
        parser.feed(data)
        return parser.close()

    def _generate_egg_info(self, package_dir):
        # type: (str) -> str
        setup_py = self._osutils.joinpath(package_dir, 'setup.py')
        script = self._SETUPTOOLS_SHIM % setup_py

        cmd = [sys.executable, '-c', script, '--no-user-cfg', 'egg_info']
        egg_info_dir = self._osutils.joinpath(package_dir, 'egg-info')
        self._osutils.makedirs(egg_info_dir)
        cmd += ['--egg-base', 'egg-info']
        p = subprocess.Popen(cmd, cwd=package_dir,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        p.communicate()
        self._osutils.joinpath(egg_info_dir)
        info_contents = self._osutils.get_directory_contents(egg_info_dir)
        assert len(info_contents) == 1
        pkg_info_path = self._osutils.joinpath(
            egg_info_dir, info_contents[0], 'PKG-INFO')
        return pkg_info_path

    def _unpack_sdist_into_dir(self, sdist_path, unpack_dir):
        # type: (str, str) -> str
        if sdist_path.endswith('zip'):
            with zipfile.ZipFile(sdist_path, 'r') as z:
                z.extractall(unpack_dir)
        elif sdist_path.endswith('.tar.gz'):
            with tarfile.open(sdist_path, 'r:gz') as tar:
                tar.extractall(unpack_dir)
        else:
            raise InvalidSourceDistributionNameError(sdist_path)
        # There should only be one directory unpacked.
        contents = self._osutils.get_directory_contents(unpack_dir)
        assert len(contents) == 1
        return self._osutils.joinpath(unpack_dir, contents[0])

    def get_package_name_and_version(self, directory, filename):
        # type: (str, str) -> Tuple[str, str]
        sdist_path = self._osutils.joinpath(directory, filename)
        with self._osutils.tempdir() as tempdir:
            package_dir = self._unpack_sdist_into_dir(sdist_path, tempdir)
            pkg_info_filepath = self._generate_egg_info(package_dir)
            metadata = self._parse_pkg_info_file(pkg_info_filepath)
            name = metadata['Name']
            version = metadata['Version']
        return name, version


class PipWrapper(object):
    def main(self, args):
        # type: (List[str]) -> Tuple[Optional[bytes], Optional[bytes]]
        raise NotImplementedError('PipWrapper.main')


class SubprocessPip(PipWrapper):
    """Wrapper around calling pip through a subprocess."""
    def main(self, args):
        # type: (List[str]) -> Tuple[Optional[bytes], Optional[bytes]]
        python_exe = sys.executable
        invoke_pip = [python_exe, '-m', 'pip']
        invoke_pip.extend(args)
        p = subprocess.Popen(invoke_pip,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        out, err = p.communicate()
        return out, err


class PipRunner(object):
    """Wrapper around pip calls used by chalice."""

    def __init__(self, pip):
        # type: (PipWrapper) -> None
        self._wrapped_pip = pip

    def _execute(self, command, args):
        # type: (str, List[str]) -> None
        """Execute a pip command with the given arguments."""
        main_args = [command] + args
        _, err = self._wrapped_pip.main(main_args)
        if err:
            if b'ReadTimeoutError' in err:
                raise PipError('Read time out downloading dependencies.')
            if b'NewConnectionError' in err:
                raise PipError('Failed to establish a new connection when '
                               'downloading dependencies.')
            if b'PermissionError' in err:
                match = re.search("Permission denied: '(.+?)'", str(err))
                raise PipError('Do not have permissions to write to %s.'
                               % match.group(1))

    def build_wheel(self, wheel, directory):
        # type: (str, str) -> None
        """Build an sdist into a wheel file."""
        arguments = ['--no-deps', '--wheel-dir', directory, wheel]
        self._execute('wheel', arguments)

    def download_all_dependencies(self, requirements_file, directory):
        # type: (str, str) -> None
        """Download all dependencies as sdist or whl."""
        arguments = ['-r', requirements_file, '--dest', directory]
        self._execute('download', arguments)

    def download_manylinux_whls(self, packages, directory):
        # type: (List[str], str) -> None
        """Download wheel files for manylinux for all the given packages."""
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
                         '--abi', lambda_abi, '--dest', directory, package]
            self._execute('download', arguments)
