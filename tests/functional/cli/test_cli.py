import json
import zipfile
import os
import sys

import pytest
from click.testing import CliRunner
import mock

from chalice import cli
from chalice.cli import factory
from chalice.deploy.deployer import Deployer
from chalice.config import Config
from chalice.utils import record_deployed_values
from chalice import local
from chalice.constants import DEFAULT_APIGATEWAY_STAGE_NAME


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def mock_deployer():
    d = mock.Mock(spec=Deployer)
    d.deploy.return_value = {}
    return d


@pytest.fixture
def mock_cli_factory(mock_deployer):
    cli_factory = mock.Mock(spec=factory.CLIFactory)
    cli_factory.create_config_obj.return_value = Config.create(project_dir='.')
    cli_factory.create_botocore_session.return_value = mock.sentinel.Session
    cli_factory.create_default_deployer.return_value = mock_deployer
    return cli_factory


def assert_chalice_app_structure_created(dirname):
    app_contents = os.listdir(os.path.join(os.getcwd(), dirname))
    assert 'app.py' in app_contents
    assert 'requirements.txt' in app_contents
    assert '.chalice' in app_contents
    assert '.gitignore' in app_contents


def _run_cli_command(runner, function, args, cli_factory=None):
    # Handles passing in 'obj' so we can get commands
    # that use @pass_context to work properly.
    # click doesn't support this natively so we have to duplicate
    # what 'def cli(...)' is doing.
    if cli_factory is None:
        cli_factory = factory.CLIFactory('.')
    result = runner.invoke(
        function, args, obj={'project_dir': '.', 'debug': False,
                             'factory': cli_factory})
    return result


def test_create_new_project_creates_app(runner):
    with runner.isolated_filesystem():
        result = runner.invoke(cli.new_project, ['testproject'])
        assert result.exit_code == 0

        # The 'new-project' command creates a directory based on
        # the project name
        assert os.listdir(os.getcwd()) == ['testproject']
        assert_chalice_app_structure_created(dirname='testproject')


def test_create_project_with_prompted_app_name(runner):
    with runner.isolated_filesystem():
        result = runner.invoke(cli.new_project, input='testproject')
        assert result.exit_code == 0
        assert os.listdir(os.getcwd()) == ['testproject']
        assert_chalice_app_structure_created(dirname='testproject')


def test_error_raised_if_dir_already_exists(runner):
    with runner.isolated_filesystem():
        os.mkdir('testproject')
        result = runner.invoke(cli.new_project, ['testproject'])
        assert result.exit_code == 1
        assert 'Directory already exists: testproject' in result.output


def test_can_load_project_config_after_project_creation(runner):
    with runner.isolated_filesystem():
        result = runner.invoke(cli.new_project, ['testproject'])
        assert result.exit_code == 0
        config = factory.CLIFactory('testproject').load_project_config()
        assert config == {
            'version': '2.0',
            'app_name': 'testproject',
            'stages': {
                'dev': {'api_gateway_stage': DEFAULT_APIGATEWAY_STAGE_NAME},
            }
        }


def test_default_new_project_adds_index_route(runner):
    with runner.isolated_filesystem():
        result = runner.invoke(cli.new_project, ['testproject'])
        assert result.exit_code == 0
        app = factory.CLIFactory('testproject').load_chalice_app()
        assert '/' in app.routes


def test_gen_policy_command_creates_policy(runner):
    with runner.isolated_filesystem():
        cli.create_new_project_skeleton('testproject')
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


def test_can_package_command(runner):
    with runner.isolated_filesystem():
        cli.create_new_project_skeleton('testproject')
        os.chdir('testproject')
        result = _run_cli_command(runner, cli.package, ['outdir'])
        assert result.exit_code == 0, result.output
        assert os.path.isdir('outdir')
        dir_contents = os.listdir('outdir')
        assert 'sam.json' in dir_contents
        assert 'deployment.zip' in dir_contents


def test_can_package_with_single_file(runner):
    with runner.isolated_filesystem():
        cli.create_new_project_skeleton('testproject')
        os.chdir('testproject')
        result = _run_cli_command(
            runner, cli.package, ['--single-file', 'package.zip'])
        assert result.exit_code == 0, result.output
        assert os.path.isfile('package.zip')
        with zipfile.ZipFile('package.zip', 'r') as f:
            assert sorted(f.namelist()) == ['deployment.zip', 'sam.json']


