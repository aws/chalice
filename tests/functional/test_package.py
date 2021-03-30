import os
import zipfile
import tarfile
import io
from collections import defaultdict, namedtuple

import pytest
import mock

from chalice.awsclient import TypedAWSClient
from chalice.config import Config
from chalice import Chalice
from chalice import package
from chalice.deploy.packager import PipRunner
from chalice.deploy.packager import DependencyBuilder
from chalice.deploy.packager import Package
from chalice.deploy.packager import MissingDependencyError
from chalice.deploy.packager import SubprocessPip
from chalice.deploy.packager import SDistMetadataFetcher
from chalice.deploy.packager import InvalidSourceDistributionNameError
from chalice.deploy.packager import UnsupportedPackageError
from chalice.compat import pip_no_compile_c_env_vars
from chalice.compat import pip_no_compile_c_shim
from chalice.package import PackageOptions
from chalice.utils import OSUtils


FakePipCall = namedtuple('FakePipEntry', ['args', 'env_vars', 'shim'])


def _create_app_structure(tmpdir):
    appdir = tmpdir.mkdir('app')
    appdir.join('app.py').write('# Test app')
    appdir.mkdir('.chalice')
    return appdir


def sample_app():
    app = Chalice("sample_app")

    @app.route('/')
    def index():
        return {"hello": "world"}

    return app


@pytest.fixture
def sdist_reader():
    return SDistMetadataFetcher()


@pytest.fixture
def sdist_builder():
    s = FakeSdistBuilder()
    return s


class FakeSdistBuilder(object):
    _SETUP_PY = (
        'from setuptools import setup\n'
        'setup(\n'
        '    name="%s",\n'
        '    version="%s"\n'
        ')\n'
    )

    def write_fake_sdist(self, directory, name, version):
        filename = '%s-%s.zip' % (name, version)
        path = '%s/%s' % (directory, filename)
        with zipfile.ZipFile(path, 'w',
                             compression=zipfile.ZIP_DEFLATED) as z:
            z.writestr('sdist/setup.py', self._SETUP_PY % (name, version))
        return directory, filename


class PathArgumentEndingWith(object):
    def __init__(self, filename):
        self._filename = filename

    def __eq__(self, other):
        if isinstance(other, str):
            filename = os.path.split(other)[-1]
            return self._filename == filename
        return False


class FakePip(object):
    def __init__(self):
        self._calls = defaultdict(lambda: [])
        self._call_history = []
        self._side_effects = defaultdict(lambda: [])
        self._return_tuple = (0, b'', b'')

    def main(self, args, env_vars=None, shim=None):
        cmd, args = args[0], args[1:]
        self._calls[cmd].append((args, env_vars, shim))
        try:
            side_effects = self._side_effects[cmd].pop(0)
            for side_effect in side_effects:
                self._call_history.append((
                    FakePipCall(args, env_vars, shim),
                    FakePipCall(side_effect.expected_args,
                                side_effect.expected_env_vars,
                                side_effect.expected_shim)))
                side_effect.execute(args)
        except IndexError:
            pass
        return self._return_tuple

    def set_return_tuple(self, rc, out, err):
        self._return_tuple = (rc, out, err)

    def packages_to_download(self, expected_args, packages, whl_contents=None):
        side_effects = [PipSideEffect(pkg,
                                      '--dest',
                                      expected_args,
                                      whl_contents)
                        for pkg in packages]
        self._side_effects['download'].append(side_effects)

    def wheels_to_build(self, expected_args, wheels_to_build,
                        expected_env_vars=None, expected_shim=None):
        # The SubprocessPip class handles injecting the
        # subprocess_python_base_environ into the env vars if needed,
        # so at this level of abstraction the env vars just default
        # to an empty dict if None is provided.
        if expected_env_vars is None:
            expected_env_vars = {}
        if expected_shim is None:
            expected_shim = ''
        side_effects = [PipSideEffect(pkg, '--wheel-dir', expected_args,
                                      expected_env_vars=expected_env_vars,
                                      expected_shim=expected_shim)
                        for pkg in wheels_to_build]
        self._side_effects['wheel'].append(side_effects)

    @property
    def calls(self):
        return self._calls

    def validate(self):
        for calls in self._call_history:
            actual_call, expected_call = calls
            assert actual_call.args == expected_call.args
            assert actual_call.env_vars == expected_call.env_vars
            assert actual_call.shim == expected_call.shim


class PipSideEffect(object):
    def __init__(self, filename, dirarg, expected_args, whl_contents=None,
                 expected_env_vars=None, expected_shim=None):
        self._filename = filename
        self._package_name = filename.split('-')[0]
        self._dirarg = dirarg
        self.expected_args = expected_args
        self.expected_env_vars = expected_env_vars
        self.expected_shim = expected_shim
        if whl_contents is None:
            whl_contents = ['{package_name}/placeholder']
        self._whl_contents = whl_contents

    def _build_fake_whl(self, directory, filename):
        filepath = os.path.join(directory, filename)
        if not os.path.isfile(filepath):
            package = Package(directory, filename)
            with zipfile.ZipFile(filepath, 'w') as z:
                for content_path in self._whl_contents:
                    z.writestr(content_path.format(
                        package_name=self._package_name,
                        data_dir=package.data_dir
                    ), b'')

    def _build_fake_sdist(self, filepath):
        # tar.gz is the same no reason to test it here as it is tested in
        # unit.deploy.TestSdistMetadataFetcher
        assert filepath.endswith('.zip')
        components = os.path.split(filepath)
        prefix, filename = components[:-1], components[-1]
        directory = os.path.join(*prefix)
        filename_without_ext = filename[:-4]
        pkg_name, pkg_version = filename_without_ext.split('-')
        builder = FakeSdistBuilder()
        builder.write_fake_sdist(directory, pkg_name, pkg_version)

    def execute(self, args):
        """Generate the file in the target_dir."""
        if self._dirarg:
            target_dir = None
            for i, arg in enumerate(args):
                if arg == self._dirarg:
                    target_dir = args[i+1]
            if target_dir:
                filepath = os.path.join(target_dir, self._filename)
                if filepath.endswith('.whl'):
                    self._build_fake_whl(target_dir, self._filename)
                else:
                    self._build_fake_sdist(filepath)


