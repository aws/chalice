import sys
import hashlib
import inspect
import re
import subprocess
from email.parser import FeedParser
from email.message import Message  # noqa
from zipfile import ZipFile  # noqa

from typing import Any, Set, List, Optional, Tuple, Iterable, Callable  # noqa
from typing import Dict, MutableMapping  # noqa
from chalice.compat import lambda_abi
from chalice.compat import pip_no_compile_c_env_vars
from chalice.compat import pip_no_compile_c_shim
from chalice.utils import OSUtils
from chalice.utils import UI  # noqa
from chalice.constants import MISSING_DEPENDENCIES_TEMPLATE

import chalice
from chalice import app


StrMap = Dict[str, Any]
OptStrMap = Optional[StrMap]
EnvVars = MutableMapping
OptStr = Optional[str]
OptBytes = Optional[bytes]


class InvalidSourceDistributionNameError(Exception):
    pass


class MissingDependencyError(Exception):
    """Raised when some dependencies could not be packaged for any reason."""
    def __init__(self, missing):
        # type: (Set[Package]) -> None
        self.missing = missing


class NoSuchPackageError(Exception):
    """Raised when a package name or version could not be found."""
    def __init__(self, package_name):
        # type: (str) -> None
        super(NoSuchPackageError, self).__init__(
            'Could not satisfy the requirement: %s' % package_name)


class PackageDownloadError(Exception):
    """Generic networking error during a package download."""
    pass


