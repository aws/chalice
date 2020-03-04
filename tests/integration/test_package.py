import os
import stat
import uuid
from zipfile import ZipFile
import hashlib
from contextlib import contextmanager

from click.testing import CliRunner
import pytest

from chalice import cli
from chalice.cli import factory
from chalice.cli import create_new_project_skeleton
from chalice.deploy.packager import NoSuchPackageError


@contextmanager
def cd(path):
    try:
        original_dir = os.getcwd()
        os.chdir(path)
        yield
    finally:
        os.chdir(original_dir)


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def app_skeleton(tmpdir, runner):
    project_name = 'deployment-integ-test'
    with cd(str(tmpdir)):
        create_new_project_skeleton(project_name, None)
    return str(tmpdir.join(project_name))


def _get_random_package_name():
    return 'foobar-%s' % str(uuid.uuid4())[:8]


class TestPackage(object):
    def assert_can_package_dependency(
            self, runner, app_skeleton, package, contents):
        req = os.path.join(app_skeleton, 'requirements.txt')
        with open(req, 'w') as f:
            f.write('%s\n' % package)
        cli_factory = factory.CLIFactory(app_skeleton)
        package_output_location = os.path.join(app_skeleton, 'pkg')
        result = runner.invoke(
            cli.package, [package_output_location],
            obj={'project_dir': app_skeleton,
                 'debug': False,
                 'factory': cli_factory})
        assert result.exit_code == 0
        assert result.output.strip() == 'Creating deployment package.'
        package_path = os.path.join(app_skeleton, 'pkg', 'deployment.zip')
        package_file = ZipFile(package_path)
        package_content = package_file.namelist()
        for content in contents:
            assert content in package_content

    def test_can_package_with_dashes_in_name(self, runner, app_skeleton):
        self.assert_can_package_dependency(
            runner,
            app_skeleton,
            'googleapis-common-protos==1.5.2',
            contents=[
                'google/api/__init__.py',
            ],
        )

    def test_can_package_simplejson(self, runner, app_skeleton):
        self.assert_can_package_dependency(
            runner,
            app_skeleton,
            'simplejson==3.17.0',
            contents=[
                'simplejson/__init__.py',
            ],
        )

    def test_can_package_sqlalchemy(self, runner, app_skeleton):
        # SQLAlchemy is used quite often with Chalice so we want to ensure
        # we can package it correctly.
        self.assert_can_package_dependency(
            runner,
            app_skeleton,
            'SQLAlchemy==1.3.13',
            contents=[
                'sqlalchemy/__init__.py',
            ],
        )

    def test_does_not_package_bad_requirements_file(
            self, runner, app_skeleton):
        req = os.path.join(app_skeleton, 'requirements.txt')
        package = _get_random_package_name()
        with open(req, 'w') as f:
            f.write('%s\n' % package)
        cli_factory = factory.CLIFactory(app_skeleton)

        # Try to build a deployment package from the bad requirements file.
        # It should fail with a NoSuchPackageError error since the package
        # should not exist.
        result = runner.invoke(
            cli.package, ['package'], obj={'project_dir': app_skeleton,
                                           'debug': False,
                                           'factory': cli_factory})
        assert result.exception is not None
        ex = result.exception
        assert isinstance(ex, NoSuchPackageError)
        assert str(ex) == 'Could not satisfy the requirement: %s' % package

    def test_packaging_requirements_keeps_same_hash(self, runner,
                                                    app_skeleton):
        req = os.path.join(app_skeleton, 'requirements.txt')
        package = 'botocore==1.12.202'
        with open(req, 'w') as f:
            f.write('%s\n' % package)
        cli_factory = factory.CLIFactory(app_skeleton)
        package_output_location = os.path.join(app_skeleton, 'pkg')
        self._run_package_cmd(package_output_location, app_skeleton,
                              cli_factory, runner)
        original_checksum = self._calculate_checksum(package_output_location)
        self._run_package_cmd(package_output_location, app_skeleton,
                              cli_factory, runner)
        new_checksum = self._calculate_checksum(package_output_location)
        assert original_checksum == new_checksum

    def test_preserves_executable_permissions(self, runner, app_skeleton):
        vendor = os.path.join(app_skeleton, 'vendor')
        os.makedirs(vendor)
        executable_file = os.path.join(vendor, 'myscript.sh')
        with open(executable_file, 'w') as f:
            f.write('#!/bin/bash\necho foo\n')
        os.chmod(executable_file, 0o755)
        cli_factory = factory.CLIFactory(app_skeleton)
        package_output_location = os.path.join(app_skeleton, 'pkg')
        self._run_package_cmd(package_output_location, app_skeleton,
                              cli_factory, runner)
        self._verify_file_is_executable(package_output_location,
                                        'myscript.sh')
        original_checksum = self._calculate_checksum(package_output_location)
        self._run_package_cmd(package_output_location, app_skeleton,
                              cli_factory, runner)
        new_checksum = self._calculate_checksum(package_output_location)
        assert original_checksum == new_checksum

    def _calculate_checksum(self, package_output_location):
        zip_filename = os.path.join(package_output_location, 'deployment.zip')
        with open(zip_filename, 'rb') as f:
            return hashlib.md5(f.read()).hexdigest()

    def _run_package_cmd(self, package_output_location, app_skeleton,
                         cli_factory, runner, expected_exit_code=0):
        result = runner.invoke(
            cli.package, [package_output_location],
            obj={'project_dir': app_skeleton,
                 'debug': False,
                 'factory': cli_factory})
        assert result.exit_code == expected_exit_code
        return result

    def _verify_file_is_executable(self, package_output_location, filename):
        zip_filename = os.path.join(package_output_location, 'deployment.zip')
        with ZipFile(zip_filename) as zip:
            zipinfo = zip.getinfo(filename)
            assert (zipinfo.external_attr >> 16) & stat.S_IXUSR