def test_can_deploy(runner, mock_cli_factory, mock_deployer):
    deployed_values = {
        'dev': {
            # We don't need to fill in everything here.
            'api_handler_arn': 'foo',
            'rest_api_id': 'bar',
        }
    }
    mock_deployer.deploy.return_value = deployed_values
    with runner.isolated_filesystem():
        cli.create_new_project_skeleton('testproject')
        os.chdir('testproject')
        result = _run_cli_command(runner, cli.deploy, [],
                                  cli_factory=mock_cli_factory)
        assert result.exit_code == 0
        # We should have also created the deployed JSON file.
        deployed_file = os.path.join('.chalice', 'deployed.json')
        assert os.path.isfile(deployed_file)
        with open(deployed_file) as f:
            data = json.load(f)
            assert data == deployed_values


def test_does_deploy_with_default_api_gateway_stage_name(
        runner, mock_cli_factory, mock_deployer):
    with runner.isolated_filesystem():
        cli.create_new_project_skeleton('testproject')
        os.chdir('testproject')
        # This isn't perfect as we're assuming we know how to
        # create the config_obj like the deploy() command does,
        # it should give us more confidence that the api gateway
        # stage defaults are still working.
        cli_factory = factory.CLIFactory('.')
        config = cli_factory.create_config_obj(
            chalice_stage_name='dev',
            autogen_policy=None,
            api_gateway_stage=None
        )
        assert config.api_gateway_stage == DEFAULT_APIGATEWAY_STAGE_NAME


def test_can_delete(runner, mock_cli_factory, mock_deployer):
    deployed_values = {
        'dev': {
            'api_handler_arn': 'foo',
            'rest_api_id': 'bar',
        }
    }
    mock_deployer.delete.return_value = None
    with runner.isolated_filesystem():
        cli.create_new_project_skeleton('testproject')
        os.chdir('testproject')
        deployed_file = os.path.join('.chalice', 'deployed.json')
        with open(deployed_file, 'wb') as f:
            f.write(json.dumps(deployed_values).encode('utf-8'))
        result = _run_cli_command(runner, cli.delete, [],
                                  cli_factory=mock_cli_factory)

        assert result.exit_code == 0
        with open(deployed_file) as f:
            data = json.load(f)
            assert data == {}


def test_can_specify_chalice_stage_arg(runner, mock_cli_factory,
                                       mock_deployer):
    with runner.isolated_filesystem():
        cli.create_new_project_skeleton('testproject')
        os.chdir('testproject')
        result = _run_cli_command(runner, cli.deploy, ['--stage', 'prod'],
                                  cli_factory=mock_cli_factory)
        assert result.exit_code == 0

    config = mock_cli_factory.create_config_obj.return_value
    mock_deployer.deploy.assert_called_with(config, chalice_stage_name='prod')


def test_can_specify_api_gateway_stage(runner, mock_cli_factory,
                                       mock_deployer):
    with runner.isolated_filesystem():
        cli.create_new_project_skeleton('testproject')
        os.chdir('testproject')
        result = _run_cli_command(runner, cli.deploy,
                                  ['--api-gateway-stage', 'notdev'],
                                  cli_factory=mock_cli_factory)
        assert result.exit_code == 0
        mock_cli_factory.create_config_obj.assert_called_with(
            autogen_policy=None, chalice_stage_name='dev',
            api_gateway_stage='notdev'
        )


def test_can_retrieve_url(runner, mock_cli_factory):
    deployed_values = {
        "dev": {
            "rest_api_id": "rest_api_id",
            "chalice_version": "0.7.0",
            "region": "us-west-2",
            "backend": "api",
            "api_handler_name": "helloworld-dev",
            "api_handler_arn": "arn:...",
            "api_gateway_stage": "dev-apig",
            "lambda_functions": {},
        },
        "prod": {
            "rest_api_id": "rest_api_id_prod",
            "chalice_version": "0.7.0",
            "region": "us-west-2",
            "backend": "api",
            "api_handler_name": "helloworld-dev",
            "api_handler_arn": "arn:...",
            "api_gateway_stage": "prod-apig",
            "lambda_functions": {},
        },
    }
    with runner.isolated_filesystem():
        cli.create_new_project_skeleton('testproject')
        os.chdir('testproject')
        record_deployed_values(deployed_values,
                               os.path.join('.chalice', 'deployed.json'))
        result = _run_cli_command(runner, cli.url, [],
                                  cli_factory=mock_cli_factory)
        assert result.exit_code == 0
        assert result.output == (
            'https://rest_api_id.execute-api.us-west-2.amazonaws.com'
            '/dev-apig/\n')

        prod_result = _run_cli_command(runner, cli.url, ['--stage', 'prod'],
                                       cli_factory=mock_cli_factory)
        assert prod_result.exit_code == 0
        assert prod_result.output == (
            'https://rest_api_id_prod.execute-api.us-west-2.amazonaws.com'
            '/prod-apig/\n')