class LambdaDeploymentPackager(object):
    _CHALICE_LIB_DIR = 'chalicelib'
    _VENDOR_DIR = 'vendor'

    def __init__(self, osutils, dependency_builder, ui):
        # type: (OSUtils, DependencyBuilder, UI) -> None
        self._osutils = osutils
        self._dependency_builder = dependency_builder
        self._ui = ui

    def _get_requirements_filename(self, project_dir):
        # type: (str) -> str
        # Gets the path to a requirements.txt file out of a project dir path
        return self._osutils.joinpath(project_dir, 'requirements.txt')

    def create_deployment_package(self, project_dir, python_version,
                                  package_filename=None):
        # type: (str, str, Optional[str]) -> str
        self._ui.write("Creating deployment package.\n")
        # Now we need to create a zip file and add in the site-packages
        # dir first, followed by the app_dir contents next.
        deployment_package_filename = self.deployment_package_filename(
            project_dir, python_version)
        if package_filename is None:
            package_filename = deployment_package_filename
        requirements_filepath = self._get_requirements_filename(project_dir)
        with self._osutils.tempdir() as site_packages_dir:
            try:
                self._dependency_builder.build_site_packages(
                    requirements_filepath, site_packages_dir)
            except MissingDependencyError as e:
                missing_packages = '\n'.join([p.identifier for p
                                              in e.missing])
                self._ui.write(
                    MISSING_DEPENDENCIES_TEMPLATE % missing_packages)
            dirname = self._osutils.dirname(
                self._osutils.abspath(package_filename))
            if not self._osutils.directory_exists(dirname):
                self._osutils.makedirs(dirname)
            with self._osutils.open_zip(package_filename, 'w',
                                        self._osutils.ZIP_DEFLATED) as z:
                self._add_py_deps(z, site_packages_dir)
                self._add_app_files(z, project_dir)
                self._add_vendor_files(z, self._osutils.joinpath(
                    project_dir, self._VENDOR_DIR))
        return package_filename

    def _add_vendor_files(self, zipped, dirname):
        # type: (ZipFile, str) -> None
        if not self._osutils.directory_exists(dirname):
            return
        prefix_len = len(dirname) + 1
        for root, _, filenames in self._osutils.walk(dirname):
            for filename in filenames:
                full_path = self._osutils.joinpath(root, filename)
                zip_path = full_path[prefix_len:]
                zipped.write(full_path, zip_path)

    def deployment_package_filename(self, project_dir, python_version):
        # type: (str, str) -> str
        # Computes the name of the deployment package zipfile
        # based on a hash of the requirements file.
        # This is done so that we only "pip install -r requirements.txt"
        # when we know there's new dependencies we need to install.
        # The python version these depedencies were downloaded for is appended
        # to the end of the filename since the the dependencies may not change
        # but if the python version changes then the dependencies need to be
        # re-downloaded since they will not be compatible.
        requirements_filename = self._get_requirements_filename(project_dir)
        hash_contents = self._hash_project_dir(
            requirements_filename, self._osutils.joinpath(project_dir,
                                                          self._VENDOR_DIR))
        filename = '%s-%s.zip' % (hash_contents, python_version)
        deployment_package_filename = self._osutils.joinpath(
            project_dir, '.chalice', 'deployments', filename)
        return deployment_package_filename

    def _add_py_deps(self, zip_fileobj, deps_dir):
        # type: (ZipFile, str) -> None
        prefix_len = len(deps_dir) + 1
        for root, dirnames, filenames in self._osutils.walk(deps_dir):
            if root == deps_dir and 'chalice' in dirnames:
                # Don't include any chalice deps.  We cherry pick
                # what we want to include in _add_app_files.
                dirnames.remove('chalice')
            for filename in filenames:
                full_path = self._osutils.joinpath(root, filename)
                zip_path = full_path[prefix_len:]
                zip_fileobj.write(full_path, zip_path)

    def _add_app_files(self, zip_fileobj, project_dir):
        # type: (ZipFile, str) -> None
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

    def _hash_project_dir(self, requirements_filename, vendor_dir):
        # type: (str, str) -> str
        if not self._osutils.file_exists(requirements_filename):
            contents = b''
        else:
            contents = self._osutils.get_file_contents(
                requirements_filename, binary=True)
        h = hashlib.md5(contents)
        if self._osutils.directory_exists(vendor_dir):
            self._hash_vendor_dir(vendor_dir, h)
        return h.hexdigest()

    def _hash_vendor_dir(self, vendor_dir, md5):
        # type: (str, Any) -> None
        for rootdir, _, filenames in self._osutils.walk(vendor_dir):
            for filename in filenames:
                fullpath = self._osutils.joinpath(rootdir, filename)
                with self._osutils.open(fullpath, 'rb') as f:
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
        self._ui.write("Regen deployment package.\n")
        tmpzip = deployment_package_filename + '.tmp.zip'

        with self._osutils.open_zip(deployment_package_filename, 'r') as inzip:
            with self._osutils.open_zip(tmpzip, 'w',
                                        self._osutils.ZIP_DEFLATED) as outzip:
                for el in inzip.infolist():
                    if self._needs_latest_version(el.filename):
                        continue
                    else:
                        contents = inzip.read(el.filename)
                        outzip.writestr(el, contents)
                # Then at the end, add back the app.py, chalicelib,
                # and runtime files.
                self._add_app_files(outzip, project_dir)
        self._osutils.move(tmpzip, deployment_package_filename)

    def _needs_latest_version(self, filename):
        # type: (str) -> bool
        return filename == 'app.py' or filename.startswith(
            ('chalicelib/', 'chalice/'))

    def _add_chalice_lib_if_needed(self, project_dir, zip_fileobj):
        # type: (str, ZipFile) -> None
        libdir = self._osutils.joinpath(project_dir, self._CHALICE_LIB_DIR)
        if self._osutils.directory_exists(libdir):
            for rootdir, _, filenames in self._osutils.walk(libdir):
                for filename in filenames:
                    fullpath = self._osutils.joinpath(rootdir, filename)
                    zip_path = self._osutils.joinpath(
                        self._CHALICE_LIB_DIR,
                        fullpath[len(libdir) + 1:])
                    zip_fileobj.write(fullpath, zip_path)


