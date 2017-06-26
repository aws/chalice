import sys
import os
import pytest
import zipfile
import tarfile
import io

from chalice.utils import OSUtils
from chalice.deploy.packager import Package
from chalice.deploy.packager import PipRunner
from chalice.deploy.packager import DependencyBuilder
from chalice.deploy.packager import SdistMetadataFetcher
from chalice.deploy.packager import InvalidSourceDistributionNameError
from chalice.deploy.packager import SubprocessPip
from chalice.deploy.packager import PipError


class FakePip(object):
    def __init__(self):
        self._calls = []
        self._returns = []

    def main(self, args):
        self._calls.append(args)
        if self._returns:
            return self._returns.pop(0)
        return b'', b''

    def add_return(self, return_pair):
        self._returns.append(return_pair)

    @property
    def calls(self):
        return self._calls


@pytest.fixture
def pip_runner():
    pip = FakePip()
    pip_runner = PipRunner(pip)
    return pip, pip_runner


@pytest.fixture
def osutils():
    return OSUtils()


@pytest.fixture
def sdist_reader():
    return SdistMetadataFetcher()


class TestDependencyBuilder(object):
    def test_site_package_dir_is_correct(self, osutils):
        builder = DependencyBuilder(osutils)
        root = os.path.join('tmp', 'foo', 'bar')
        site_packages = builder.site_package_dir(root)
        assert site_packages == os.path.join(
            root, '.chalice', 'site-packages')


class TestPackage(object):
    def test_whl_package(self):
        filename = 'foobar-1.0-py3-none-any.whl'
        pkg = Package('', filename)
        assert pkg.dist_type == 'whl'
        assert pkg.filename == filename
        assert pkg.identifier == 'foobar==1.0'
        assert str(pkg) == 'foobar==1.0(whl)'

    def test_invalid_package(self):
        with pytest.raises(InvalidSourceDistributionNameError):
            Package('', 'foobar.jpg')

    def test_same_pkg_sdist_and_whl_collide(self, osutils, sdist_builder):
        with osutils.tempdir() as tempdir:
            sdist_builder.write_fake_sdist(tempdir, 'foobar', '1.0')
            pkgs = set()
            pkgs.add(Package('', 'foobar-1.0-py3-none-any.whl'))
            pkgs.add(Package(tempdir, 'foobar-1.0.zip'))
            assert len(pkgs) == 1

    def test_diff_pkg_sdist_and_whl_do_not_collide(self):
        pkgs = set()
        pkgs.add(Package('', 'foobar-1.0-py3-none-any.whl'))
        pkgs.add(Package('', 'badbaz-1.0-py3-none-any.whl'))
        assert len(pkgs) == 2

    def test_same_pkg_is_eq(self):
        pkg = Package('', 'foobar-1.0-py3-none-any.whl')
        assert pkg == pkg

    def test_pkg_repr(self):
        pkg = Package('', 'foobar-1.0-py3-none-any.whl')
        assert repr(pkg) == 'foobar==1.0(whl)'

    def test_whl_data_dir(self):
        pkg = Package('', 'foobar-2.0-py3-none-any.whl')
        assert pkg.data_dir == 'foobar-2.0.data'


class TestSubprocessPip(object):
    def test_can_invoke_pip(self):
        pip = SubprocessPip()
        out, err = pip.main(['--version'])
        # Simple assertion that we can execute pip and it gives us some output
        # and nothing on stderr.
        assert len(out) > 0
        assert err == b''


class TestPipRunner(object):
    def test_build_wheel(self, pip_runner):
        # Test that `pip wheel` is called with the correct params
        pip, runner = pip_runner
        whl = 'foobar-1.0-py3-none-any.whl'
        directory = 'directory'
        runner.build_wheel(whl, directory)
        assert pip.calls[0] == ['wheel', '--no-deps', '--wheel-dir',
                                directory, whl]

    def test_download_all_deps(self, pip_runner):
        # Make sure that `pip download` is called with the correct arguments
        # for getting all sdists.
        pip, runner = pip_runner
        runner.download_all_dependencies('requirements.txt', 'directory')
        assert pip.calls[0] == ['download', '-r',
                                'requirements.txt', '--dest', 'directory']

    def test_download_wheels(self, pip_runner):
        # Make sure that `pip download` is called with the correct arguments
        # for getting lambda compatible wheels.
        pip, runner = pip_runner
        packages = ['foo', 'bar', 'baz']
        runner.download_manylinux_whls(packages, 'directory')
        if sys.version_info[0] == 2:
            abi = 'cp27mu'
        else:
            abi = 'cp36m'
        expected_prefix = ['download', '--only-binary=:all:', '--no-deps',
                           '--platform', 'manylinux1_x86_64',
                           '--implementation', 'cp', '--abi', abi,
                           '--dest', 'directory']
        for i, package in enumerate(packages):
            assert pip.calls[i] == expected_prefix + [package]

    def test_download_wheels_no_wheels(self, pip_runner):
        pip, runner = pip_runner
        runner.download_manylinux_whls([], 'directory')
        assert len(pip.calls) == 0

    def test_raise_timeout_error(self, pip_runner):
        pip, runner = pip_runner
        pip.add_return((b'', b'ReadTimeoutError'))
        with pytest.raises(PipError) as einfo:
            runner.download_all_dependencies('requirements.txt', 'directory')
        assert str(einfo.value) == 'Read time out downloading dependencies.'

    def test_raise_new_connection_error(self, pip_runner):
        pip, runner = pip_runner
        pip.add_return((b'', b'NewConnectionError'))
        with pytest.raises(PipError) as einfo:
            runner.download_all_dependencies('requirements.txt', 'directory')
        assert str(einfo.value) == ('Failed to establish a new connection '
                                    'when downloading dependencies.')

    def test_raise_permission_error(self, pip_runner):
        pip, runner = pip_runner
        pip.add_return((b'', (b"PermissionError Permission denied: "
                              b"'/foo/bar/baz.tar.gz'")))
        with pytest.raises(PipError) as einfo:
            runner.download_all_dependencies('requirements.txt', 'directory')
        assert str(einfo.value) == ('Do not have permissions to write to '
                                    '/foo/bar/baz.tar.gz.')


