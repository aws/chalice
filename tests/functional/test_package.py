import os
import zipfile
import mock
from collections import defaultdict

import pytest
from chalice.config import Config
from chalice import Chalice
from chalice import package
from chalice.deploy.packager import PipRunner
from chalice.deploy.packager import DependencyBuilder
from chalice.deploy.packager import Package
from chalice.deploy.packager import MissingDependencyError
from chalice.compat import lambda_abi
from chalice.utils import OSUtils
from tests.conftest import FakeSdistBuilder


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

    def main(self, args):
        cmd, args = args[0], args[1:]
        self._calls[cmd].append(args)
        try:
            side_effects = self._side_effects[cmd].pop(0)
            for side_effect in side_effects:
                self._call_history.append((args, side_effect.expected_args))
                side_effect.execute(args)
        except IndexError:
            pass
        return 0, b''

    def packages_to_download(self, expected_args, packages,
                             whl_contents=None):
        side_effects = [PipSideEffect(pkg,
                                      '--dest',
                                      expected_args,
                                      whl_contents)
                        for pkg in packages]
        self._side_effects['download'].append(side_effects)

    def wheels_to_build(self, expected_args, wheels_to_build):
        side_effects = [PipSideEffect(pkg, '--wheel-dir', expected_args)
                        for pkg in wheels_to_build]
        self._side_effects['wheel'].append(side_effects)

    @property
    def calls(self):
        return self._calls

    def validate(self):
        for call in self._call_history:
            actual_args, expected_args = call
            assert expected_args == actual_args


class PipSideEffect(object):
    def __init__(self, filename, dirarg, expected_args, whl_contents=None):
        self._filename = filename
        self._package_name = filename.split('-')[0]
        self._dirarg = dirarg
        self.expected_args = expected_args
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
        assert filepath.endswith('zip')
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
def pip_runner():
    pip = FakePip()
    pip_runner = PipRunner(pip)
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
        builder.build_site_packages(requirements_file, site_packages)
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
        builder.build_site_packages(requirements_file, site_packages)
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
            whl_contents=['foo-1.2.data/platlib/foo/']
        )

        site_packages = os.path.join(appdir, '.chalice.', 'site-packages')
        builder.build_site_packages(requirements_file, site_packages)
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
        builder.build_site_packages(requirements_file, site_packages)
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
        builder.build_site_packages(requirements_file, site_packages)
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
        builder.build_site_packages(requirements_file, site_packages)
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
        builder.build_site_packages(requirements_file, site_packages)
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
        builder.build_site_packages(requirements_file, site_packages)
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
        builder.build_site_packages(requirements_file, site_packages)
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
        builder.build_site_packages(requirements_file, site_packages)
        installed_packages = os.listdir(site_packages)

        pip.validate()
        for req in reqs:
            assert req in installed_packages

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
            builder.build_site_packages(requirements_file, site_packages)
        installed_packages = os.listdir(site_packages)

        missing_pacakges = list(e.value.missing)
        pip.validate()
        assert len(missing_pacakges) == 1
        assert missing_pacakges[0].identifier == 'baz==1.5'
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
            builder.build_site_packages(requirements_file, site_packages)
        installed_packages = os.listdir(site_packages)

        missing_pacakges = list(e.value.missing)
        pip.validate()
        assert len(missing_pacakges) == 1
        assert missing_pacakges[0].identifier == 'baz==1.5'
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
                'manylinux1_x86_64', '--implementation', 'cp',
                '--abi', lambda_abi, '--dest', mock.ANY,
                'bar==1.2'
            ],
            packages=[
                'bar-1.2-cp36-cp36m-manylinux1_x86_64.whl'
            ]
        )
        site_packages = os.path.join(appdir, '.chalice.', 'site-packages')
        builder.build_site_packages(requirements_file, site_packages)
        installed_packages = os.listdir(site_packages)

        pip.validate()
        for req in reqs:
            assert req in installed_packages

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
        builder.build_site_packages(requirements_file, site_packages)
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
            builder.build_site_packages(requirements_file, site_packages)
        installed_packages = os.listdir(site_packages)

        # bar should succeed and foo should failed.
        missing_pacakges = list(e.value.missing)
        pip.validate()
        assert len(missing_pacakges) == 1
        assert missing_pacakges[0].identifier == 'foo==1.2'
        assert installed_packages == ['bar']

    def test_build_into_existing_dir_with_preinstalled_packages(
            self, tmpdir, osutils, pip_runner):
        # Same test as above so we should get foo failing and bar succeeding
        # but in this test we started with a .chalice/site-packages directory
        # with both foo and bar already installed. It should still fail since
        # they may be there by happenstance, or from an incompatible version
        # of python.
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
        pip.packages_to_download(
            expected_args=[
                '--only-binary=:all:', '--no-deps', '--platform',
                'manylinux1_x86_64', '--implementation', 'cp',
                '--abi', lambda_abi, '--dest', mock.ANY,
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
            builder.build_site_packages(requirements_file, site_packages)
        installed_packages = os.listdir(site_packages)

        # bar should succeed and foo should failed.
        missing_pacakges = list(e.value.missing)
        pip.validate()
        assert len(missing_pacakges) == 1
        assert missing_pacakges[0].identifier == 'foo==1.2'
        assert installed_packages == ['bar']


def test_can_create_app_packager_with_no_autogen(tmpdir):
    appdir = _create_app_structure(tmpdir)

    outdir = tmpdir.mkdir('outdir')
    config = Config.create(project_dir=str(appdir),
                           chalice_app=sample_app())
    p = package.create_app_packager(config)
    p.package_app(config, str(outdir))
    # We're not concerned with the contents of the files
    # (those are tested in the unit tests), we just want to make
    # sure they're written to disk and look (mostly) right.
    contents = os.listdir(str(outdir))
    assert 'deployment.zip' in contents
    assert 'sam.json' in contents


def test_will_create_outdir_if_needed(tmpdir):
    appdir = _create_app_structure(tmpdir)
    outdir = str(appdir.join('outdir'))
    config = Config.create(project_dir=str(appdir),
                           chalice_app=sample_app())
    p = package.create_app_packager(config)
    p.package_app(config, str(outdir))
    contents = os.listdir(str(outdir))
    assert 'deployment.zip' in contents
    assert 'sam.json' in contents
