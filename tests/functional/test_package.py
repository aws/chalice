import sys
import os
import zipfile
import contextlib
from collections import defaultdict

import pytest
from chalice.config import Config
from chalice import Chalice
from chalice import package
from chalice.deploy.packager import PipRunner, DependencyBuilder
from chalice.utils import OSUtils
from chalice.compat import StringIO
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


@contextlib.contextmanager
def consume_stdout_and_stderr():
    try:
        out, err = sys.stdout, sys.stderr
        temp_out, temp_err = StringIO(), StringIO()
        sys.stdout, sys.stderr = temp_out, temp_err
        yield temp_out, temp_err
    finally:
        sys.stdout, sys.stderr = out, err


class FakePip(object):
    def __init__(self):
        self._calls = defaultdict(lambda: [])
        self._side_effects = defaultdict(lambda: [])

    def main(self, args):
        cmd, args = args[0], args[1:]
        self._calls[cmd].append(args)
        try:
            side_effects = self._side_effects[cmd].pop(0)
            for side_effect in side_effects:
                side_effect.execute(args)
        except IndexError:
            pass

    def add_side_effect(self, cmd, side_effect):
        self._side_effects[cmd].append(side_effect)

    @property
    def calls(self):
        return self._calls


class PipSideEffect(object):
    def __init__(self, filename, dirarg='--dest', consume=True):
        self._filename = filename
        self._package_name = filename.split('-')[0]
        self._dirarg = dirarg
        self._consume = consume

    def _build_fake_whl(self, filepath):
        if not os.path.isfile(filepath):
            with zipfile.ZipFile(filepath, 'w') as z:
                z.writestr('%s/placeholder' % self._package_name, b'')

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
                    self._build_fake_whl(filepath)
                else:
                    self._build_fake_sdist(filepath)
        return self._consume


@pytest.fixture
def osutils():
    return OSUtils()


@pytest.fixture
def pip_runner():
    pip = FakePip()
    pip_runner = PipRunner(pip)
    return pip, pip_runner


