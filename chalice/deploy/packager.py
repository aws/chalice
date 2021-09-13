# pylint: disable=too-many-lines
import sys
import hashlib
import inspect
import re
import subprocess
import logging
import functools
from email.parser import FeedParser
from email.message import Message  # noqa
from zipfile import ZipFile  # noqa

from typing import Any, Set, List, Optional, Tuple, Iterable, Callable  # noqa
from typing import Iterator  # noqa
from typing import Dict, MutableMapping, cast  # noqa
from chalice.compat import pip_import_string
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

logger = logging.getLogger(__name__)


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


class EmptyPackageError(Exception):
    """A deployment package cannot be an empty zip file."""


class UnsupportedPackageError(Exception):
    """Unable to parse package metadata."""
    def __init__(self, package_name):
        # type: (str) -> None
        super(UnsupportedPackageError, self).__init__(
            'Unable to retrieve name/version for package: %s' % package_name)


class BaseLambdaDeploymentPackager(object):
    _CHALICE_LIB_DIR = 'chalicelib'
    _VENDOR_DIR = 'vendor'

    _RUNTIME_TO_ABI = {
        'python2.7': 'cp27mu',
        'python3.6': 'cp36m',
        'python3.7': 'cp37m',
        'python3.8': 'cp38',
        'python3.9': 'cp39'
    }

    def __init__(self, osutils, dependency_builder, ui):
        # type: (OSUtils, DependencyBuilder, UI) -> None
        self._osutils = osutils
        self._dependency_builder = dependency_builder
        self._ui = ui

    def create_deployment_package(self, project_dir, python_version):
        # type: (str, str) -> str
        raise NotImplementedError("create_deployment_package")

    def _get_requirements_filename(self, project_dir):
        # type: (str) -> str
        # Gets the path to a requirements.txt file out of a project dir path
        return self._osutils.joinpath(project_dir, 'requirements.txt')

    def _add_vendor_files(self, zipped, dirname, prefix=''):
        # type: (ZipFile, str, str) -> None
        if not self._osutils.directory_exists(dirname):
            return
        prefix_len = len(dirname) + 1
        for root, _, filenames in self._osutils.walk(dirname,
                                                     followlinks=True):
            for filename in filenames:
                full_path = self._osutils.joinpath(root, filename)
                zip_path = full_path[prefix_len:]
                if prefix:
                    zip_path = self._osutils.joinpath(prefix, zip_path)
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
        return self._deployment_package_filename(project_dir, python_version)

    def _deployment_package_filename(self, project_dir, python_version,
                                     prefix=''):
        # type: (str, str, str) -> str
        requirements_filename = self._get_requirements_filename(project_dir)
        hash_contents = self._hash_project_dir(
            requirements_filename,
            self._osutils.joinpath(project_dir, self._VENDOR_DIR),
            project_dir
        )
        filename = '%s%s-%s.zip' % (prefix, hash_contents, python_version)
        deployment_package_filename = self._osutils.joinpath(
            project_dir, '.chalice', 'deployments', filename)
        return deployment_package_filename

    def _add_py_deps(self, zip_fileobj, deps_dir, prefix=''):
        # type: (ZipFile, str, str) -> None
        prefix_len = len(deps_dir) + 1
        for root, dirnames, filenames in self._osutils.walk(deps_dir):
            if root == deps_dir and 'chalice' in dirnames:
                # Don't include any chalice deps.  We cherry pick
                # what we want to include in _add_app_files.
                dirnames.remove('chalice')
            for filename in filenames:
                full_path = self._osutils.joinpath(root, filename)
                zip_path = full_path[prefix_len:]
                if prefix:
                    zip_path = self._osutils.joinpath(prefix, zip_path)
                zip_fileobj.write(full_path, zip_path)

    def _add_app_files(self, zip_fileobj, project_dir):
        # type: (ZipFile, str) -> None
        for full_path, zip_path in self._iter_app_filenames(project_dir):
            zip_fileobj.write(full_path, zip_path)

    def _iter_app_filenames(self, project_dir):
        # type: (str) -> Iterator[Tuple[str, str]]
        chalice_router = inspect.getfile(app)
        if chalice_router.endswith('.pyc'):
            chalice_router = chalice_router[:-1]
        yield (chalice_router, 'chalice/app.py')

        chalice_init = inspect.getfile(chalice)
        if chalice_init.endswith('.pyc'):
            chalice_init = chalice_init[:-1]
        yield (chalice_init, 'chalice/__init__.py')
        yield (self._osutils.joinpath(project_dir, 'app.py'), 'app.py')
        for filename in self._iter_chalice_lib_if_needed(project_dir):
            yield filename

    def _hash_project_dir(self, requirements_filename, vendor_dir,
                          project_dir):
        # type: (str, str, str) -> str
        if not self._osutils.file_exists(requirements_filename):
            contents = b''
        else:
            contents = cast(bytes, self._osutils.get_file_contents(
                requirements_filename, binary=True))
        h = hashlib.md5(contents)
        for filename, _ in self._iter_app_filenames(project_dir):
            with self._osutils.open(filename, 'rb') as f:
                reader = functools.partial(f.read, 1024 * 1024)
                for chunk in iter(reader, b''):
                    h.update(chunk)
        if self._osutils.directory_exists(vendor_dir):
            self._hash_vendor_dir(vendor_dir, h)
        return h.hexdigest()

    def _hash_vendor_dir(self, vendor_dir, md5):
        # type: (str, Any) -> None
        for rootdir, _, filenames in self._osutils.walk(vendor_dir,
                                                        followlinks=True):
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
                    reader = functools.partial(f.read, 1024 * 1024)
                    for chunk in iter(reader, b''):
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

    def _iter_chalice_lib_if_needed(self, project_dir):
        # type: (str) -> Iterator[Tuple[str, str]]
        libdir = self._osutils.joinpath(project_dir, self._CHALICE_LIB_DIR)
        if self._osutils.directory_exists(libdir):
            for rootdir, _, filenames in self._osutils.walk(libdir):
                for filename in filenames:
                    fullpath = self._osutils.joinpath(rootdir, filename)
                    zip_path = self._osutils.joinpath(
                        self._CHALICE_LIB_DIR,
                        fullpath[len(libdir) + 1:])
                    yield (fullpath, zip_path)

    def _create_output_dir_if_needed(self, package_filename):
        # type: (str) -> None
        dirname = self._osutils.dirname(
            self._osutils.abspath(package_filename))
        if not self._osutils.directory_exists(dirname):
            self._osutils.makedirs(dirname)

    def _build_python_dependencies(self, python_version, requirements_filepath,
                                   site_packages_dir):
        # type: (str, str, str) -> None
        try:
            abi = self._RUNTIME_TO_ABI[python_version]
            self._dependency_builder.build_site_packages(
                abi, requirements_filepath, site_packages_dir)
        except MissingDependencyError as e:
            missing_packages = '\n'.join([p.identifier for p in e.missing])
            self._ui.write(MISSING_DEPENDENCIES_TEMPLATE % missing_packages)