class DependencyBuilder(object):
    """Build site-packages by manually downloading and unpacking wheels.

    Pip is used to download all the dependency sdists. Then wheels that
    compatible with lambda are downloaded. Any source packages that do not
    have a matching wheel file are built into a wheel and that file is checked
    for compatibility with the lambda python runtime environment.

    All compatible wheels that are downloaded/built this way are unpacked
    into a site-packages directory, to be included in the bundle by the
    packager.
    """
    _MANYLINUX_COMPATIBLE_PLATFORM = {'any', 'linux_x86_64',
                                      'manylinux1_x86_64'}
    _COMPATIBLE_PACKAGE_WHITELIST = {
        'sqlalchemy'
    }

    def __init__(self, osutils, pip_runner=None):
        # type: (OSUtils, Optional[PipRunner]) -> None
        self._osutils = osutils
        if pip_runner is None:
            pip_runner = PipRunner(SubprocessPip(osutils))
        self._pip = pip_runner

    def _is_compatible_wheel_filename(self, filename):
        # type: (str) -> bool
        wheel = filename[:-4]
        implementation, abi, platform = wheel.split('-')[-3:]
        # Verify platform is compatible
        if platform not in self._MANYLINUX_COMPATIBLE_PLATFORM:
            return False
        # Verify that the ABI is compatible with lambda. Either none or the
        # correct type for the python version cp27mu for py27 and cp36m for
        # py36.
        if abi == 'none':
            return True
        prefix_version = implementation[:3]
        if prefix_version == 'cp3':
            # Deploying python 3 function which means we need cp36m abi
            # We can also accept abi3 which is the CPython 3 Stable ABI and
            # will work on any version of python 3.
            return abi == 'cp36m' or abi == 'abi3'
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

    def _download_all_dependencies(self, requirements_filename, directory):
        # type: (str, str) -> set[Package]
        # Download dependencies prefering wheel files but falling back to
        # raw source dependences to get the transitive closure over
        # the dependency graph. Return the set of all package objects
        # which will serve as the master list of dependencies needed to deploy
        # successfully.
        self._pip.download_all_dependencies(requirements_filename, directory)
        deps = {Package(directory, filename) for filename
                in self._osutils.get_directory_contents(directory)}
        return deps

    def _download_binary_wheels(self, packages, directory):
        # type: (set[Package], str) -> None
        # Try to get binary wheels for each package that isn't compatible.
        self._pip.download_manylinux_wheels(
            [pkg.identifier for pkg in packages], directory)

    def _build_sdists(self, sdists, directory, compile_c=True):
        # type: (set[Package], str, bool) -> None
        for sdist in sdists:
            path_to_sdist = self._osutils.joinpath(directory, sdist.filename)
            self._pip.build_wheel(path_to_sdist, directory, compile_c)

    def _categorize_wheel_files(self, directory):
        # type: (str) -> Tuple[Set[Package], Set[Package]]
        final_wheels = [Package(directory, filename) for filename
                        in self._osutils.get_directory_contents(directory)
                        if filename.endswith('.whl')]

        compatible_wheels, incompatible_wheels = set(), set()
        for wheel in final_wheels:
            if self._is_compatible_wheel_filename(wheel.filename):
                compatible_wheels.add(wheel)
            else:
                incompatible_wheels.add(wheel)
        return compatible_wheels, incompatible_wheels

    def _download_dependencies(self, directory, requirements_filename):
        # type: (str, str) -> Tuple[Set[Package], Set[Package]]
        # Download all dependencies we can, letting pip choose what to
        # download.
        # deps should represent the best effort we can make to gather all the
        # dependencies.
        deps = self._download_all_dependencies(
            requirements_filename, directory)

        # Sort the downloaded packages into three categories:
        # - sdists (Pip could not get a wheel so it gave us an sdist)
        # - lambda compatible wheel files
        # - lambda incompatible wheel files
        # Pip will give us a wheel when it can, but some distributions do not
        # ship with wheels at all in which case we will have an sdist for it.
        # In some cases a platform specific wheel file may be availble so pip
        # will have downloaded that, if our platform does not match the
        # platform lambda runs on (linux_x86_64/manylinux) then the downloaded
        # wheel file may not be compatible with lambda. Pure python wheels
        # still will be compatible because they have no platform dependencies.
        compatible_wheels = set()
        incompatible_wheels = set()
        sdists = set()
        for package in deps:
            if package.dist_type == 'sdist':
                sdists.add(package)
            else:
                if self._is_compatible_wheel_filename(package.filename):
                    compatible_wheels.add(package)
                else:
                    incompatible_wheels.add(package)

        # Next we need to go through the downloaded packages and pick out any
        # dependencies that do not have a compatible wheel file downloaded.
        # For these packages we need to explicitly try to download a
        # compatible wheel file.
        missing_wheels = sdists | incompatible_wheels
        self._download_binary_wheels(missing_wheels, directory)

        # Re-count the wheel files after the second download pass. Anything
        # that has an sdist but not a valid wheel file is still not going to
        # work on lambda and we must now try and build the sdist into a wheel
        # file ourselves.
        compatible_wheels, incompatible_wheels = self._categorize_wheel_files(
            directory)
        missing_wheels = sdists - compatible_wheels
        self._build_sdists(missing_wheels, directory, compile_c=True)

        # There is still the case where the package had optional C dependencies
        # for speedups. In this case the wheel file will have built above with
        # the C dependencies if it managed to find a C compiler. If we are on
        # an incompatible architecture this means the wheel file generated will
        # not be compatible. If we categorize our files once more and find that
        # there are missing dependencies we can try our last ditch effort of
        # building the package and trying to sever its ability to find a C
        # compiler.
        compatible_wheels, incompatible_wheels = self._categorize_wheel_files(
            directory)
        missing_wheels = sdists - compatible_wheels
        self._build_sdists(missing_wheels, directory, compile_c=False)

        # Final pass to find the compatible wheel files and see if there are
        # any unmet dependencies left over. At this point there is nothing we
        # can do about any missing wheel files. We tried downloading a
        # compatible version directly and building from source.
        compatible_wheels, incompatible_wheels = self._categorize_wheel_files(
            directory)

        # Now there is still the case left over where the setup.py has been
        # made in such a way to be incompatible with python's setup tools,
        # causing it to lie about its compatibility. To fix this we have a
        # manually curated whitelist of packages that will work, despite
        # claiming otherwise.
        compatible_wheels, incompatible_wheels = self._apply_wheel_whitelist(
            compatible_wheels, incompatible_wheels)
        missing_wheels = deps - compatible_wheels

        return compatible_wheels, missing_wheels

    def _apply_wheel_whitelist(self,
                               compatible_wheels,   # type: Set[Package]
                               incompatible_wheels  # type: Set[Package]
                               ):
        # (...) ->Tuple[Set[Package], Set[Package]]
        compatible_wheels = set(compatible_wheels)
        actual_incompatible_wheels = set()
        for missing_package in incompatible_wheels:
            if missing_package.name in self._COMPATIBLE_PACKAGE_WHITELIST:
                compatible_wheels.add(missing_package)
            else:
                actual_incompatible_wheels.add(missing_package)
        return compatible_wheels, actual_incompatible_wheels

    def _install_purelib_and_platlib(self, wheel, root):
        # type: (Package, str) -> None
        # Take a wheel package and the directory it was just unpacked into and
        # unpackage the purelib/platlib directories if they are present into
        # the parent directory. On some systems purelib and platlib need to
        # be installed into separate locations, for lambda this is not the case
        # and both should be installed in site-packages.
        data_dir = self._osutils.joinpath(root, wheel.data_dir)
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

    def _install_wheels(self, src_dir, dst_dir, wheels):
        # type: (str, str, Set[Package]) -> None
        if self._osutils.directory_exists(dst_dir):
            self._osutils.rmtree(dst_dir)
        self._osutils.makedirs(dst_dir)
        for wheel in wheels:
            zipfile_path = self._osutils.joinpath(src_dir, wheel.filename)
            self._osutils.extract_zipfile(zipfile_path, dst_dir)
            self._install_purelib_and_platlib(wheel, dst_dir)

    def build_site_packages(self, requirements_filepath, target_directory):
        # type: (str, str) -> None
        if self._has_at_least_one_package(requirements_filepath):
            with self._osutils.tempdir() as tempdir:
                wheels, packages_without_wheels = self._download_dependencies(
                    tempdir, requirements_filepath)
                self._install_wheels(tempdir, target_directory, wheels)
            if packages_without_wheels:
                raise MissingDependencyError(packages_without_wheels)