def test_error_when_no_deployed_record(runner, mock_cli_factory):
    with runner.isolated_filesystem():
        cli.create_new_project_skeleton('testproject')
        os.chdir('testproject')
        result = _run_cli_command(runner, cli.url, [],
                                  cli_factory=mock_cli_factory)
        assert result.exit_code == 2
        assert 'not find' in result.output


@pytest.mark.skipif(sys.version_info[0] == 3,
                    reason=('Python Version 3 cannot create pipelines due to '
                            'CodeBuild not having a Python 3.6 image. This '
                            'mark can be removed when that image exists.'))
def test_can_generate_pipeline_for_all(runner):
    with runner.isolated_filesystem():
        cli.create_new_project_skeleton('testproject')
        os.chdir('testproject')
        result = _run_cli_command(
            runner, cli.generate_pipeline, ['pipeline.json'])
        assert result.exit_code == 0, result.output
        assert os.path.isfile('pipeline.json')
        with open('pipeline.json', 'r') as f:
            template = json.load(f)
            # The actual contents are tested in the unit
            # tests.  Just a sanity check that it looks right.
            assert "AWSTemplateFormatVersion" in template
            assert "Outputs" in template


def test_no_errors_if_override_codebuild_image(runner):
    with runner.isolated_filesystem():
        cli.create_new_project_skeleton('testproject')
        os.chdir('testproject')
        result = _run_cli_command(
            runner, cli.generate_pipeline,
            ['-i', 'python:3.6.1', 'pipeline.json'])
        assert result.exit_code == 0, result.output
        assert os.path.isfile('pipeline.json')
        with open('pipeline.json', 'r') as f:
            template = json.load(f)
            # The actual contents are tested in the unit
            # tests.  Just a sanity check that it looks right.
            image = template['Parameters']['CodeBuildImage']['Default']
            assert image == 'python:3.6.1'


def test_can_configure_github(runner):
    with runner.isolated_filesystem():
        cli.create_new_project_skeleton('testproject')
        os.chdir('testproject')
        # The -i option is provided so we don't have to skip this
        # test on python3.6
        result = _run_cli_command(
            runner, cli.generate_pipeline,
            ['--source', 'github', '-i' 'python:3.6.1', 'pipeline.json'])
        assert result.exit_code == 0, result.output
        assert os.path.isfile('pipeline.json')
        with open('pipeline.json', 'r') as f:
            template = json.load(f)
            # The template is already tested in the unit tests
            # for template generation.  We just want a basic
            # sanity check to make sure things are mapped
            # properly.
            assert 'GithubOwner' in template['Parameters']
            assert 'GithubRepoName' in template['Parameters']


def test_env_vars_set_in_local(runner, mock_cli_factory,
                               monkeypatch):
    local_server = mock.Mock(spec=local.LocalDevServer)
    mock_cli_factory.create_local_server.return_value = local_server
    mock_cli_factory.create_config_obj.return_value = Config.create(
        project_dir='.', environment_variables={'foo': 'bar'})
    actual_env = {}
    monkeypatch.setattr(os, 'environ', actual_env)
    with runner.isolated_filesystem():
        cli.create_new_project_skeleton('testproject')
        os.chdir('testproject')
        _run_cli_command(runner, cli.local, [],
                         cli_factory=mock_cli_factory)
        assert actual_env['foo'] == 'bar'


def test_can_specify_profile_for_logs(runner, mock_cli_factory):
    with runner.isolated_filesystem():
        cli.create_new_project_skeleton('testproject')
        os.chdir('testproject')
        result = _run_cli_command(
            runner, cli.logs, ['--profile', 'my-profile'],
            cli_factory=mock_cli_factory
        )
        assert result.exit_code == 0
        assert mock_cli_factory.profile == 'my-profile'