class LambdaDeploymentPackager(BaseLambdaDeploymentPackager):
    def create_deployment_package(self, project_dir, python_version):
        # type: (str, str) -> str
        msg = "Creating deployment package."
        self._ui.write("%s\n" % msg)
        logger.debug(msg)
        package_filename = self.deployment_package_filename(
            project_dir, python_version)
        if self._osutils.file_exists(package_filename):
            self._ui.write("Reusing existing deployment package.\n")
            return package_filename
        self._create_output_dir_if_needed(package_filename)
        with self._osutils.tempdir() as tmpdir:
            requirements_filepath = self._get_requirements_filename(
                project_dir)
            self._build_python_dependencies(python_version,
                                            requirements_filepath,
                                            site_packages_dir=tmpdir)
            with self._osutils.open_zip(package_filename, 'w',
                                        self._osutils.ZIP_DEFLATED) as z:
                self._add_py_deps(z, deps_dir=tmpdir)
                self._add_app_files(z, project_dir)
                self._add_vendor_files(z, self._osutils.joinpath(
                    project_dir, self._VENDOR_DIR))
        return package_filename


class AppOnlyDeploymentPackager(BaseLambdaDeploymentPackager):
    def create_deployment_package(self, project_dir, python_version):
        # type: (str, str) -> str
        msg = "Creating app deployment package."
        self._ui.write("%s\n" % msg)
        logger.debug(msg)
        package_filename = self.deployment_package_filename(project_dir,
                                                            python_version)
        if self._osutils.file_exists(package_filename):
            self._ui.write("  Reusing existing app deployment package.\n")
            return package_filename
        self._create_output_dir_if_needed(package_filename)
        with self._osutils.open_zip(package_filename, 'w',
                                    self._osutils.ZIP_DEFLATED) as z:
            self._add_app_files(z, project_dir)
        return package_filename

    def deployment_package_filename(self, project_dir, python_version):
        # type: (str, str) -> str
        return self._deployment_package_filename(project_dir, python_version,
                                                 prefix='appcode-')

    def _deployment_package_filename(self, project_dir, python_version,
                                     prefix=''):
        # type: (str, str, str) -> str
        h = hashlib.md5(b'')
        for filename, _ in self._iter_app_filenames(project_dir):
            with self._osutils.open(filename, 'rb') as f:
                reader = functools.partial(f.read, 1024 * 1024)
                for chunk in iter(reader, b''):
                    h.update(chunk)
        digest = h.hexdigest()
        filename = '%s%s-%s.zip' % (prefix, digest, python_version)
        deployment_package_filename = self._osutils.joinpath(
            project_dir, '.chalice', 'deployments', filename)
        return deployment_package_filename