@pytest.fixture
def osutils():
    return OSUtils()


@pytest.fixture
def empty_env_osutils():
    class EmptyEnv(object):
        def environ(self):
            return {}
    return EmptyEnv()


@pytest.fixture
def pip_runner(empty_env_osutils):
    pip = FakePip()
    pip_runner = PipRunner(pip, osutils=empty_env_osutils)
    return pip, pip_runner


class TestDependencyBuilder(object):
    def _write_requirements_txt(self, packages, directory):
        contents = '\n'.join(packages)
        filepath = os.path.join(directory, 'requirements.txt')
        with open(filepath, 'w') as f:
            f.write(contents)

    def _make_appdir_and_dependency_builder(self, reqs, tmpdir, runner):
        appdir = str(_create_app_structure(tmpdir))
        self._write_requirements_txt(reqs, appdir)
        builder = DependencyBuilder(OSUtils(), runner)
        return appdir, builder

    def test_can_build_local_dir_as_whl(self, tmpdir, pip_runner):
        reqs = ['../foo']
        pip, runner = pip_runner
        appdir, builder = self._make_appdir_and_dependency_builder(
            reqs, tmpdir, runner)
        requirements_file = os.path.join(appdir, 'requirements.txt')
        pip.set_return_tuple(0, (b"Processing ../foo\n"
                                 b"  Link is a directory,"
                                 b" ignoring download_dir"), b'')
        pip.wheels_to_build(
            expected_args=['--no-deps', '--wheel-dir', mock.ANY, '../foo'],
            wheels_to_build=[
                'foo-1.2-cp36-none-any.whl'
            ]
        )

        site_packages = os.path.join(appdir, '.chalice.', 'site-packages')
        builder.build_site_packages('cp36m', requirements_file, site_packages)
        installed_packages = os.listdir(site_packages)

        pip.validate()
        assert ['foo'] == installed_packages

    def test_can_get_sdist_if_missing_initially(self, tmpdir, pip_runner):
        reqs = ['foo']
        pip, runner = pip_runner
        appdir, builder = self._make_appdir_and_dependency_builder(
            reqs, tmpdir, runner)
        requirements_file = os.path.join(appdir, 'requirements.txt')
        # Initial download yields  an incompatible wheel
        pip.packages_to_download(
            expected_args=['-r', requirements_file, '--dest', mock.ANY],
            packages=[
                'foo-1.2-cp36-cp36m-macosx_10_6_intel.whl'
            ]
        )
        # Secondary download for a compatible only one fails
        pip.packages_to_download(
            expected_args=[
                '--only-binary=:all:', '--no-deps', '--platform',
                'manylinux2014_x86_64', '--implementation', 'cp',
                '--abi', 'cp36m', '--dest', mock.ANY,
                'foo==1.2'
            ],
            packages=[]
        )
        # Third download for an sdist succeeds
        pip.packages_to_download(
            expected_args=[
                '--no-binary=:all:', '--no-deps', '--dest', mock.ANY,
                'foo==1.2'
            ],
            packages=[
                'foo-1.2.zip',
            ]
        )
        # Wheel successfully builds
        pip.wheels_to_build(
            expected_args=['--no-deps', '--wheel-dir', mock.ANY,
                           PathArgumentEndingWith('foo-1.2.zip')],
            wheels_to_build=[
                'foo-1.2-cp36-none-any.whl'
            ]
        )

        site_packages = os.path.join(appdir, '.chalice.', 'site-packages')
        builder.build_site_packages('cp36m', requirements_file, site_packages)
        installed_packages = os.listdir(site_packages)

        pip.validate()
        for req in reqs:
            assert req in installed_packages

    def test_can_get_whls_all_manylinux(self, tmpdir, pip_runner):
        reqs = ['foo', 'bar']
        pip, runner = pip_runner
        appdir, builder = self._make_appdir_and_dependency_builder(
            reqs, tmpdir, runner)
        requirements_file = os.path.join(appdir, 'requirements.txt')
        pip.packages_to_download(
            expected_args=['-r', requirements_file, '--dest', mock.ANY],
            packages=[
                'foo-1.2-cp36-cp36m-manylinux1_x86_64.whl',
                'bar-1.2-cp36-cp36m-manylinux1_x86_64.whl'
            ]
        )

        site_packages = os.path.join(appdir, '.chalice.', 'site-packages')
        builder.build_site_packages('cp36m', requirements_file, site_packages)
        installed_packages = os.listdir(site_packages)

        pip.validate()
        for req in reqs:
            assert req in installed_packages

    def test_can_use_abi3_whl_for_any_python3(self, tmpdir, pip_runner):
        reqs = ['foo', 'bar', 'baz', 'qux']
        pip, runner = pip_runner
        appdir, builder = self._make_appdir_and_dependency_builder(
            reqs, tmpdir, runner)
        requirements_file = os.path.join(appdir, 'requirements.txt')
        pip.packages_to_download(
            expected_args=['-r', requirements_file, '--dest', mock.ANY],
            packages=[
                'foo-1.2-cp33-abi3-manylinux1_x86_64.whl',
                'bar-1.2-cp34-abi3-manylinux1_x86_64.whl',
                'baz-1.2-cp35-abi3-manylinux1_x86_64.whl',
                'qux-1.2-cp36-abi3-manylinux1_x86_64.whl',
            ]
        )

        site_packages = os.path.join(appdir, '.chalice.', 'site-packages')
        builder.build_site_packages('cp36m', requirements_file, site_packages)
        installed_packages = os.listdir(site_packages)

        pip.validate()
        for req in reqs:
            assert req in installed_packages

    def test_can_expand_purelib_whl(self, tmpdir, pip_runner):
        reqs = ['foo']
        pip, runner = pip_runner
        appdir, builder = self._make_appdir_and_dependency_builder(
            reqs, tmpdir, runner)
        requirements_file = os.path.join(appdir, 'requirements.txt')
        pip.packages_to_download(
            expected_args=['-r', requirements_file, '--dest', mock.ANY],
            packages=[
                'foo-1.2-cp36-cp36m-manylinux1_x86_64.whl'
            ],
            whl_contents=['foo-1.2.data/purelib/foo/']
        )

        site_packages = os.path.join(appdir, '.chalice.', 'site-packages')
        builder.build_site_packages('cp36m', requirements_file, site_packages)
        installed_packages = os.listdir(site_packages)

        pip.validate()
        for req in reqs:
            assert req in installed_packages

    def test_can_normalize_dirname_for_purelib_whl(self, tmpdir, pip_runner):
        reqs = ['foo']
        pip, runner = pip_runner
        appdir, builder = self._make_appdir_and_dependency_builder(
            reqs, tmpdir, runner)
        requirements_file = os.path.join(appdir, 'requirements.txt')
        pip.packages_to_download(
            expected_args=['-r', requirements_file, '--dest', mock.ANY],
            packages=[
                'foo-1.2-cp36-cp36m-manylinux1_x86_64.whl'
            ],
            whl_contents=['Foo-1.2.data/purelib/foo/']
        )

        site_packages = os.path.join(appdir, '.chalice.', 'site-packages')
        builder.build_site_packages('cp36m', requirements_file, site_packages)
        installed_packages = os.listdir(site_packages)

        pip.validate()
        for req in reqs:
            assert req in installed_packages

    def test_can_expand_platlib_whl(self, tmpdir, pip_runner):
        reqs = ['foo']
        pip, runner = pip_runner
        appdir, builder = self._make_appdir_and_dependency_builder(
            reqs, tmpdir, runner)
        requirements_file = os.path.join(appdir, 'requirements.txt')
        pip.packages_to_download(
            expected_args=['-r', requirements_file, '--dest', mock.ANY],
            packages=[
                'foo-1.2-cp36-cp36m-manylinux1_x86_64.whl'
            ],
            whl_contents=['Foo-1.2.data/platlib/foo/']
        )

        site_packages = os.path.join(appdir, '.chalice.', 'site-packages')
        builder.build_site_packages('cp36m', requirements_file, site_packages)
        installed_packages = os.listdir(site_packages)

        pip.validate()
        for req in reqs:
            assert req in installed_packages

    def test_can_expand_platlib_and_purelib(self, tmpdir, pip_runner):
        # This wheel installs two importable libraries foo and bar, one from
        # the wheels purelib and one from its platlib.
        reqs = ['foo', 'bar']
        pip, runner = pip_runner
        appdir, builder = self._make_appdir_and_dependency_builder(
            reqs, tmpdir, runner)
        requirements_file = os.path.join(appdir, 'requirements.txt')
        pip.packages_to_download(
            expected_args=['-r', requirements_file, '--dest', mock.ANY],
            packages=[
                'foo-1.2-cp36-cp36m-manylinux1_x86_64.whl'
            ],
            whl_contents=[
                'foo-1.2.data/platlib/foo/',
                'foo-1.2.data/purelib/bar/'
            ]
        )

        site_packages = os.path.join(appdir, '.chalice.', 'site-packages')
        builder.build_site_packages('cp36m', requirements_file, site_packages)
        installed_packages = os.listdir(site_packages)

        pip.validate()
        for req in reqs:
            assert req in installed_packages

    def test_does_ignore_data(self, tmpdir, pip_runner):
        # Make sure the wheel installer does not copy the data directory
        # up to the root.
        reqs = ['foo']
        pip, runner = pip_runner
        appdir, builder = self._make_appdir_and_dependency_builder(
            reqs, tmpdir, runner)
        requirements_file = os.path.join(appdir, 'requirements.txt')
        pip.packages_to_download(
            expected_args=['-r', requirements_file, '--dest', mock.ANY],
            packages=[
                'foo-1.2-cp36-cp36m-manylinux1_x86_64.whl'
            ],
            whl_contents=[
                'foo/placeholder',
                'foo-1.2.data/data/bar/'
            ]
        )

        site_packages = os.path.join(appdir, '.chalice.', 'site-packages')
        builder.build_site_packages('cp36m', requirements_file, site_packages)
        installed_packages = os.listdir(site_packages)

        pip.validate()
        for req in reqs:
            assert req in installed_packages
        assert 'bar' not in installed_packages

    def test_does_ignore_include(self, tmpdir, pip_runner):
        # Make sure the wheel installer does not copy the includes directory
        # up to the root.
        reqs = ['foo']
        pip, runner = pip_runner
        appdir, builder = self._make_appdir_and_dependency_builder(
            reqs, tmpdir, runner)
        requirements_file = os.path.join(appdir, 'requirements.txt')
        pip.packages_to_download(
            expected_args=['-r', requirements_file, '--dest', mock.ANY],
            packages=[
                'foo-1.2-cp36-cp36m-manylinux1_x86_64.whl'
            ],
            whl_contents=[
                'foo/placeholder',
                'foo.1.2.data/includes/bar/'
            ]
        )

        site_packages = os.path.join(appdir, '.chalice.', 'site-packages')
        builder.build_site_packages('cp36m', requirements_file, site_packages)
        installed_packages = os.listdir(site_packages)

        pip.validate()
        for req in reqs:
            assert req in installed_packages
        assert 'bar' not in installed_packages

    def test_does_ignore_scripts(self, tmpdir, pip_runner):
        # Make sure the wheel isntaller does not copy the scripts directory
        # up to the root.
        reqs = ['foo']
        pip, runner = pip_runner
        appdir, builder = self._make_appdir_and_dependency_builder(
            reqs, tmpdir, runner)
        requirements_file = os.path.join(appdir, 'requirements.txt')
        pip.packages_to_download(
            expected_args=['-r', requirements_file, '--dest', mock.ANY],
            packages=[
                'foo-1.2-cp36-cp36m-manylinux1_x86_64.whl'
            ],
            whl_contents=[
                '{package_name}/placeholder',
                '{data_dir}/scripts/bar/placeholder'
            ]
        )

        site_packages = os.path.join(appdir, '.chalice.', 'site-packages')
        builder.build_site_packages('cp36m', requirements_file, site_packages)
        installed_packages = os.listdir(site_packages)

        pip.validate()
        for req in reqs:
            assert req in installed_packages
        assert 'bar' not in installed_packages

    def test_can_expand_platlib_and_platlib_and_root(self, tmpdir, pip_runner):
        # This wheel installs three import names foo, bar and baz.
        # they are from the root install directory and the platlib and purelib
        # subdirectories in the platlib.
        reqs = ['foo', 'bar', 'baz']
        pip, runner = pip_runner
        appdir, builder = self._make_appdir_and_dependency_builder(
            reqs, tmpdir, runner)
        requirements_file = os.path.join(appdir, 'requirements.txt')
        pip.packages_to_download(
            expected_args=['-r', requirements_file, '--dest', mock.ANY],
            packages=[
                'foo-1.2-cp36-cp36m-manylinux1_x86_64.whl'
            ],
            whl_contents=[
                '{package_name}/placeholder',
                '{data_dir}/platlib/bar/placeholder',
                '{data_dir}/purelib/baz/placeholder'
            ]
        )

        site_packages = os.path.join(appdir, '.chalice.', 'site-packages')
        builder.build_site_packages('cp36m', requirements_file, site_packages)
        installed_packages = os.listdir(site_packages)

        pip.validate()
        for req in reqs:
            assert req in installed_packages

    def test_can_get_whls_mixed_compat(self, tmpdir, osutils, pip_runner):
        reqs = ['foo', 'bar', 'baz']
        pip, runner = pip_runner
        appdir, builder = self._make_appdir_and_dependency_builder(
            reqs, tmpdir, runner)
        requirements_file = os.path.join(appdir, 'requirements.txt')
        pip.packages_to_download(
            expected_args=['-r', requirements_file, '--dest', mock.ANY],
            packages=[
                'foo-1.0-cp36-none-any.whl',
                'bar-1.2-cp36-cp36m-manylinux1_x86_64.whl',
                'baz-1.5-cp36-cp36m-linux_x86_64.whl'
            ]
        )

        site_packages = os.path.join(appdir, '.chalice.', 'site-packages')
        builder.build_site_packages('cp36m', requirements_file, site_packages)
        installed_packages = os.listdir(site_packages)

        pip.validate()
        for req in reqs:
            assert req in installed_packages

    def test_can_get_py27_whls(self, tmpdir, osutils, pip_runner):
        reqs = ['foo', 'bar', 'baz']
        pip, runner = pip_runner
        appdir, builder = self._make_appdir_and_dependency_builder(
            reqs, tmpdir, runner)
        requirements_file = os.path.join(appdir, 'requirements.txt')
        pip.packages_to_download(
            expected_args=['-r', requirements_file, '--dest', mock.ANY],
            packages=[
                'foo-1.0-cp27-none-any.whl',
                'bar-1.2-cp27-none-manylinux1_x86_64.whl',
                'baz-1.5-cp27-cp27mu-linux_x86_64.whl'
            ]
        )

        site_packages = os.path.join(appdir, '.chalice.', 'site-packages')
        builder.build_site_packages('cp27mu', requirements_file, site_packages)
        installed_packages = os.listdir(site_packages)

        pip.validate()
        for req in reqs:
            assert req in installed_packages

    def test_does_fail_on_invalid_local_package(self, tmpdir, osutils,
                                                pip_runner):
        reqs = ['../foo']
        pip, runner = pip_runner
        appdir, builder = self._make_appdir_and_dependency_builder(
            reqs, tmpdir, runner)
        requirements_file = os.path.join(appdir, 'requirements.txt')
        pip.set_return_tuple(0, (b"Processing ../foo\n"
                                 b"  Link is a directory,"
                                 b" ignoring download_dir"), b'')
        pip.wheels_to_build(
            expected_args=['--no-deps', '--wheel-dir', mock.ANY, '../foo'],
            wheels_to_build=[
                'foo-1.2-cp36-cp36m-macosx_10_6_intel.whl'
            ]
        )

        site_packages = os.path.join(appdir, '.chalice.', 'site-packages')
        with pytest.raises(MissingDependencyError) as e:
            builder.build_site_packages(
                'cp36m', requirements_file, site_packages)
        installed_packages = os.listdir(site_packages)
        missing_packages = list(e.value.missing)

        pip.validate()
        assert len(missing_packages) == 1
        assert missing_packages[0].identifier == 'foo==1.2'
        assert len(installed_packages) == 0

    def test_does_fail_on_narrow_py27_unicode(self, tmpdir, osutils,
                                              pip_runner):
        reqs = ['baz']
        pip, runner = pip_runner
        appdir, builder = self._make_appdir_and_dependency_builder(
            reqs, tmpdir, runner)
        requirements_file = os.path.join(appdir, 'requirements.txt')
        pip.packages_to_download(
            expected_args=['-r', requirements_file, '--dest', mock.ANY],
            packages=[
                'baz-1.5-cp27-cp27m-linux_x86_64.whl'
            ]
        )

        site_packages = os.path.join(appdir, '.chalice.', 'site-packages')
        with pytest.raises(MissingDependencyError) as e:
            builder.build_site_packages(
                'cp27mu', requirements_file, site_packages)
        installed_packages = os.listdir(site_packages)

        missing_packages = list(e.value.missing)
        pip.validate()
        assert len(missing_packages) == 1
        assert missing_packages[0].identifier == 'baz==1.5'
        assert len(installed_packages) == 0

    def test_does_fail_on_python_1_whl(self, tmpdir, osutils, pip_runner):
        reqs = ['baz']
        pip, runner = pip_runner
        appdir, builder = self._make_appdir_and_dependency_builder(
            reqs, tmpdir, runner)
        requirements_file = os.path.join(appdir, 'requirements.txt')
        pip.packages_to_download(
            expected_args=['-r', requirements_file, '--dest', mock.ANY],
            packages=[
                'baz-1.5-cp14-cp14m-linux_x86_64.whl'
            ]
        )

        site_packages = os.path.join(appdir, '.chalice.', 'site-packages')
        with pytest.raises(MissingDependencyError) as e:
            builder.build_site_packages(
                'cp36m', requirements_file, site_packages)
        installed_packages = os.listdir(site_packages)

        missing_packages = list(e.value.missing)
        pip.validate()
        assert len(missing_packages) == 1
        assert missing_packages[0].identifier == 'baz==1.5'
        assert len(installed_packages) == 0

    def test_can_replace_incompat_whl(self, tmpdir, osutils, pip_runner):
        reqs = ['foo', 'bar']
        pip, runner = pip_runner
        appdir, builder = self._make_appdir_and_dependency_builder(
            reqs, tmpdir, runner)
        requirements_file = os.path.join(appdir, 'requirements.txt')
        pip.packages_to_download(
            expected_args=['-r', requirements_file, '--dest', mock.ANY],
            packages=[
                'foo-1.0-cp36-none-any.whl',
                'bar-1.2-cp36-cp36m-macosx_10_6_intel.whl'
            ]
        )
        # Once the initial download has 1 incompatible whl file. The second,
        # more targeted download, finds manylinux1_x86_64 and downloads that.
        pip.packages_to_download(
            expected_args=[
                '--only-binary=:all:', '--no-deps', '--platform',
                'manylinux2014_x86_64', '--implementation', 'cp',
                '--abi', 'cp36m', '--dest', mock.ANY,
                'bar==1.2'
            ],
            packages=[
                'bar-1.2-cp36-cp36m-manylinux1_x86_64.whl'
            ]
        )
        site_packages = os.path.join(appdir, '.chalice.', 'site-packages')
        builder.build_site_packages('cp36m', requirements_file, site_packages)
        installed_packages = os.listdir(site_packages)

        pip.validate()
        for req in reqs:
            assert req in installed_packages

    @pytest.mark.parametrize(
        'package,package_filename', [
            # package: The name you would provide in requirements.txt
            # package_filename: The package name used in the .whl file.
            ('sqlalchemy', 'SQLAlchemy'),
            ('pyyaml', 'PyYAML'),
        ]
    )
    def test_whitelist_sqlalchemy(self, tmpdir, osutils, pip_runner,
                                  package, package_filename):
        reqs = ['%s==1.1.18' % package]
        abi = 'cp36m'
        pip, runner = pip_runner
        appdir, builder = self._make_appdir_and_dependency_builder(
            reqs, tmpdir, runner)
        requirements_file = os.path.join(appdir, 'requirements.txt')
        pip.packages_to_download(
            expected_args=['-r', requirements_file, '--dest', mock.ANY],
            packages=[
                '%s-1.1.18-cp36-cp36m-macosx_10_11_x86_64.whl'
                % package_filename
            ]
        )
        pip.packages_to_download(
            expected_args=[
                '--only-binary=:all:', '--no-deps', '--platform',
                'manylinux2014_x86_64', '--implementation', 'cp',
                '--abi', abi, '--dest', mock.ANY,
                '%s==1.1.18' % package
            ],
            packages=[
                '%s-1.1.18-cp36-cp36m-macosx_10_11_x86_64.whl'
                % package_filename
            ]
        )
        site_packages = os.path.join(appdir, '.chalice.', 'site-packages')
        builder.build_site_packages(abi, requirements_file, site_packages)
        installed_packages = os.listdir(site_packages)

        pip.validate()
        assert installed_packages == [package_filename]

    def test_can_build_sdist(self, tmpdir, osutils, pip_runner):
        reqs = ['foo', 'bar']
        pip, runner = pip_runner
        appdir, builder = self._make_appdir_and_dependency_builder(
            reqs, tmpdir, runner)
        requirements_file = os.path.join(appdir, 'requirements.txt')
        pip.packages_to_download(
            expected_args=['-r', requirements_file, '--dest', mock.ANY],
            packages=[
                'foo-1.2.zip',
                'bar-1.2-cp36-cp36m-manylinux1_x86_64.whl'
            ]
        )
        # Foo is built from and is pure python so it yields a compatible
        # wheel file.
        pip.wheels_to_build(
            expected_args=['--no-deps', '--wheel-dir', mock.ANY,
                           PathArgumentEndingWith('foo-1.2.zip')],
            wheels_to_build=[
                'foo-1.2-cp36-none-any.whl'
            ]
        )
        site_packages = os.path.join(appdir, '.chalice.', 'site-packages')
        builder.build_site_packages('cp36m', requirements_file, site_packages)
        installed_packages = os.listdir(site_packages)

        pip.validate()
        for req in reqs:
            assert req in installed_packages

    def test_build_sdist_makes_incompatible_whl(self, tmpdir, osutils,
                                                pip_runner):
        reqs = ['foo', 'bar']
        pip, runner = pip_runner
        appdir, builder = self._make_appdir_and_dependency_builder(
            reqs, tmpdir, runner)
        requirements_file = os.path.join(appdir, 'requirements.txt')
        pip.packages_to_download(
            expected_args=['-r', requirements_file, '--dest', mock.ANY],
            packages=[
                'foo-1.2.zip',
                'bar-1.2-cp36-cp36m-manylinux1_x86_64.whl'
            ]
        )
        # foo is compiled since downloading it failed to get any wheels. And
        # the second download for manylinux1_x86_64 wheels failed as well.
        # building in this case yields a platform specific wheel file that is
        # not compatible. In this case currently there is nothing that chalice
        # can do to install this package.
        pip.wheels_to_build(
            expected_args=['--no-deps', '--wheel-dir', mock.ANY,
                           PathArgumentEndingWith('foo-1.2.zip')],
            wheels_to_build=[
                'foo-1.2-cp36-cp36m-macosx_10_6_intel.whl'
            ]
        )
        site_packages = os.path.join(appdir, '.chalice.', 'site-packages')
        with pytest.raises(MissingDependencyError) as e:
            builder.build_site_packages(
                'cp36m', requirements_file, site_packages)
        installed_packages = os.listdir(site_packages)

        # bar should succeed and foo should failed.
        missing_packages = list(e.value.missing)
        pip.validate()
        assert len(missing_packages) == 1
        assert missing_packages[0].identifier == 'foo==1.2'
        assert installed_packages == ['bar']

    def test_can_build_package_with_optional_c_speedups_and_no_wheel(
            self, tmpdir, osutils, pip_runner):
        reqs = ['foo']
        pip, runner = pip_runner
        appdir, builder = self._make_appdir_and_dependency_builder(
            reqs, tmpdir, runner)
        requirements_file = os.path.join(appdir, 'requirements.txt')
        # In this scenario we are downloading a package that has no wheel files
        # at all, and optional c speedups. The initial download will yield an
        # sdist since there were no wheels.
        pip.packages_to_download(
            expected_args=['-r', requirements_file, '--dest', mock.ANY],
            packages=['foo-1.2.zip']
        )

        # Chalice should now try and build this into a wheel file. Since it has
        # optional c speedups it will build a platform dependent wheel file
        # which is not compatible with lambda.
        pip.wheels_to_build(
            expected_args=['--no-deps', '--wheel-dir', mock.ANY,
                           PathArgumentEndingWith('foo-1.2.zip')],
            wheels_to_build=[
                'foo-1.2-cp36-cp36m-macosx_10_6_intel.whl'
            ]
        )

        # Now chalice should make a last ditch effort to build the package by
        # trying once again to build the sdist, but this time it will prevent
        # c extensions from compiling by force. If the package had optional
        # c speedups (which in this scenario it did) then it will
        # successfully fall back to building a pure python wheel file.
        pip.wheels_to_build(
            expected_args=['--no-deps', '--wheel-dir', mock.ANY,
                           PathArgumentEndingWith('foo-1.2.zip')],
            expected_env_vars=pip_no_compile_c_env_vars,
            expected_shim=pip_no_compile_c_shim,
            wheels_to_build=[
                'foo-1.2-cp36-none-any.whl'
            ]
        )

        site_packages = os.path.join(appdir, '.chalice.', 'site-packages')
        builder.build_site_packages('cp36m', requirements_file, site_packages)
        installed_packages = os.listdir(site_packages)

        # Now we should have successfully built the foo package.
        pip.validate()
        assert installed_packages == ['foo']

    def test_build_into_existing_dir_with_preinstalled_packages(
            self, tmpdir, osutils, pip_runner):
        # Same test as above so we should get foo failing and bar succeeding
        # but in this test we started with a .chalice/site-packages directory
        # with both foo and bar already installed. It should still fail since
        # they may be there by happenstance, or from an incompatible version
        # of python.
        reqs = ['foo', 'bar']
        abi = 'cp36m'
        pip, runner = pip_runner
        appdir, builder = self._make_appdir_and_dependency_builder(
            reqs, tmpdir, runner)
        requirements_file = os.path.join(appdir, 'requirements.txt')
        pip.packages_to_download(
            expected_args=['-r', requirements_file, '--dest', mock.ANY],
            packages=[
                'foo-1.2.zip',
                'bar-1.2-cp36-cp36m-manylinux1_x86_64.whl'
            ]
        )
        pip.packages_to_download(
            expected_args=[
                '--only-binary=:all:', '--no-deps', '--platform',
                'manylinux2014_x86_64', '--implementation', 'cp',
                '--abi', abi, '--dest', mock.ANY,
                'foo==1.2'
            ],
            packages=[
                'foo-1.2-cp36-cp36m-macosx_10_6_intel.whl'
            ]
        )

        # Add two fake packages foo and bar that have previously been
        # installed in the site-packages directory.
        site_packages = os.path.join(appdir, '.chalice', 'site-packages')
        foo = os.path.join(site_packages, 'foo')
        os.makedirs(foo)
        bar = os.path.join(site_packages, 'bar')
        os.makedirs(bar)
        with pytest.raises(MissingDependencyError) as e:
            builder.build_site_packages(
                abi, requirements_file, site_packages)
        installed_packages = os.listdir(site_packages)

        # bar should succeed and foo should failed.
        missing_packages = list(e.value.missing)
        pip.validate()
        assert len(missing_packages) == 1
        assert missing_packages[0].identifier == 'foo==1.2'
        assert installed_packages == ['bar']