class Package(object):
    """A class to represent a package downloaded but not yet installed."""
    def __init__(self, directory, filename, osutils=None):
        # type: (str, str, Optional[OSUtils]) -> None
        self.dist_type = 'wheel' if filename.endswith('.whl') else 'sdist'
        self._directory = directory
        self.filename = filename
        if osutils is None:
            osutils = OSUtils()
        self._osutils = osutils
        self._name, self._version = self._calculate_name_and_version()

    @property
    def name(self):
        # type: () -> str
        return self._name

    @property
    def data_dir(self):
        # type: () -> str
        # The directory format is {distribution}-{version}.data
        return '%s-%s.data' % (self._name, self._version)

    def _normalize_name(self, name):
        # type: (str) -> str
        # Taken directly from PEP 503
        return re.sub(r"[-_.]+", "-", name).lower()

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
        if not isinstance(other, Package):
            return False
        return self.identifier == other.identifier

    def __hash__(self):
        # type: () -> int
        return hash(self.identifier)

    def _calculate_name_and_version(self):
        # type: () -> Tuple[str, str]
        if self.dist_type == 'wheel':
            # From the wheel spec (PEP 427)
            # {distribution}-{version}(-{build tag})?-{python tag}-{abi tag}-
            # {platform tag}.whl
            name, version = self.filename.split('-')[:2]
        else:
            info_fetcher = SDistMetadataFetcher(osutils=self._osutils)
            sdist_path = self._osutils.joinpath(self._directory, self.filename)
            name, version = info_fetcher.get_package_name_and_version(
                sdist_path)
        normalized_name = self._normalize_name(name)
        return normalized_name, version