class LayerDeploymentPackager(BaseLambdaDeploymentPackager):

    # A Lambda layer will unzip into the /opt directory instead of
    # the current working directory of the function.  This means
    # in order for our python dependencies to work we need.
    _PREFIX = 'python/lib/%s/site-packages'

    def create_deployment_package(self, project_dir, python_version):
        # type: (str, str) -> str
        msg = "Creating shared layer deployment package."
        self._ui.write("%s\n" % msg)
        logger.debug(msg)
        package_filename = self.deployment_package_filename(
            project_dir, python_version)
        self._create_output_dir_if_needed(package_filename)
        if self._osutils.file_exists(package_filename):
            self._ui.write(
                "  Reusing existing shared layer deployment package.\n")
            return package_filename
        with self._osutils.tempdir() as tmpdir:
            requirements_filepath = self._get_requirements_filename(
                project_dir)
            self._build_python_dependencies(python_version,
                                            requirements_filepath,
                                            site_packages_dir=tmpdir)
            with self._osutils.open_zip(package_filename, 'w',
                                        self._osutils.ZIP_DEFLATED) as z:
                prefix = self._PREFIX % python_version
                self._add_py_deps(z, deps_dir=tmpdir, prefix=prefix)
                self._add_vendor_files(z, self._osutils.joinpath(
                    project_dir, self._VENDOR_DIR), prefix=prefix)
        self._check_valid_package(package_filename)
        return package_filename

    def _check_valid_package(self, package_filename):
        # type: (str) -> None
        # Lambda does not allow empty deployment packages, so if there are no
        # requirements.txt deps or anything in vendor/, we need to let the
        # call know that we couldn't generate a useful deployment package
        # for them.  The caller will then need make the appropriate adjustments
        # i.e remove that LambdaLayer model from the app.
        with self._osutils.open_zip(package_filename,
                                    'r', self._osutils.ZIP_DEFLATED) as z:
            total_size = sum([f.file_size for f in z.infolist()])
            # We have to check the total archive size, Lambda will still error
            # out if you have a zip file with all empty files.  It's not enough
            # to check if the zipfile is empty.
            if not total_size > 0:
                # We want to make sure we remove any deployment packages we
                # know are invalid, we don't want them being used as cache
                # hits in subsequent create_deployment_package() requests.
                self._osutils.remove_file(package_filename)
                raise EmptyPackageError(package_filename)

    def deployment_package_filename(self, project_dir, python_version):
        # type: (str, str) -> str
        return self._deployment_package_filename(project_dir, python_version,
                                                 prefix='managed-layer-')

    def _deployment_package_filename(self, project_dir, python_version,
                                     prefix=''):
        # type: (str, str, str) -> str
        requirements_filename = self._get_requirements_filename(project_dir)
        if not self._osutils.file_exists(requirements_filename):
            contents = b''
        else:
            contents = cast(bytes, self._osutils.get_file_contents(
                requirements_filename, binary=True))
        h = hashlib.md5(contents)
        vendor_dir = self._osutils.joinpath(project_dir, self._VENDOR_DIR)
        if self._osutils.directory_exists(vendor_dir):
            self._hash_vendor_dir(vendor_dir, h)
        hash_contents = h.hexdigest()
        filename = '%s%s-%s.zip' % (prefix, hash_contents, python_version)
        deployment_package_filename = self._osutils.joinpath(
            project_dir, '.chalice', 'deployments', filename)
        return deployment_package_filename


