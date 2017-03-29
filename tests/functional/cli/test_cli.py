import json
import zipfile
import os

from click.testing import CliRunner

from chalice import cli
from chalice.cli import factory


def assert_chalice_app_structure_created(dirname):
    app_contents = os.listdir(os.path.join(os.getcwd(), dirname))
    assert 'app.py' in app_contents
    assert 'requirements.txt' in app_contents
    assert '.chalice' in app_contents
    assert '.gitignore' in app_contents


def _run_cli_command(runner, function, args):
    # Handles passing in 'obj' so we can get commands
    # that use @pass_context to work properly.
    # click doesn't support this natively so we have to duplicate
    # what 'def cli(...)' is doing.
    result = runner.invoke(
        function, args, obj={'project_dir': '.', 'debug': False,
                             'factory': factory.CLIFactory('.')})
    return result


def test_create_new_project_creates_app():
    runner = CliRunner()
    with runner.isolated_filesystem():
        result = runner.invoke(cli.new_project, ['testproject'])
        assert result.exit_code == 0

        # The 'new-project' command creates a directory based on
        # the project name
        assert os.listdir(os.getcwd()) == ['testproject']
        assert_chalice_app_structure_created(dirname='testproject')


def test_create_project_with_prompted_app_name():
    runner = CliRunner()
    with runner.isolated_filesystem():
        result = runner.invoke(cli.new_project, input='testproject')
        assert result.exit_code == 0
        assert os.listdir(os.getcwd()) == ['testproject']
        assert_chalice_app_structure_created(dirname='testproject')


def test_error_raised_if_dir_already_exists():
    runner = CliRunner()
    with runner.isolated_filesystem():
        os.mkdir('testproject')
        result = runner.invoke(cli.new_project, ['testproject'])
        assert result.exit_code == 1
        assert 'Directory already exists: testproject' in result.output


def test_can_load_project_config_after_project_creation():
    runner = CliRunner()
    with runner.isolated_filesystem():
        result = runner.invoke(cli.new_project, ['testproject'])
        assert result.exit_code == 0
        config = factory.CLIFactory('testproject').load_project_config()
        assert config == {
            'version': '2.0',
            'app_name': 'testproject',
            'stages': {
                'dev': {'api_gateway_stage': u'dev'}
            }
        }


def test_default_new_project_adds_index_route():
    runner = CliRunner()
    with runner.isolated_filesystem():
        result = runner.invoke(cli.new_project, ['testproject'])
        assert result.exit_code == 0
        app = factory.CLIFactory('testproject').load_chalice_app()
        assert '/' in app.routes


def test_gen_policy_command_creates_policy():
    runner = CliRunner()
    with runner.isolated_filesystem():
        runner.invoke(cli.new_project, ['testproject'])
        os.chdir('testproject')
        result = runner.invoke(cli.cli, ['gen-policy'], obj={})
        assert result.exit_code == 0
        # The output should be valid JSON.
        parsed_policy = json.loads(result.output)
        # We don't want to validate the specific parts of the policy
        # (that's tested elsewhere), but we'll check to make sure
        # it looks like a policy document.
        assert 'Version' in parsed_policy
        assert 'Statement' in parsed_policy


def test_can_package_command():
    runner = CliRunner()
    with runner.isolated_filesystem():
        assert runner.invoke(cli.new_project, ['testproject']).exit_code == 0
        os.chdir('testproject')
        result = _run_cli_command(runner, cli.package, ['outdir'])
        assert result.exit_code == 0, result.output
        assert os.path.isdir('outdir')
        dir_contents = os.listdir('outdir')
        assert 'sam.json' in dir_contents
        assert 'deployment.zip' in dir_contents


def test_can_package_with_single_file():
    runner = CliRunner()
    with runner.isolated_filesystem():
        assert runner.invoke(cli.new_project, ['testproject']).exit_code == 0
        os.chdir('testproject')
        result = _run_cli_command(
            runner, cli.package, ['--single-file', 'package.zip'])
        assert result.exit_code == 0, result.output
        assert os.path.isfile('package.zip')
        with zipfile.ZipFile('package.zip', 'r') as f:
            assert f.namelist() == ['deployment.zip', 'sam.json']


def test_can_deploy():
    runner = CliRunner()
    with runner.isolated_filesystem():
        pass
