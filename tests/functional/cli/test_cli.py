import json
import zipfile
import os
import sys

import pytest
from click.testing import CliRunner
import mock

from chalice import cli
from chalice.cli import factory
from chalice.config import Config, DeployedResources
from chalice.utils import record_deployed_values
from chalice.constants import DEFAULT_APIGATEWAY_STAGE_NAME
from chalice.logs import LogRetriever


class FakeConfig(object):
    def __init__(self, deployed_resources):
        self._deployed_resources = deployed_resources

    def deployed_resources(self, chalice_stage_name):
        return self._deployed_resources


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def mock_cli_factory():
    cli_factory = mock.Mock(spec=factory.CLIFactory)
    cli_factory.create_config_obj.return_value = Config.create(project_dir='.')
    cli_factory.create_botocore_session.return_value = mock.sentinel.Session
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


def test_does_deploy_with_default_api_gateway_stage_name(runner,
                                                         mock_cli_factory):
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


def test_can_specify_api_gateway_stage(runner, mock_cli_factory):
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


def test_can_deploy_specify_connection_timeout(runner, mock_cli_factory):
    with runner.isolated_filesystem():
        cli.create_new_project_skeleton('testproject')
        os.chdir('testproject')
        result = _run_cli_command(runner, cli.deploy,
                                  ['--connection-timeout', 100],
                                  cli_factory=mock_cli_factory)
        assert result.exit_code == 0
        mock_cli_factory.create_botocore_session.assert_called_with(
            connection_timeout=100
        )


def test_can_retrieve_url(runner, mock_cli_factory):
    deployed_values_dev = {
        "schema_version": "2.0",
        "resources": [
            {"rest_api_url": "https://dev-url/",
             "name": "rest_api",
             "resource_type": "rest_api"},
        ]
    }
    deployed_values_prod = {
        "schema_version": "2.0",
        "resources": [
            {"rest_api_url": "https://prod-url/",
             "name": "rest_api",
             "resource_type": "rest_api"},
        ]
    }
    with runner.isolated_filesystem():
        cli.create_new_project_skeleton('testproject')
        os.chdir('testproject')
        deployed_dir = os.path.join('.chalice', 'deployed')
        os.makedirs(deployed_dir)
        record_deployed_values(
            deployed_values_dev,
            os.path.join(deployed_dir, 'dev.json')
        )
        record_deployed_values(
            deployed_values_prod,
            os.path.join(deployed_dir, 'prod.json')
        )
        result = _run_cli_command(runner, cli.url, [],
                                  cli_factory=mock_cli_factory)
        assert result.exit_code == 0
        assert result.output == 'https://dev-url/\n'

        prod_result = _run_cli_command(runner, cli.url, ['--stage', 'prod'],
                                       cli_factory=mock_cli_factory)
        assert prod_result.exit_code == 0
        assert prod_result.output == 'https://prod-url/\n'


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


def test_can_extract_buildspec_yaml(runner):
    with runner.isolated_filesystem():
        cli.create_new_project_skeleton('testproject')
        os.chdir('testproject')
        result = _run_cli_command(
            runner, cli.generate_pipeline,
            ['--buildspec-file', 'buildspec.yml',
             '-i', 'python:3.6.1',
             'pipeline.json'])
        assert result.exit_code == 0, result.output
        assert os.path.isfile('buildspec.yml')
        with open('buildspec.yml') as f:
            data = f.read()
            # The contents of this file are tested elsewhere,
            # we just want a basic sanity check here.
            assert 'chalice package' in data


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


def test_can_provide_lambda_name_for_logs(runner, mock_cli_factory):
    deployed_resources = DeployedResources({
        "resources": [
            {"name": "foo",
             "lambda_arn": "arn:aws:lambda::app-dev-foo",
             "resource_type": "lambda_function"}]
    })
    mock_cli_factory.create_config_obj.return_value = FakeConfig(
        deployed_resources)
    log_retriever = mock.Mock(spec=LogRetriever)
    log_retriever.retrieve_logs.return_value = []
    mock_cli_factory.create_log_retriever.return_value = log_retriever
    with runner.isolated_filesystem():
        cli.create_new_project_skeleton('testproject')
        os.chdir('testproject')
        result = _run_cli_command(
            runner, cli.logs, ['--name', 'foo'],
            cli_factory=mock_cli_factory
        )
        assert result.exit_code == 0
    log_retriever.retrieve_logs.assert_called_with(
        include_lambda_messages=False, max_entries=None)
    mock_cli_factory.create_log_retriever.assert_called_with(
        mock.sentinel.Session, 'arn:aws:lambda::app-dev-foo'
    )