def test_can_create_app_packager_with_no_autogen(tmpdir, stubbed_session):
    appdir = _create_app_structure(tmpdir)

    outdir = tmpdir.mkdir('outdir')
    default_params = {'autogen_policy': True}
    config = Config.create(project_dir=str(appdir),
                           chalice_app=sample_app(),
                           **default_params)
    options = PackageOptions(TypedAWSClient(session=stubbed_session))
    p = package.create_app_packager(config, options)
    p.package_app(config, str(outdir), 'dev')
    # We're not concerned with the contents of the files
    # (those are tested in the unit tests), we just want to make
    # sure they're written to disk and look (mostly) right.
    contents = os.listdir(str(outdir))
    assert 'deployment.zip' in contents
    assert 'sam.json' in contents


def test_can_create_app_packager_with_yaml_extention(tmpdir, stubbed_session):
    appdir = _create_app_structure(tmpdir)

    outdir = tmpdir.mkdir('outdir')
    default_params = {'autogen_policy': True}
    extras_file = tmpdir.join('extras.yaml')
    extras_file.write("foo: bar")
    config = Config.create(project_dir=str(appdir),
                           chalice_app=sample_app(),
                           **default_params)
    options = PackageOptions(TypedAWSClient(session=stubbed_session))
    p = package.create_app_packager(config, options,
                                    merge_template=str(extras_file))

    p.package_app(config, str(outdir), 'dev')
    contents = os.listdir(str(outdir))
    assert 'deployment.zip' in contents
    assert 'sam.yaml' in contents


