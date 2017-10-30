import sys
import pytest

from chalice.utils import OSUtils
from chalice.compat import pip_no_compile_c_env_vars
from chalice.compat import pip_no_compile_c_shim
from chalice.deploy.packager import Package
from chalice.deploy.packager import PipRunner
from chalice.deploy.packager import InvalidSourceDistributionNameError
from chalice.deploy.packager import NoSuchPackageError
from chalice.deploy.packager import PackageDownloadError
from tests.conftest import FakePipCall


class FakePip(object):
    def __init__(self):
        self._calls = []
        self._returns = []

    def main(self, args, env_vars=None, shim=None):
        self._calls.append(FakePipCall(args, env_vars, shim))
        if self._returns:
            return self._returns.pop(0)
        # Return an rc of 0 and an empty stderr
        return 0, b''

    def add_return(self, return_pair):
        self._returns.append(return_pair)

    @property
    def calls(self):
        return self._calls


@pytest.fixture
def pip_factory():
    def create_pip_runner(osutils=None):
        pip = FakePip()
        pip_runner = PipRunner(pip, osutils=osutils)
        return pip, pip_runner
    return create_pip_runner


class CustomEnv(OSUtils):
    def __init__(self, env):
        self._env = env

    def environ(self):
        return self._env


@pytest.fixture
def osutils():
    return OSUtils()


class TestPackage(object):
    def test_can_create_package_with_custom_osutils(self, osutils):
        pkg = Package('', 'foobar-1.0-py3-none-any.whl', osutils)
        assert pkg._osutils == osutils

    def test_wheel_package(self):
        filename = 'foobar-1.0-py3-none-any.whl'
        pkg = Package('', filename)
        assert pkg.dist_type == 'wheel'
        assert pkg.filename == filename
        assert pkg.identifier == 'foobar==1.0'
        assert str(pkg) == 'foobar==1.0(wheel)'

    def test_invalid_package(self):
        with pytest.raises(InvalidSourceDistributionNameError):
            Package('', 'foobar.jpg')

    def test_diff_pkg_sdist_and_whl_do_not_collide(self):
        pkgs = set()
        pkgs.add(Package('', 'foobar-1.0-py3-none-any.whl'))
        pkgs.add(Package('', 'badbaz-1.0-py3-none-any.whl'))
        assert len(pkgs) == 2

    def test_same_pkg_is_eq(self):
        pkg = Package('', 'foobar-1.0-py3-none-any.whl')
        assert pkg == pkg

    def test_pkg_is_eq_to_similar_pkg(self):
        pure_pkg = Package('', 'foobar-1.0-py3-none-any.whl')
        plat_pkg = Package('', 'foobar-1.0-py3-py36m-manylinux1_x86_64.whl')
        assert pure_pkg == plat_pkg

    def test_pkg_is_not_equal_to_different_type(self):
        pkg = Package('', 'foobar-1.0-py3-none-any.whl')
        non_package_type = 1
        assert not (pkg == non_package_type)

    def test_pkg_repr(self):
        pkg = Package('', 'foobar-1.0-py3-none-any.whl')
        assert repr(pkg) == 'foobar==1.0(wheel)'

    def test_wheel_data_dir(self):
        pkg = Package('', 'foobar-2.0-py3-none-any.whl')
        assert pkg.data_dir == 'foobar-2.0.data'

    def test_can_read_packages_with_underscore_in_name(self):
        pkg = Package('', 'foo_bar-2.0-py3-none-any.whl')
        assert pkg.identifier == 'foo-bar==2.0'

    def test_can_read_packages_with_period_in_name(self):
        pkg = Package('', 'foo.bar-2.0-py3-none-any.whl')
        assert pkg.identifier == 'foo-bar==2.0'