class SDistMetadataFetcher(object):
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
        # type: (Optional[OSUtils]) -> None
        if osutils is None:
            osutils = OSUtils()
        self._osutils = osutils

    def _parse_pkg_info_file(self, filepath):
        # type: (str) -> Message
        # The PKG-INFO generated by the egg-info command is in an email feed
        # format, so we use an email feedparser here to extract the metadata
        # from the PKG-INFO file.
        data = self._osutils.get_file_contents(filepath, binary=False)
        parser = FeedParser()
        parser.feed(data)
        return parser.close()

    def _generate_egg_info(self, package_dir):
        # type: (str) -> str
        setup_py = self._osutils.joinpath(package_dir, 'setup.py')
        script = self._SETUPTOOLS_SHIM % setup_py

        cmd = [sys.executable, '-c', script, '--no-user-cfg', 'egg_info',
               '--egg-base', 'egg-info']
        egg_info_dir = self._osutils.joinpath(package_dir, 'egg-info')
        self._osutils.makedirs(egg_info_dir)
        p = subprocess.Popen(cmd, cwd=package_dir,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        p.communicate()
        info_contents = self._osutils.get_directory_contents(egg_info_dir)
        pkg_info_path = self._osutils.joinpath(
            egg_info_dir, info_contents[0], 'PKG-INFO')
        return pkg_info_path

    def _unpack_sdist_into_dir(self, sdist_path, unpack_dir):
        # type: (str, str) -> str
        if sdist_path.endswith('.zip'):
            self._osutils.extract_zipfile(sdist_path, unpack_dir)
        elif sdist_path.endswith(('.tar.gz', '.tar.bz2')):
            self._osutils.extract_tarfile(sdist_path, unpack_dir)
        else:
            raise InvalidSourceDistributionNameError(sdist_path)
        # There should only be one directory unpacked.
        contents = self._osutils.get_directory_contents(unpack_dir)
        return self._osutils.joinpath(unpack_dir, contents[0])

    def get_package_name_and_version(self, sdist_path):
        # type: (str) -> Tuple[str, str]
        with self._osutils.tempdir() as tempdir:
            package_dir = self._unpack_sdist_into_dir(sdist_path, tempdir)
            pkg_info_filepath = self._generate_egg_info(package_dir)
            metadata = self._parse_pkg_info_file(pkg_info_filepath)
            name = metadata['Name']
            version = metadata['Version']
        return name, version


class SubprocessPip(object):
    """Wrapper around calling pip through a subprocess."""
    def __init__(self, osutils=None):
        # type: (Optional[OSUtils]) -> None
        if osutils is None:
            osutils = OSUtils()
        self._osutils = osutils

    def main(self, args, env_vars=None, shim=None):
        # type: (List[str], EnvVars, OptStr) -> Tuple[int, Optional[bytes]]
        if env_vars is None:
            env_vars = self._osutils.environ()
        if shim is None:
            shim = ''
        python_exe = sys.executable
        run_pip = 'import pip, sys; sys.exit(pip.main(%s))' % args
        exec_string = '%s%s' % (shim, run_pip)
        invoke_pip = [python_exe, '-c', exec_string]
        p = subprocess.Popen(invoke_pip,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             env=env_vars)
        _, err = p.communicate()
        rc = p.returncode
        return rc, err


class PipRunner(object):
    """Wrapper around pip calls used by chalice."""
    def __init__(self, pip, osutils=None):
        # type: (SubprocessPip, Optional[OSUtils]) -> None
        if osutils is None:
            osutils = OSUtils()
        self._wrapped_pip = pip
        self._osutils = osutils

    def _execute(self, command, args, env_vars=None, shim=None):
        # type: (str, List[str], EnvVars, OptStr) -> Tuple[int, OptBytes]
        """Execute a pip command with the given arguments."""
        main_args = [command] + args
        rc, err = self._wrapped_pip.main(main_args, env_vars=env_vars,
                                         shim=shim)
        return rc, err

    def build_wheel(self, wheel, directory, compile_c=True):
        # type: (str, str, bool) -> None
        """Build an sdist into a wheel file."""
        arguments = ['--no-deps', '--wheel-dir', directory, wheel]
        env_vars = self._osutils.environ()
        shim = ''
        if not compile_c:
            env_vars.update(pip_no_compile_c_env_vars)
            shim = pip_no_compile_c_shim
        # Ignore rc and stderr from this command since building the wheels
        # may fail and we will find out when we categorize the files that were
        # generated.
        self._execute('wheel', arguments,
                      env_vars=env_vars, shim=shim)

    def download_all_dependencies(self, requirements_filename, directory):
        # type: (str, str) -> None
        """Download all dependencies as sdist or wheel."""
        arguments = ['-r', requirements_filename, '--dest', directory]
        rc, err = self._execute('download', arguments)
        # When downloading all dependencies we expect to get an rc of 0 back
        # since we are casting a wide net here letting pip have options about
        # what to download. If a package is not found it is likely because it
        # does not exist and was mispelled. In this case we raise an error with
        # the package name. Otherwise a nonzero rc results in a generic
        # download error where we pass along the stderr.
        if rc != 0:
            if err is None:
                err = b'Unknown error'
            error = err.decode()
            match = re.search(("Could not find a version that satisfies the "
                               "requirement (.+?) "), error)
            if match:
                package_name = match.group(1)
                raise NoSuchPackageError(str(package_name))
            raise PackageDownloadError(error)

    def download_manylinux_wheels(self, packages, directory):
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