def test_can_specify_yaml_output(tmpdir, stubbed_session):
    appdir = _create_app_structure(tmpdir)

    outdir = tmpdir.mkdir('outdir')
    default_params = {'autogen_policy': True}
    config = Config.create(project_dir=str(appdir),
                           chalice_app=sample_app(),
                           **default_params)
    options = PackageOptions(TypedAWSClient(session=stubbed_session))
    p = package.create_app_packager(config, options, template_format='yaml')

    p.package_app(config, str(outdir), 'dev')
    contents = os.listdir(str(outdir))
    assert 'deployment.zip' in contents
    assert 'sam.yaml' in contents


def test_will_create_outdir_if_needed(tmpdir, stubbed_session):
    appdir = _create_app_structure(tmpdir)
    outdir = str(appdir.join('outdir'))
    default_params = {'autogen_policy': True}
    config = Config.create(project_dir=str(appdir),
                           chalice_app=sample_app(),
                           **default_params)
    options = PackageOptions(TypedAWSClient(session=stubbed_session))
    p = package.create_app_packager(config, options)
    p.package_app(config, str(outdir), 'dev')
    contents = os.listdir(str(outdir))
    assert 'deployment.zip' in contents
    assert 'sam.json' in contents


def test_includes_layer_package_with_sam(tmpdir, stubbed_session):
    appdir = _create_app_structure(tmpdir)
    appdir.mkdir('vendor').join('hello').write('hello\n')
    outdir = str(appdir.join('outdir'))
    default_params = {'autogen_policy': True}
    config = Config.create(project_dir=str(appdir),
                           chalice_app=sample_app(),
                           automatic_layer=True,
                           **default_params)
    options = PackageOptions(TypedAWSClient(session=stubbed_session))
    p = package.create_app_packager(config, options)
    p.package_app(config, str(outdir), 'dev')
    contents = os.listdir(str(outdir))
    assert 'deployment.zip' in contents
    assert 'layer-deployment.zip' in contents
    assert 'sam.json' in contents


