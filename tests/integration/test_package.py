import os
import uuid
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
