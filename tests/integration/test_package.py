import os
import sys
import uuid
from zipfile import ZipFile
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
    def test_can_package_with_dashes_in_name(self, runner, app_skeleton):
        sys.modules.pop('app', None)
        req = os.path.join(app_skeleton, 'requirements.txt')
        package = 'googleapis-common-protos==1.5.2'
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
        assert 'google/api/__init__.py' in package_content

    def test_does_not_package_bad_requirements_file(
            self, runner, app_skeleton):
        sys.modules.pop('app', None)
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