def test_includes_layer_package_with_terraform(tmpdir, stubbed_session):
    appdir = _create_app_structure(tmpdir)
    appdir.mkdir('vendor').join('hello').write('hello\n')
    outdir = str(appdir.join('outdir'))
    default_params = {'autogen_policy': True}
    config = Config.create(project_dir=str(appdir),
                           chalice_app=sample_app(),
                           automatic_layer=True,
                           **default_params)
    options = PackageOptions(TypedAWSClient(session=stubbed_session))
    p = package.create_app_packager(config, options,
                                    package_format='terraform')
    p.package_app(config, str(outdir), 'dev')
    contents = os.listdir(str(outdir))
    assert 'deployment.zip' in contents
    assert 'layer-deployment.zip' in contents
    assert 'chalice.tf.json' in contents


class TestSubprocessPip(object):
    def test_can_invoke_pip(self):
        pip = SubprocessPip()
        rc, out, err = pip.main(['--version'])
        # Simple assertion that we can execute pip and it gives us some output
        # and nothing on stderr.
        print(out, err)
        assert rc == 0
        assert err == b''

    def test_does_error_code_propagate(self):
        pip = SubprocessPip()
        rc, _, err = pip.main(['badcommand'])
        assert rc != 0
        # Don't want to depend on a particular error message from pip since it
        # may change if we pin a differnet version to Chalice at some point.
        # But there should be a non-empty error message of some kind.
        assert err != b''


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
    _VALID_TAR_FORMATS = ['tar.gz', 'tar.bz2']

    def _write_fake_sdist(self, setup_py, directory, ext,
                          pkg_info_contents=None):
        filename = 'sdist.%s' % ext
        path = '%s/%s' % (directory, filename)
        if ext == 'zip':
            with zipfile.ZipFile(path, 'w',
                                 compression=zipfile.ZIP_DEFLATED) as z:
                z.writestr('sdist/setup.py', setup_py)
                if pkg_info_contents is not None:
                    z.writestr('sdist/PKG-INFO', pkg_info_contents)
        elif ext in self._VALID_TAR_FORMATS:
            compression_format = ext.split('.')[1]
            with tarfile.open(path, 'w:%s' % compression_format) as tar:
                tarinfo = tarfile.TarInfo('sdist/setup.py')
                tarinfo.size = len(setup_py)
                tar.addfile(tarinfo, io.BytesIO(setup_py.encode()))
                if pkg_info_contents is not None:
                    tarinfo = tarfile.TarInfo('sdist/PKG-INFO')
                    tarinfo.size = len(pkg_info_contents)
                    tar.addfile(tarinfo,
                                io.BytesIO(pkg_info_contents.encode()))
        else:
            open(path, 'a').close()
        filepath = os.path.join(directory, filename)
        return filepath

    def test_setup_tar_gz(self, osutils, sdist_reader):
        setup_py = self._SETUP_PY % (
            self._SETUPTOOLS, 'foo', '1.0'
        )
        with osutils.tempdir() as tempdir:
            filepath = self._write_fake_sdist(setup_py, tempdir, 'tar.gz')
            name, version = sdist_reader.get_package_name_and_version(
                filepath)
        assert name == 'foo'
        assert version == '1.0'

    def test_setup_tar_bz2(self, osutils, sdist_reader):
        setup_py = self._SETUP_PY % (
            self._SETUPTOOLS, 'foo', '1.0'
        )
        with osutils.tempdir() as tempdir:
            filepath = self._write_fake_sdist(setup_py, tempdir, 'tar.bz2')
            name, version = sdist_reader.get_package_name_and_version(
                filepath)
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
            filepath = self._write_fake_sdist(setup_py, tempdir, 'tar.gz')
            name, version = sdist_reader.get_package_name_and_version(
                filepath)
        assert name == 'foo-bar'
        assert version == '1.0-2b'

    def test_setup_zip(self, osutils, sdist_reader):
        setup_py = self._SETUP_PY % (
            self._SETUPTOOLS, 'foo', '1.0'
        )
        with osutils.tempdir() as tempdir:
            filepath = self._write_fake_sdist(setup_py, tempdir, 'zip')
            name, version = sdist_reader.get_package_name_and_version(
                filepath)
        assert name == 'foo'
        assert version == '1.0'

    def test_distutil_tar_gz(self, osutils, sdist_reader):
        setup_py = self._SETUP_PY % (
            self._DISTUTILS, 'foo', '1.0'
        )
        with osutils.tempdir() as tempdir:
            filepath = self._write_fake_sdist(setup_py, tempdir, 'tar.gz')
            name, version = sdist_reader.get_package_name_and_version(
                filepath)
        assert name == 'foo'
        assert version == '1.0'

    def test_distutil_tar_bz2(self, osutils, sdist_reader):
        setup_py = self._SETUP_PY % (
            self._DISTUTILS, 'foo', '1.0'
        )
        with osutils.tempdir() as tempdir:
            filepath = self._write_fake_sdist(setup_py, tempdir, 'tar.bz2')
            name, version = sdist_reader.get_package_name_and_version(
                filepath)
        assert name == 'foo'
        assert version == '1.0'

    def test_distutil_zip(self, osutils, sdist_reader):
        setup_py = self._SETUP_PY % (
            self._DISTUTILS, 'foo', '1.0'
        )
        with osutils.tempdir() as tempdir:
            filepath = self._write_fake_sdist(setup_py, tempdir, 'zip')
            name, version = sdist_reader.get_package_name_and_version(
                filepath)
        assert name == 'foo'
        assert version == '1.0'

    def test_both_tar_gz(self, osutils, sdist_reader):
        setup_py = self._SETUP_PY % (
            self._BOTH, 'foo-bar', '1.0-2b'
        )
        with osutils.tempdir() as tempdir:
            filepath = self._write_fake_sdist(setup_py, tempdir, 'tar.gz')
            name, version = sdist_reader.get_package_name_and_version(
                filepath)
        assert name == 'foo-bar'
        assert version == '1.0-2b'

    def test_both_tar_bz2(self, osutils, sdist_reader):
        setup_py = self._SETUP_PY % (
            self._BOTH, 'foo-bar', '1.0-2b'
        )
        with osutils.tempdir() as tempdir:
            filepath = self._write_fake_sdist(setup_py, tempdir, 'tar.bz2')
            name, version = sdist_reader.get_package_name_and_version(
                filepath)
        assert name == 'foo-bar'
        assert version == '1.0-2b'

    def test_both_zip(self, osutils, sdist_reader):
        setup_py = self._SETUP_PY % (
            self._BOTH, 'foo', '1.0'
        )
        with osutils.tempdir() as tempdir:
            filepath = self._write_fake_sdist(setup_py, tempdir, 'zip')
            name, version = sdist_reader.get_package_name_and_version(
                filepath)
        assert name == 'foo'
        assert version == '1.0'

    def test_bad_format(self, osutils, sdist_reader):
        setup_py = self._SETUP_PY % (
            self._BOTH, 'foo', '1.0'
        )
        with osutils.tempdir() as tempdir:
            filepath = self._write_fake_sdist(setup_py, tempdir, 'tar.gz2')
            with pytest.raises(InvalidSourceDistributionNameError):
                name, version = sdist_reader.get_package_name_and_version(
                    filepath)

    def test_cant_get_egg_info_filename(self, osutils, sdist_reader):
        # In this scenario the setup.py file will fail with an import
        # error so we should verify we try a fallback to look for
        # PKG-INFO.
        bad_setup_py = self._SETUP_PY % (
            'import some_build_dependency', 'foo', '1.0',
        )
        pkg_info_file = (
            'Name: foo\n'
            'Version: 1.0\n'
        )
        with osutils.tempdir() as tempdir:
            filepath = self._write_fake_sdist(bad_setup_py, tempdir,
                                              'zip', pkg_info_file)
            name, version = sdist_reader.get_package_name_and_version(
                filepath)
        assert name == 'foo'
        assert version == '1.0'

    def test_pkg_info_fallback_fails_raises_error(self, osutils, sdist_reader):
        setup_py = self._SETUP_PY % (
            'import build_time_dependency', 'foo', '1.0'
        )
        with osutils.tempdir() as tempdir:
            filepath = self._write_fake_sdist(setup_py, tempdir, 'tar.gz')
            with pytest.raises(UnsupportedPackageError):
                sdist_reader.get_package_name_and_version(filepath)