class TestDependencyBuilder(object):
    def _write_requirements_txt(self, contents, directory):
        filepath = os.path.join(directory, 'requirements.txt')
        with open(filepath, 'w') as f:
            f.write(contents)

    def test_can_get_whls_all_manylinux(self, tmpdir, osutils, pip_runner):
        reqs = ['foo', 'bar']
        pip, runner = pip_runner
        pip.add_side_effect('download', [
            PipSideEffect('foo-1.2-cp36-cp36m-manylinux1_x86_64.whl'),
            PipSideEffect('bar-1.2-cp36-cp36m-manylinux1_x86_64.whl')
        ])

        appdir = str(_create_app_structure(tmpdir))
        self._write_requirements_txt('\n'.join(reqs), appdir)
        builder = DependencyBuilder(osutils, runner)
        site_packages = builder.build_site_packages(appdir)
        installed_packages = os.listdir(site_packages)
        for req in reqs:
            assert req in installed_packages

    def test_can_get_whls_mixed_compat(self, tmpdir, osutils, pip_runner):
        reqs = ['foo', 'bar', 'baz']
        pip, runner = pip_runner
        pip.add_side_effect('download', [
            PipSideEffect('foo-1.0-cp36-none-any.whl'),
            PipSideEffect('bar-1.2-cp36-cp36m-manylinux1_x86_64.whl'),
            PipSideEffect('baz-1.5-cp36-cp36m-linux_x86_64.whl')
        ])

        appdir = str(_create_app_structure(tmpdir))
        self._write_requirements_txt('\n'.join(reqs), appdir)
        builder = DependencyBuilder(osutils, runner)
        site_packages = builder.build_site_packages(appdir)
        installed_packages = os.listdir(site_packages)
        for req in reqs:
            assert req in installed_packages

    def test_can_get_py27_whls(self, tmpdir, osutils, pip_runner):
        reqs = ['foo', 'bar', 'baz']
        pip, runner = pip_runner
        pip.add_side_effect('download', [
            PipSideEffect('foo-1.0-cp27-none-any.whl'),
            PipSideEffect(
                'bar-1.2-cp27-none-manylinux1_x86_64.whl'),
            PipSideEffect('baz-1.5-cp27-cp27mu-linux_x86_64.whl')
        ])

        appdir = str(_create_app_structure(tmpdir))
        self._write_requirements_txt('\n'.join(reqs), appdir)
        builder = DependencyBuilder(osutils, runner)
        site_packages = builder.build_site_packages(appdir)
        installed_packages = os.listdir(site_packages)
        for req in reqs:
            assert req in installed_packages

    def test_does_fail_on_narrow_py27_unicode(self, tmpdir, osutils,
                                              pip_runner):
        reqs = ['baz']
        pip, runner = pip_runner
        pip.add_side_effect('download', [
            PipSideEffect('baz-1.5-cp27-cp27m-linux_x86_64.whl')
        ])

        appdir = str(_create_app_structure(tmpdir))
        self._write_requirements_txt('\n'.join(reqs), appdir)
        builder = DependencyBuilder(osutils, runner)
        with consume_stdout_and_stderr() as (out, _):
            site_packages = builder.build_site_packages(appdir)
        installed_packages = os.listdir(site_packages)
        assert len(installed_packages) == 0
        assert 'Could not install dependencies:\nbaz==1.5' in out.getvalue()

    def test_does_fail_on_python_1_whl(self, tmpdir, osutils, pip_runner):
        reqs = ['baz']
        pip, runner = pip_runner
        pip.add_side_effect('download', [
            PipSideEffect('baz-1.5-cp14-cp14m-linux_x86_64.whl')
        ])

        appdir = str(_create_app_structure(tmpdir))
        self._write_requirements_txt('\n'.join(reqs), appdir)

        builder = DependencyBuilder(osutils, runner)
        with consume_stdout_and_stderr() as (out, _):
            site_packages = builder.build_site_packages(appdir)
        installed_packages = os.listdir(site_packages)
        assert len(installed_packages) == 0
        assert 'Could not install dependencies:\nbaz==1.5' in out.getvalue()

    def test_can_get_replace_incompat_whl(self, tmpdir, osutils, pip_runner):
        reqs = ['foo', 'bar']
        pip, runner = pip_runner
        pip.add_side_effect('download', [
            PipSideEffect('foo-1.0-cp36-none-any.whl'),
            PipSideEffect('bar-1.2-cp36-cp36m-macosx_10_6_intel.whl'),
        ])
        # Once the initial download has 1 incompatible whl file. The second,
        # more targeted download, finds manylinux1_x86_64 and downloads that.
        pip.add_side_effect('download', [
            PipSideEffect('bar-1.2-cp36-cp36m-manylinux1_x86_64.whl')
        ])

        appdir = str(_create_app_structure(tmpdir))
        self._write_requirements_txt('\n'.join(reqs), appdir)
        builder = DependencyBuilder(osutils, runner)
        site_packages = builder.build_site_packages(appdir)
        installed_packages = os.listdir(site_packages)
        for req in reqs:
            assert req in installed_packages

    def test_can_build_sdist(self, tmpdir, osutils, pip_runner):
        reqs = ['foo', 'bar']
        pip, runner = pip_runner
        pip.add_side_effect('download', [
            PipSideEffect('foo-1.2.zip'),
            PipSideEffect('bar-1.2-cp36-cp36m-manylinux1_x86_64.whl')
        ])
        # Foo is built from and is pure python so it yields a compatible
        # wheel file.
        pip.add_side_effect('wheel', [
            PipSideEffect('foo-1.2-cp36-none-any.whl',
                          dirarg='--wheel-dir')
        ])

        appdir = str(_create_app_structure(tmpdir))
        self._write_requirements_txt('\n'.join(reqs), appdir)
        builder = DependencyBuilder(osutils, runner)
        site_packages = builder.build_site_packages(appdir)
        installed_packages = os.listdir(site_packages)

        for req in reqs:
            assert req in installed_packages

    def test_build_sdist_makes_incompatible_whl(self, tmpdir, osutils,
                                                pip_runner):
        reqs = ['foo', 'bar']
        pip, runner = pip_runner
        pip.add_side_effect('download', [
            PipSideEffect('foo-1.2.zip'),
            PipSideEffect('bar-1.2-cp36-cp36m-manylinux1_x86_64.whl')
        ])
        # foo is compiled since downloading it failed to get any wheels. And
        # the second download for manylinux1_x86_64 wheels failed as well.
        # building in this case yields a platform specific wheel file that is
        # not compatible. In this case currently there is nothing that chalice
        # can do to install this package.
        pip.add_side_effect('wheel', [
            PipSideEffect('foo-1.2-cp36-cp36m-macosx_10_6_intel.whl',
                          dirarg='--wheel-dir')
        ])

        appdir = str(_create_app_structure(tmpdir))
        self._write_requirements_txt('\n'.join(reqs), appdir)
        builder = DependencyBuilder(osutils, runner)
        with consume_stdout_and_stderr() as (out, _):
            site_packages = builder.build_site_packages(appdir)
        installed_packages = os.listdir(site_packages)

        # bar should succeed and foo should failed.
        assert len(installed_packages) == 1
        assert 'Could not install dependencies:\nfoo==1.2' in out.getvalue()


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