class TestPipRunner(object):
    def test_does_propagate_env_vars(self, pip_factory):
        osutils = CustomEnv({'foo': 'bar'})
        pip, runner = pip_factory(osutils)
        wheel = 'foobar-1.2-py3-none-any.whl'
        directory = 'directory'
        runner.build_wheel(wheel, directory)
        call = pip.calls[0]

        assert 'foo' in call.env_vars
        assert call.env_vars['foo'] == 'bar'

    def test_build_wheel(self, pip_factory):
        # Test that `pip wheel` is called with the correct params
        pip, runner = pip_factory()
        wheel = 'foobar-1.0-py3-none-any.whl'
        directory = 'directory'
        runner.build_wheel(wheel, directory)

        assert len(pip.calls) == 1
        call = pip.calls[0]
        assert call.args == ['wheel', '--no-deps', '--wheel-dir',
                             directory, wheel]
        for compile_env_var in pip_no_compile_c_env_vars:
            assert compile_env_var not in call.env_vars
        assert call.shim == ''

    def test_build_wheel_without_c_extensions(self, pip_factory):
        # Test that `pip wheel` is called with the correct params when we
        # call it with compile_c=False. These will differ by platform.
        pip, runner = pip_factory()
        wheel = 'foobar-1.0-py3-none-any.whl'
        directory = 'directory'
        runner.build_wheel(wheel, directory, compile_c=False)

        assert len(pip.calls) == 1
        call = pip.calls[0]
        assert call.args == ['wheel', '--no-deps', '--wheel-dir',
                             directory, wheel]
        for compile_env_var in pip_no_compile_c_env_vars:
            assert compile_env_var in call.env_vars
        assert call.shim == pip_no_compile_c_shim

    def test_download_all_deps(self, pip_factory):
        # Make sure that `pip download` is called with the correct arguments
        # for getting all sdists.
        pip, runner = pip_factory()
        runner.download_all_dependencies('requirements.txt', 'directory')

        assert len(pip.calls) == 1
        call = pip.calls[0]
        assert call.args == ['download', '-r',
                             'requirements.txt', '--dest', 'directory']
        assert call.env_vars is None
        assert call.shim is None

    def test_download_wheels(self, pip_factory):
        # Make sure that `pip download` is called with the correct arguments
        # for getting lambda compatible wheels.
        pip, runner = pip_factory()
        packages = ['foo', 'bar', 'baz']
        runner.download_manylinux_wheels(packages, 'directory')
        if sys.version_info[0] == 2:
            abi = 'cp27mu'
        else:
            abi = 'cp36m'
        expected_prefix = ['download', '--only-binary=:all:', '--no-deps',
                           '--platform', 'manylinux1_x86_64',
                           '--implementation', 'cp', '--abi', abi,
                           '--dest', 'directory']
        for i, package in enumerate(packages):
            assert pip.calls[i].args == expected_prefix + [package]
            assert pip.calls[i].env_vars is None
            assert pip.calls[i].shim is None

    def test_download_wheels_no_wheels(self, pip_factory):
        pip, runner = pip_factory()
        runner.download_manylinux_wheels([], 'directory')
        assert len(pip.calls) == 0

    def test_raise_no_such_package_error(self, pip_factory):
        pip, runner = pip_factory()
        pip.add_return((1, (b'Could not find a version that satisfies the '
                            b'requirement BadPackageName ')))
        with pytest.raises(NoSuchPackageError) as einfo:
            runner.download_all_dependencies('requirements.txt', 'directory')
        assert str(einfo.value) == ('Could not satisfy the requirement: '
                                    'BadPackageName')

    def test_raise_other_unknown_error_during_downloads(self, pip_factory):
        pip, runner = pip_factory()
        pip.add_return((1, b'SomeNetworkingError: Details here.'))
        with pytest.raises(PackageDownloadError) as einfo:
            runner.download_all_dependencies('requirements.txt', 'directory')
        assert str(einfo.value) == 'SomeNetworkingError: Details here.'

    def test_inject_unknown_error_if_no_stderr(self, pip_factory):
        pip, runner = pip_factory()
        pip.add_return((1, None))
        with pytest.raises(PackageDownloadError) as einfo:
            runner.download_all_dependencies('requirements.txt', 'directory')
        assert str(einfo.value) == 'Unknown error'
