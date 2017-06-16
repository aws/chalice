import os
import pytest
import mock

from chalice.deploy.packager import Package, PipRunner, DependencyBuilder, \
    InvalidSourceDistributionNameError


class FakePip(object):
    def __init__(self):
        self._calls = []

    def main(self, args):
        self._calls.append(args)

    @property
    def calls(self):
        return self._calls


@pytest.fixture
def pip_runner():
    pip = FakePip()
    pip_runner = PipRunner(pip)
    return pip, pip_runner


class TestDependencyBuilder(object):
    def test_site_package_dir_is_correct(self):
        builder = DependencyBuilder(mock.Mock())
        root = os.path.join('tmp', 'foo', 'bar')
        site_packages = builder.site_package_dir(root)
        assert site_packages == os.path.join(
            root, '.chalice', 'site-packages')


class TestPackage(object):
    def test_whl_package(self):
        filename = 'foobar-1.0-py3-none-any.whl'
        pkg = Package(filename)
        assert pkg.dist_type == 'whl'
        assert pkg.filename == filename
        assert pkg.identifier == 'foobar==1.0'
        assert str(pkg) == 'foobar==1.0(whl)'

    def test_zip_package(self):
        filename = 'foobar-1.0.zip'
        pkg = Package(filename)
        assert pkg.dist_type == 'sdist'
        assert pkg.filename == filename
        assert pkg.identifier == 'foobar==1.0'
        assert str(pkg) == 'foobar==1.0(sdist)'

    def test_tar_gz_package(self):
        filename = 'foobar-1.0.tar.gz'
        pkg = Package(filename)
        assert pkg.dist_type == 'sdist'
        assert pkg.filename == filename
        assert pkg.identifier == 'foobar==1.0'
        assert str(pkg) == 'foobar==1.0(sdist)'

    def test_invalid_package(self):
        with pytest.raises(InvalidSourceDistributionNameError):
            Package('foobar.jpg')

    def test_same_pkg_sdist_and_whl_collide(self):
        pkgs = set()
        pkgs.add(Package('foobar-1.0-py3-none-any.whl'))
        pkgs.add(Package('foobar-1.0.zip'))
        assert len(pkgs) == 1

    def test_diff_pkg_sdist_and_whl_do_not_collide(self):
        pkgs = set()
        pkgs.add(Package('foobar-1.0-py3-none-any.whl'))
        pkgs.add(Package('badbaz-1.0-py3-none-any.whl'))
        assert len(pkgs) == 2

    def test_same_pkg_is_eq(self):
        pkg = Package('foobar-1.0-py3-none-any.whl')
        assert pkg == pkg


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
        assert pip.calls[0] == ['download', '--no-binary=:all:', '-r',
                                'requirements.txt', '--dest', 'directory']

    def test_download_wheels(self, pip_runner):
        # Make sure that `pip download` is called with the correct arguments
        # for getting lambda compatible wheels.
        pip, runner = pip_runner
        packages = ['foo', 'bar', 'baz']
        runner.download_manylinux_whls(packages, 'directory')
        expected_prefix = ['download', '--only-binary=:all:', '--no-deps',
                           '--platform', 'manylinux1_x86_64',
                           '--implementation', 'cp', '--dest', 'directory']
        for i, package in enumerate(packages):
            assert pip.calls[i] == expected_prefix + [package]

    def test_download_wheels_no_wheels(self, pip_runner):
        pip, runner = pip_runner
        runner.download_manylinux_whls([], 'directory')
        assert len(pip.calls) == 0