class DependencyBuilder(object):
    """Build site-packages by manually downloading and unpacking wheels.

    Pip is used to download all the dependency sdists. Then wheels that are
    compatible with lambda are downloaded. Any source packages that do not
    have a matching wheel file are built into a wheel and that file is checked
    for compatibility with the lambda python runtime environment.

    All compatible wheels that are downloaded/built this way are unpacked
    into a site-packages directory, to be included in the bundle by the
    packager.
    """
    _ADDITIONAL_COMPATIBLE_PLATFORM = {'any', 'linux_x86_64'}
    _MANYLINUX_LEGACY_MAP = {
        'manylinux1_x86_64': 'manylinux_2_5_x86_64',
        'manylinux2010_x86_64': 'manylinux_2_12_x86_64',
        'manylinux2014_x86_64': 'manylinux_2_17_x86_64',
    }

    # Mapping of abi to glibc version in Lambda runtime.
    _RUNTIME_GLIBC = {
        'cp27mu': (2, 17),
        'cp36m': (2, 17),
        'cp37m': (2, 17),
        'cp38': (2, 26),
    }
    # Fallback version if we're on an unknown python version
    # not in _RUNTIME_GLIBC.
    # Unlikely to hit this case.
    _DEFAULT_GLIBC = (2, 17)

    _COMPATIBLE_PACKAGE_WHITELIST = {
        'sqlalchemy',
        'pyyaml',
        'pyrsistent',
    }

    def __init__(self, osutils, pip_runner=None):
        # type: (OSUtils, Optional[PipRunner]) -> None
        self._osutils = osutils
        if pip_runner is None:
            pip_runner = PipRunner(SubprocessPip(osutils))
        self._pip = pip_runner

    def _is_compatible_wheel_filename(self, expected_abi, filename):
        # type: (str, str) -> bool
        wheel = filename[:-4]
        all_compatibility_tags = self._iter_all_compatibility_tags(wheel)
        for implementation, abi, platform in all_compatibility_tags:
            # Verify platform is compatible
            if not self._is_compatible_platform_tag(expected_abi, platform):
                continue
            # Verify that the ABI is compatible with lambda. Either none or the
            # correct type for the python version cp27mu for py27 and cp36m for
            # py36.
            if abi == 'none':
                return True
            prefix_version = implementation[:3]
            expected_abis = [expected_abi]
            if prefix_version == 'cp3':
                # Deploying python 3 function which means we can accept the
                # version specific abi, or we can accept the CPython 3 stable
                # ABI of 'abi3'.
                expected_abis.append('abi3')
            if abi in expected_abis:
                return True
        return False

    def _is_compatible_platform_tag(self, expected_abi, platform):
        # type: (str, str) -> bool
        # From PEP 600, the new manylinux tag is
        # manylinux_${GLIBCMAJOR}_${GLIBCMINOR}_${ARCH}
        # e.g. manylinux_2_17_x86_64.
        # To check if the wheel is compatible, we first need to map any of the
        # legacy manylinux formats to the new perennial format.
        # Then we verify that the glibc version is compatible with the version
        # on the Lambda runtime (from _RUNTIME_GLIBC).
        if platform in self._ADDITIONAL_COMPATIBLE_PLATFORM:
            logger.debug("Found compatible platform tag: %s", platform)
            return True
        elif platform.startswith('manylinux'):
            # This is roughly based on the "Package Installers" section from
            # PEP 600.
            perennial_tag = self._MANYLINUX_LEGACY_MAP.get(platform, platform)
            m = re.match("manylinux_([0-9]+)_([0-9]+)_(.*)", perennial_tag)
            if m is None:
                return False
            tag_major, tag_minor = [int(x) for x in m.groups()[:2]]
            runtime_major, runtime_minor = self._RUNTIME_GLIBC.get(
                expected_abi, self._DEFAULT_GLIBC)
            if (tag_major, tag_minor) <= (runtime_major, runtime_minor):
                logger.debug(
                    "Tag glibc (%s, %s) is compatible with "
                    "runtime glibc (%s, %s)",
                    tag_major, tag_minor, runtime_major, runtime_minor)
                return True
        return False

    def _iter_all_compatibility_tags(self, wheel):
        # type: (str) -> Iterator[Tuple[str, str, str]]
        # From PEP 425, section "Compressed Tag Sets"
        #
        # "To allow for compact filenames of bdists that work with more than
        # one compatibility tag triple, each tag in a filename can instead be a
        # '.'-separated, sorted, set of tags."
        #
        # So this means that we have to iterate over all the possible
        # compatibility tag tuples and check if the wheel is compatible.
        # We just need any of the combinations to match for us to consider the
        # wheel compatible.
        implementation_tag, abi_tag, platform_tag = wheel.split('-')[-3:]
        for implementation in implementation_tag.split('.'):
            for abi in abi_tag.split('.'):
                for platform in platform_tag.split('.'):
                    yield (implementation, abi, platform)

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
        # type: (str, str) -> Set[Package]
        # Download dependencies prefering wheel files but falling back to
        # raw source dependences to get the transitive closure over
        # the dependency graph. Return the set of all package objects
        # which will serve as the master list of dependencies needed to deploy
        # successfully.
        self._pip.download_all_dependencies(requirements_filename, directory)
        deps = {Package(directory, filename) for filename
                in self._osutils.get_directory_contents(directory)}
        logger.debug("Full dependency closure: %s", deps)
        return deps

    def _download_binary_wheels(self, abi, packages, directory):
        # type: (str, Set[Package], str) -> None
        # Try to get binary wheels for each package that isn't compatible.
        logger.debug("Downloading manylinux wheels: %s", packages)
        self._pip.download_manylinux_wheels(
            abi, [pkg.identifier for pkg in packages], directory)

    def _download_sdists(self, packages, directory):
        # type: (Set[Package], str) -> None
        logger.debug("Downloading missing sdists: %s", packages)
        self._pip.download_sdists(
            [pkg.identifier for pkg in packages], directory)

    def _find_sdists(self, directory):
        # type: (str) -> Set[Package]
        packages = [Package(directory, filename) for filename
                    in self._osutils.get_directory_contents(directory)]
        sdists = {package for package in packages
                  if package.dist_type == 'sdist'}
        return sdists

    def _build_sdists(self, sdists, directory, compile_c=True):
        # type: (Set[Package], str, bool) -> None
        logger.debug("Build missing wheels from sdists "
                     "(C compiling %s): %s", compile_c, sdists)
        for sdist in sdists:
            path_to_sdist = self._osutils.joinpath(directory, sdist.filename)
            self._pip.build_wheel(path_to_sdist, directory, compile_c)

    def _categorize_wheel_files(self, abi, directory):
        # type: (str, str) -> Tuple[Set[Package], Set[Package]]
        final_wheels = [Package(directory, filename) for filename
                        in self._osutils.get_directory_contents(directory)
                        if filename.endswith('.whl')]

        compatible_wheels, incompatible_wheels = set(), set()
        for wheel in final_wheels:
            if self._is_compatible_wheel_filename(abi, wheel.filename):
                compatible_wheels.add(wheel)
            else:
                incompatible_wheels.add(wheel)
        return compatible_wheels, incompatible_wheels

    def _categorize_deps(self, abi, deps):
        # type: (str, Set[Package]) -> Any
        compatible_wheels = set()
        incompatible_wheels = set()
        sdists = set()
        for package in deps:
            if package.dist_type == 'sdist':
                sdists.add(package)
            else:
                if self._is_compatible_wheel_filename(abi, package.filename):
                    compatible_wheels.add(package)
                else:
                    incompatible_wheels.add(package)
        return sdists, compatible_wheels, incompatible_wheels

    def _download_dependencies(self, abi, directory, requirements_filename):
        # type: (str, str, str) -> Tuple[Set[Package], Set[Package]]
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
        sdists, compatible_wheels, incompatible_wheels = self._categorize_deps(
            abi, deps)
        logger.debug("Compatible wheels for Lambda: %s", compatible_wheels)
        logger.debug("Initial incompatible wheels for Lambda: %s",
                     incompatible_wheels | sdists)

        # Next we need to go through the downloaded packages and pick out any
        # dependencies that do not have a compatible wheel file downloaded.
        # For these packages we need to explicitly try to download a
        # compatible wheel file.
        missing_wheels = sdists.union(incompatible_wheels)
        self._download_binary_wheels(abi, missing_wheels, directory)

        # Re-count the wheel files after the second download pass. Anything
        # that has an sdist but not a valid wheel file is still not going to
        # work on lambda and we must now try and build the sdist into a wheel
        # file ourselves.
        # There also may be the case where no sdist was ever downloaded. For
        # example if we are on MacOS, and the package in question has a mac
        # compatible wheel file but no linux ones, we will only have an
        # incompatible wheel file and no sdist. So we need to get any missing
        # sdists before we can build them.
        compatible_wheels, incompatible_wheels = self._categorize_wheel_files(
            abi, directory)
        # The self._download_binary_wheels() can now introduce duplicate
        # entries.  For example, if we download a macOS whl at first but
        # then we're able to download a manylinux1 wheel, we'll now have
        # two wheels for the package, so we have to remove any compatible
        # wheels from our set of incompatible wheels.
        incompatible_wheels -= compatible_wheels
        missing_sdists = incompatible_wheels - sdists
        self._download_sdists(missing_sdists, directory)
        sdists = self._find_sdists(directory)
        logger.debug(
            "compatible wheels after second download pass: %s",
            compatible_wheels
        )
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
            abi, directory)
        logger.debug(
            "compatible after building wheels (C compiling): %s",
            compatible_wheels
        )
        missing_wheels = sdists - compatible_wheels
        self._build_sdists(missing_wheels, directory, compile_c=False)

        # Final pass to find the compatible wheel files and see if there are
        # any unmet dependencies left over. At this point there is nothing we
        # can do about any missing wheel files. We tried downloading a
        # compatible version directly and building from source.
        compatible_wheels, incompatible_wheels = self._categorize_wheel_files(
            abi, directory)
        logger.debug(
            "compatible after building wheels (no C compiling): %s",
            compatible_wheels
        )

        # Now there is still the case left over where the setup.py has been
        # made in such a way to be incompatible with python's setup tools,
        # causing it to lie about its compatibility. To fix this we have a
        # manually curated whitelist of packages that will work, despite
        # claiming otherwise.
        compatible_wheels, incompatible_wheels = self._apply_wheel_whitelist(
            compatible_wheels, incompatible_wheels)
        missing_wheels = deps - compatible_wheels
        logger.debug("Final compatible: %s", compatible_wheels)
        logger.debug("Final incompatible: %s", incompatible_wheels)
        logger.debug("Final missing wheels: %s", missing_wheels)
        return compatible_wheels, missing_wheels

    def _apply_wheel_whitelist(self,
                               compatible_wheels,   # type: Set[Package]
                               incompatible_wheels  # type: Set[Package]
                               ):
        # type: (...) -> Tuple[Set[Package], Set[Package]]
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
        dirnames = self._osutils.get_directory_contents(root)
        for dirname in dirnames:
            if wheel.matches_data_dir(dirname):
                data_dir = self._osutils.joinpath(root, dirname)
                break
        else:
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

    def build_site_packages(self, abi, requirements_filepath,
                            target_directory):
        # type: (str, str, str) -> None
        if self._has_at_least_one_package(requirements_filepath):
            with self._osutils.tempdir() as tempdir:
                wheels, packages_without_wheels = self._download_dependencies(
                    abi, tempdir, requirements_filepath)
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

    def matches_data_dir(self, dirname):
        # type: (str) -> bool
        """Check if a directory name matches the data_dir of a package.

        This will normalize the directory name and perform a case-insensitive
        match against the package name's data dir.

        """
        if not self.dist_type == 'wheel' or '-' not in dirname:
            return False
        name, version = dirname.split('-')[:2]
        comparison_data_dir = '%s-%s' % (self._normalize_name(name), version)
        return self.data_dir == comparison_data_dir

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

    def _normalize_name(self, name):
        # type: (str) -> str
        # Taken directly from PEP 503
        return re.sub(r"[-_.]+", "-", name).lower()


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

    def _get_pkg_info_filepath(self, package_dir):
        # type: (str) -> str
        setup_py = self._osutils.joinpath(package_dir, 'setup.py')
        script = self._SETUPTOOLS_SHIM % setup_py

        cmd = [sys.executable, '-c', script, '--no-user-cfg', 'egg_info',
               '--egg-base', 'egg-info']
        egg_info_dir = self._osutils.joinpath(package_dir, 'egg-info')
        self._osutils.makedirs(egg_info_dir)
        p = subprocess.Popen(cmd, cwd=package_dir,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        _, stderr = p.communicate()
        if p.returncode != 0:
            logger.debug("Non zero rc (%s) from the setup.py egg_info "
                         "command: %s", p.returncode, stderr)
        info_contents = self._osutils.get_directory_contents(egg_info_dir)
        if info_contents:
            pkg_info_path = self._osutils.joinpath(
                egg_info_dir, info_contents[0], 'PKG-INFO')
        else:
            # This might be a pep 517 package in which case this PKG-INFO file
            # should be available right in the top level directory of the sdist
            # in the case where the egg_info command fails.
            logger.debug("Using fallback location for PKG-INFO file in "
                         "package directory: %s", package_dir)
            pkg_info_path = self._osutils.joinpath(package_dir, 'PKG-INFO')
        if not self._osutils.file_exists(pkg_info_path):
            raise UnsupportedPackageError(self._osutils.basename(package_dir))
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
            pkg_info_filepath = self._get_pkg_info_filepath(package_dir)
            metadata = self._parse_pkg_info_file(pkg_info_filepath)
            name = metadata['Name']
            version = metadata['Version']
        return name, version


class SubprocessPip(object):
    """Wrapper around calling pip through a subprocess."""
    def __init__(self, osutils=None, import_string=None):
        # type: (Optional[OSUtils], OptStr) -> None
        if osutils is None:
            osutils = OSUtils()
        self._osutils = osutils
        if import_string is None:
            import_string = pip_import_string()
        self._import_string = import_string

    def main(self,
             args,           # type: List[str]
             env_vars=None,  # type: EnvVars
             shim=None       # type: OptStr
             ):
        # type: (...) -> Tuple[int, bytes, bytes]
        if env_vars is None:
            env_vars = self._osutils.environ()
        if shim is None:
            shim = ''
        python_exe = sys.executable
        run_pip = (
            'import sys; %s; sys.exit(main(%s))'
        ) % (self._import_string, args)
        exec_string = '%s%s' % (shim, run_pip)
        invoke_pip = [python_exe, '-c', exec_string]
        p = self._osutils.popen(invoke_pip,
                                stdout=self._osutils.pipe,
                                stderr=self._osutils.pipe,
                                env=env_vars)
        out, err = p.communicate()
        rc = p.returncode
        return rc, out, err


class PipRunner(object):
    """Wrapper around pip calls used by chalice."""

    _LINK_IS_DIR_PATTERN = ("Processing (.+?)\n"
                            "  Link is a directory,"
                            " ignoring download_dir")

    def __init__(self, pip, osutils=None):
        # type: (SubprocessPip, Optional[OSUtils]) -> None
        if osutils is None:
            osutils = OSUtils()
        self._wrapped_pip = pip
        self._osutils = osutils

    def _execute(self,
                 command,        # type: str
                 args,           # type: List[str]
                 env_vars=None,  # type: EnvVars
                 shim=None       # type: OptStr
                 ):
        # type: (...) -> Tuple[int, bytes, bytes]
        """Execute a pip command with the given arguments."""
        main_args = [command] + args
        logger.debug("calling pip %s", ' '.join(main_args))
        rc, out, err = self._wrapped_pip.main(main_args, env_vars=env_vars,
                                              shim=shim)
        return rc, out, err

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
        rc, out, err = self._execute('download', arguments)
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
            match = re.search(r"Could not find a version that satisfies the "
                              r"requirement ([^\s]+)", error)
            if match:
                package_name = match.group(1)
                raise NoSuchPackageError(str(package_name))
            raise PackageDownloadError(error)
        stdout = out.decode()
        matches = re.finditer(self._LINK_IS_DIR_PATTERN, stdout)
        for match in matches:
            wheel_package_path = str(match.group(1))
            # Looks odd we do not check on the error status of building the
            # wheel here. We can assume this is a valid package path since
            # we already passed the pip download stage. This stage would have
            # thrown a PackageDownloadError if any of the listed packages were
            # not valid.
            # If it fails the actual build step, it will have the same behavior
            # as any other package we fail to build a valid wheel for, and
            # complain at deployment time.
            self.build_wheel(wheel_package_path, directory)

    def download_manylinux_wheels(self, abi, packages, directory):
        # type: (str, List[str], str) -> None
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
                         'manylinux2014_x86_64', '--implementation', 'cp',
                         '--abi', abi, '--dest', directory, package]
            self._execute('download', arguments)

    def download_sdists(self, packages, directory):
        # type: (List[str], str) -> None
        for package in packages:
            arguments = ["--no-binary=:all:", "--no-deps", "--dest",
                         directory, package]
            self._execute('download', arguments)
