import json
import os

from click.testing import CliRunner

from chalice import cli


def assert_chalice_app_structure_created(dirname):
    app_contents = os.listdir(os.path.join(os.getcwd(), dirname))
    assert 'app.py' in app_contents
    assert 'requirements.txt' in app_contents
    assert '.chalice' in app_contents
    assert '.gitignore' in app_contents


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
        config = cli.load_project_config('testproject')
        assert config == {'app_name': 'testproject', 'stage': 'dev'}


def test_default_new_project_adds_index_route():
    runner = CliRunner()
    with runner.isolated_filesystem():
        result = runner.invoke(cli.new_project, ['testproject'])
        assert result.exit_code == 0
        app = cli.load_chalice_app('testproject')
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