class TestPackage(object):

    def test_same_pkg_sdist_and_wheel_collide(self, osutils, sdist_builder):
        with osutils.tempdir() as tempdir:
            sdist_builder.write_fake_sdist(tempdir, 'foobar', '1.0')
            pkgs = set()
            pkgs.add(Package('', 'foobar-1.0-py3-none-any.whl'))
            pkgs.add(Package(tempdir, 'foobar-1.0.zip'))
            assert len(pkgs) == 1

    def test_ensure_sdist_name_normalized_for_comparison(self, osutils,
                                                         sdist_builder):
        with osutils.tempdir() as tempdir:
            sdist_builder.write_fake_sdist(tempdir, 'Foobar', '1.0')
            pkgs = set()
            pkgs.add(Package('', 'foobar-1.0-py3-none-any.whl'))
            pkgs.add(Package(tempdir, 'Foobar-1.0.zip'))
            assert len(pkgs) == 1

    def test_ensure_wheel_name_normalized_for_comparison(self, osutils,
                                                         sdist_builder):
        with osutils.tempdir() as tempdir:
            sdist_builder.write_fake_sdist(tempdir, 'foobar', '1.0')
            pkgs = set()
            pkgs.add(Package('', 'Foobar-1.0-py3-none-any.whl'))
            pkgs.add(Package(tempdir, 'foobar-1.0.zip'))
            assert len(pkgs) == 1