class TestSdistMetadataFetcher(object):
    _SETUPTOOLS = 'from setuptools import setup'
    _DISTUTILS = 'from distutils.core import setup'
    _BOTH = (
        'try:\n'
        '    from setuptools import setup\n'
        'except ImportError:\n'
        '    from distutils.core import setuptools\n'
    )

    _SETUP_PY = (
        '%s\n'
        'setup(\n'
        '    name="%s",\n'
        '    version="%s"\n'
        ')\n'
    )

    def _write_fake_sdist(self, setup_py, directory, ext):
        filename = 'sdist.%s' % ext
        path = '%s/%s' % (directory, filename)
        if ext == 'zip':
            with zipfile.ZipFile(path, 'w',
                                 compression=zipfile.ZIP_DEFLATED) as z:
                z.writestr('sdist/setup.py', setup_py)
        else:
            with tarfile.open(path, 'w:gz') as tar:
                tarinfo = tarfile.TarInfo('sdist/setup.py')
                tarinfo.size = len(setup_py)
                tar.addfile(tarinfo, io.BytesIO(setup_py.encode()))
        return directory, filename

    def test_setup_tar_gz(self, osutils, sdist_reader):
        setup_py = self._SETUP_PY % (
            self._SETUPTOOLS, 'foo', '1.0'
        )
        with osutils.tempdir() as tempdir:
            directory, filename = self._write_fake_sdist(
                setup_py, tempdir, 'tar.gz')
            name, version = sdist_reader.get_package_name_and_version(
                directory, filename)
        assert name == 'foo'
        assert version == '1.0'

    def test_setup_tar_gz_hyphens_in_name(self, osutils, sdist_reader):
        # The whole reason we need to use the egg info to get the name and
        # version is that we cannot deterministically parse that information
        # from the filenames themselves. This test puts hyphens in the name
        # and version which would break a simple ``split("-")`` attempt to get
        # that information.
        setup_py = self._SETUP_PY % (
            self._SETUPTOOLS, 'foo-bar', '1.0-2b'
        )
        with osutils.tempdir() as tempdir:
            directory, filename = self._write_fake_sdist(
                setup_py, tempdir, 'tar.gz')
            name, version = sdist_reader.get_package_name_and_version(
                directory, filename)
        assert name == 'foo-bar'
        assert version == '1.0-2b'

    def test_setup_zip(self, osutils, sdist_reader):
        setup_py = self._SETUP_PY % (
            self._SETUPTOOLS, 'foo', '1.0'
        )
        with osutils.tempdir() as tempdir:
            directory, filename = self._write_fake_sdist(
                setup_py, tempdir, 'zip')
            name, version = sdist_reader.get_package_name_and_version(
                directory, filename)
        assert name == 'foo'
        assert version == '1.0'

    def test_distutil_tar_gz(self, osutils, sdist_reader):
        setup_py = self._SETUP_PY % (
            self._DISTUTILS, 'foo', '1.0'
        )
        with osutils.tempdir() as tempdir:
            directory, filename = self._write_fake_sdist(
                setup_py, tempdir, 'tar.gz')
            name, version = sdist_reader.get_package_name_and_version(
                directory, filename)
        assert name == 'foo'
        assert version == '1.0'

    def test_distutil_zip(self, osutils, sdist_reader):
        setup_py = self._SETUP_PY % (
            self._DISTUTILS, 'foo', '1.0'
        )
        with osutils.tempdir() as tempdir:
            directory, filename = self._write_fake_sdist(
                setup_py, tempdir, 'zip')
            name, version = sdist_reader.get_package_name_and_version(
                directory, filename)
        assert name == 'foo'
        assert version == '1.0'

    def test_both_tar_gz(self, osutils, sdist_reader):
        setup_py = self._SETUP_PY % (
            self._BOTH, 'foo-bar', '1.0-2b'
        )
        with osutils.tempdir() as tempdir:
            directory, filename = self._write_fake_sdist(
                setup_py, tempdir, 'tar.gz')
            name, version = sdist_reader.get_package_name_and_version(
                directory, filename)
        assert name == 'foo-bar'
        assert version == '1.0-2b'

    def test_both_zip(self, osutils, sdist_reader):
        setup_py = self._SETUP_PY % (
            self._BOTH, 'foo', '1.0'
        )
        with osutils.tempdir() as tempdir:
            directory, filename = self._write_fake_sdist(
                setup_py, tempdir, 'zip')
            name, version = sdist_reader.get_package_name_and_version(
                directory, filename)
        assert name == 'foo'
        assert version == '1.0'

    def test_bad_format(self, osutils, sdist_reader):
        setup_py = self._SETUP_PY % (
            self._BOTH, 'foo', '1.0'
        )
        with osutils.tempdir() as tempdir:
            directory, filename = self._write_fake_sdist(
                setup_py, tempdir, 'tar.gz2')
            with pytest.raises(InvalidSourceDistributionNameError):
                name, version = sdist_reader.get_package_name_and_version(
                    directory, filename)
