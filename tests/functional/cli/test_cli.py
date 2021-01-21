import json
import zipfile
import os
import sys
import re

import pytest
from click.testing import CliRunner
import mock
from botocore.exceptions import ClientError

from chalice import cli
from chalice.cli import factory
from chalice.cli import newproj
from chalice.config import Config, DeployedResources
from chalice.utils import record_deployed_values
from chalice.utils import PipeReader
from chalice.constants import DEFAULT_APIGATEWAY_STAGE_NAME
from chalice.logs import LogRetriever, LogRetrieveOptions
from chalice.invoke import LambdaInvokeHandler
from chalice.invoke import UnhandledLambdaError
from chalice.awsclient import ReadTimeout
from chalice.deploy.validate import ExperimentalFeatureError


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


def teardown_function(function):
    sys.modules.pop('app', None)


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
        result = runner.invoke(cli.new_project, ['testproject'], obj={})
        assert result.exit_code == 0

        # The 'new-project' command creates a directory based on
        # the project name
        assert os.listdir(os.getcwd()) == ['testproject']
        assert_chalice_app_structure_created(dirname='testproject')


def test_create_project_with_prompted_app_name(runner):
    with runner.isolated_filesystem():
        result = runner.invoke(
            cli.new_project, input=b'', obj={
                'prompter': lambda: {'project_name': 'testproject',
                                     'project_type': 'legacy'}
            }
        )
        print(result.stdout)
        assert result.exit_code == 0
        assert os.listdir(os.getcwd()) == ['testproject']
        assert_chalice_app_structure_created(dirname='testproject')


def test_error_raised_if_dir_already_exists(runner):
    with runner.isolated_filesystem():
        os.mkdir('testproject')
        result = runner.invoke(cli.new_project, ['testproject'], obj={})
        assert result.exit_code == 1
        assert 'Directory already exists: testproject' in result.output


def test_can_load_project_config_after_project_creation(runner):
    with runner.isolated_filesystem():
        result = runner.invoke(cli.new_project, ['testproject'], obj={})
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
        result = runner.invoke(cli.new_project, ['testproject'], obj={})
        assert result.exit_code == 0
        app = factory.CLIFactory('testproject').load_chalice_app()
        assert '/' in app.routes


def test_gen_policy_command_creates_policy(runner):
    with runner.isolated_filesystem():
        newproj.create_new_project_skeleton('testproject')
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


def test_does_fail_to_generate_swagger_if_no_rest_api(runner):
    with runner.isolated_filesystem():
        newproj.create_new_project_skeleton('testproject')
        os.chdir('testproject')
        with open('app.py', 'w') as f:
            f.write(
                'from chalice import Chalice\n'
                'app = Chalice("myapp")\n'
            )
        result = _run_cli_command(runner, cli.generate_models, [])
        assert result.exit_code == 1
        assert result.output == (
            'No REST API found to generate model from.\n'
            'Aborted!\n'
        )


def test_can_write_swagger_model(runner):
    with runner.isolated_filesystem():
        newproj.create_new_project_skeleton('testproject')
        os.chdir('testproject')
        result = _run_cli_command(runner, cli.generate_models, [])
        assert result.exit_code == 0
        model = json.loads(result.output)
        assert model == {
            "swagger": "2.0",
            "info": {
                "version": "1.0",
                "title": "testproject"
            },
            "schemes": [
                "https"
            ],
            "paths": {
                "/": {
                    "get": {
                        "consumes": [
                            "application/json"
                        ],
                        "produces": [
                            "application/json"
                        ],
                        "responses": {
                            "200": {
                                "description": "200 response",
                                "schema": {
                                    "$ref": "#/definitions/Empty"
                                }
                            }
                        },
                        "x-amazon-apigateway-integration": {
                            "responses": {
                                "default": {
                                    "statusCode": "200"
                                }
                            },
                            "uri": (
                                "arn:{partition}:apigateway:{region_name}"
                                ":lambda:path/2015-03-31/functions/"
                                "{api_handler_lambda_arn}/invocations"
                            ),
                            "passthroughBehavior": "when_no_match",
                            "httpMethod": "POST",
                            "contentHandling": "CONVERT_TO_TEXT",
                            "type": "aws_proxy"
                        }
                    }
                }
            },
            "definitions": {
                "Empty": {
                    "type": "object",
                    "title": "Empty Schema"
                }
            },
            "x-amazon-apigateway-binary-media-types": [
                "application/octet-stream",
                "application/x-tar",
                "application/zip",
                "audio/basic",
                "audio/ogg",
                "audio/mp4",
                "audio/mpeg",
                "audio/wav",
                "audio/webm",
                "image/png",
                "image/jpg",
                "image/jpeg",
                "image/gif",
                "video/ogg",
                "video/mpeg",
                "video/webm"
            ]
        }


def test_can_package_command(runner, mock_cli_factory):
    with runner.isolated_filesystem():
        newproj.create_new_project_skeleton('testproject')
        os.chdir('testproject')
        result = _run_cli_command(runner, cli.package, ['outdir'])
        assert result.exit_code == 0, result.output
        assert os.path.isdir('outdir')
        dir_contents = os.listdir('outdir')
        assert 'sam.json' in dir_contents
        assert 'deployment.zip' in dir_contents


def test_can_package_with_yaml_command(runner):
    with runner.isolated_filesystem():
        newproj.create_new_project_skeleton('testproject')
        os.chdir('testproject')
        result = _run_cli_command(runner, cli.package,
                                  ['--template-format', 'yaml', 'outdir'])
        assert result.exit_code == 0, result.output
        assert os.path.isdir('outdir')
        dir_contents = os.listdir('outdir')
        assert 'sam.yaml' in dir_contents
        assert 'deployment.zip' in dir_contents


def test_case_insensitive_template_format(runner):
    with runner.isolated_filesystem():
        newproj.create_new_project_skeleton('testproject')
        os.chdir('testproject')
        result = _run_cli_command(runner, cli.package,
                                  ['--template-format', 'YAML', 'outdir'])
        assert result.exit_code == 0, result.output
        assert os.path.isdir('outdir')
        assert 'sam.yaml' in os.listdir('outdir')


def test_can_package_with_single_file(runner):
    with runner.isolated_filesystem():
        newproj.create_new_project_skeleton('testproject')
        os.chdir('testproject')
        result = _run_cli_command(
            runner, cli.package, ['--single-file', 'package.zip'])
        assert result.exit_code == 0, result.output
        assert os.path.isfile('package.zip')
        with zipfile.ZipFile('package.zip', 'r') as f:
            assert sorted(f.namelist()) == [
                'deployment.zip', 'sam.json']


def test_package_terraform_err_with_single_file_or_merge(runner):
    with runner.isolated_filesystem():
        newproj.create_new_project_skeleton('testproject')
        os.chdir('testproject')
        result = _run_cli_command(
            runner, cli.package, ['--pkg-format', 'terraform',
                                  '--single-file', 'module'])
        assert result.exit_code == 1, result.output
        assert "Terraform format does not support" in result.output

        result = _run_cli_command(
            runner, cli.package, ['--pkg-format', 'terraform',
                                  '--merge-template', 'foo.json', 'module'])
        assert result.exit_code == 1, result.output
        assert "Terraform format does not support" in result.output


def test_debug_flag_enables_logging(runner):
    with runner.isolated_filesystem():
        newproj.create_new_project_skeleton('testproject')
        os.chdir('testproject')
        result = runner.invoke(
            cli.cli, ['--debug', 'package', 'outdir'], obj={})
        assert result.exit_code == 0
        assert re.search('[DEBUG].*Creating deployment package',
                         result.output) is not None


def test_does_deploy_with_default_api_gateway_stage_name(runner,
                                                         mock_cli_factory):
    with runner.isolated_filesystem():
        newproj.create_new_project_skeleton('testproject')
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
        newproj.create_new_project_skeleton('testproject')
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
        newproj.create_new_project_skeleton('testproject')
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
        newproj.create_new_project_skeleton('testproject')
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
        newproj.create_new_project_skeleton('testproject')
        os.chdir('testproject')
        result = _run_cli_command(runner, cli.url, [],
                                  cli_factory=mock_cli_factory)
        assert result.exit_code == 2
        assert 'not find' in result.output


@pytest.mark.skipif(sys.version_info[:2] == (3, 7),
                    reason="Cannot generate pipeline for python3.7.")
@pytest.mark.skipif(sys.version_info[:2] == (3, 8),
                    reason="Cannot generate pipeline for python3.8.")
def test_can_generate_pipeline_for_all(runner):
    with runner.isolated_filesystem():
        newproj.create_new_project_skeleton('testproject')
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
        newproj.create_new_project_skeleton('testproject')
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
        newproj.create_new_project_skeleton('testproject')
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
        newproj.create_new_project_skeleton('testproject')
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
        newproj.create_new_project_skeleton('testproject')
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
        newproj.create_new_project_skeleton('testproject')
        os.chdir('testproject')
        result = _run_cli_command(
            runner, cli.logs, ['--name', 'foo'],
            cli_factory=mock_cli_factory
        )
        assert result.exit_code == 0
    log_retriever.retrieve_logs.assert_called_with(
        LogRetrieveOptions(
            include_lambda_messages=False, max_entries=None)
    )
    mock_cli_factory.create_log_retriever.assert_called_with(
        mock.sentinel.Session, 'arn:aws:lambda::app-dev-foo', False
    )


def test_can_follow_logs_with_option(runner, mock_cli_factory):
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
        newproj.create_new_project_skeleton('testproject')
        os.chdir('testproject')
        result = _run_cli_command(
            runner, cli.logs, ['--name', 'foo', '--follow'],
            cli_factory=mock_cli_factory
        )
        assert result.exit_code == 0
    log_retriever.retrieve_logs.assert_called_with(
        LogRetrieveOptions(
            include_lambda_messages=False, max_entries=None)
    )
    mock_cli_factory.create_log_retriever.assert_called_with(
        mock.sentinel.Session, 'arn:aws:lambda::app-dev-foo', True
    )


def test_can_call_invoke(runner, mock_cli_factory, monkeypatch):
    invoke_handler = mock.Mock(spec=LambdaInvokeHandler)
    mock_cli_factory.create_lambda_invoke_handler.return_value = invoke_handler
    mock_reader = mock.Mock(spec=PipeReader)
    mock_reader.read.return_value = 'barbaz'
    mock_cli_factory.create_stdin_reader.return_value = mock_reader
    with runner.isolated_filesystem():
        newproj.create_new_project_skeleton('testproject')
        os.chdir('testproject')
        result = _run_cli_command(runner, cli.invoke, ['-n', 'foo'],
                                  cli_factory=mock_cli_factory)
        assert result.exit_code == 0
    assert invoke_handler.invoke.call_args == mock.call('barbaz')


def test_invoke_does_raise_if_service_error(runner, mock_cli_factory):
    deployed_resources = DeployedResources({"resources": []})
    mock_cli_factory.create_config_obj.return_value = FakeConfig(
        deployed_resources)
    invoke_handler = mock.Mock(spec=LambdaInvokeHandler)
    invoke_handler.invoke.side_effect = ClientError(
        {
            'Error': {
                'Code': 'LambdaError',
                'Message': 'Error message'
            }
        },
        'Invoke'
    )
    mock_cli_factory.create_lambda_invoke_handler.return_value = invoke_handler
    mock_reader = mock.Mock(spec=PipeReader)
    mock_reader.read.return_value = 'barbaz'
    mock_cli_factory.create_stdin_reader.return_value = mock_reader
    with runner.isolated_filesystem():
        newproj.create_new_project_skeleton('testproject')
        os.chdir('testproject')
        result = _run_cli_command(runner, cli.invoke, ['-n', 'foo'],
                                  cli_factory=mock_cli_factory)
        assert result.exit_code == 1
    assert invoke_handler.invoke.call_args == mock.call('barbaz')
    assert (
        "Error: got 'LambdaError' exception back from Lambda\n"
        "Error message"
    ) in result.output


def test_invoke_does_raise_if_unhandled_error(runner, mock_cli_factory):
    deployed_resources = DeployedResources({"resources": []})
    mock_cli_factory.create_config_obj.return_value = FakeConfig(
        deployed_resources)
    invoke_handler = mock.Mock(spec=LambdaInvokeHandler)
    invoke_handler.invoke.side_effect = UnhandledLambdaError('foo')
    mock_cli_factory.create_lambda_invoke_handler.return_value = invoke_handler
    mock_reader = mock.Mock(spec=PipeReader)
    mock_reader.read.return_value = 'barbaz'
    mock_cli_factory.create_stdin_reader.return_value = mock_reader
    with runner.isolated_filesystem():
        newproj.create_new_project_skeleton('testproject')
        os.chdir('testproject')
        result = _run_cli_command(runner, cli.invoke, ['-n', 'foo'],
                                  cli_factory=mock_cli_factory)
        assert result.exit_code == 1
    assert invoke_handler.invoke.call_args == mock.call('barbaz')
    assert 'Unhandled exception in Lambda function, details above.' \
        in result.output


def test_invoke_does_raise_if_read_timeout(runner, mock_cli_factory):
    mock_cli_factory.create_lambda_invoke_handler.side_effect = \
        ReadTimeout('It took too long')
    with runner.isolated_filesystem():
        newproj.create_new_project_skeleton('testproject')
        os.chdir('testproject')
        result = _run_cli_command(runner, cli.invoke, ['-n', 'foo'],
                                  cli_factory=mock_cli_factory)
        assert result.exit_code == 1
        assert 'It took too long' in result.output


def test_invoke_does_raise_if_no_function_found(runner, mock_cli_factory):
    mock_cli_factory.create_lambda_invoke_handler.side_effect = \
        factory.NoSuchFunctionError('foo')
    with runner.isolated_filesystem():
        newproj.create_new_project_skeleton('testproject')
        os.chdir('testproject')
        result = _run_cli_command(runner, cli.invoke, ['-n', 'foo'],
                                  cli_factory=mock_cli_factory)
        assert result.exit_code == 2
        assert 'foo' in result.output


def test_error_message_displayed_when_missing_feature_opt_in(runner):
    with runner.isolated_filesystem():
        newproj.create_new_project_skeleton('testproject')
        with open(os.path.join('testproject', 'app.py'), 'w') as f:
            # Rather than pick an existing experimental feature, we're
            # manually injecting a feature flag into our app.  This ensures
            # we don't have to update this test if a feature graduates
            # from trial to accepted.  The '_features_used' is a "package
            # private" var for chalice code.
            f.write(
                'from chalice import Chalice\n'
                'app = Chalice("myapp")\n'
                'app._features_used.add("MYTESTFEATURE")\n'
            )
        os.chdir('testproject')
        result = _run_cli_command(runner, cli.package, ['out'])
        assert isinstance(result.exception, ExperimentalFeatureError)
        assert 'MYTESTFEATURE' in str(result.exception)


@pytest.mark.parametrize(
    "path",
    [
        None,
        '.',
        os.getcwd,
    ],
)
def test_cli_with_absolute_path(runner, path):
    with runner.isolated_filesystem():
        if callable(path):
            path = path()
        result = runner.invoke(
            cli.cli,
            ['--project-dir', path, 'new-project', 'testproject'],
            obj={})
        assert result.exit_code == 0
        assert os.listdir(os.getcwd()) == ['testproject']
        assert_chalice_app_structure_created(dirname='testproject')


def test_can_generate_dev_plan(runner, mock_cli_factory):
    with runner.isolated_filesystem():
        newproj.create_new_project_skeleton('testproject')
        os.chdir('testproject')
        result = _run_cli_command(runner, cli.plan, [],
                                  cli_factory=mock_cli_factory)
        deployer = mock_cli_factory.create_plan_only_deployer.return_value
        call_args = deployer.deploy.call_args
        assert result.exit_code == 0
        assert isinstance(call_args[0][0], Config)
        assert call_args[1] == {'chalice_stage_name': 'dev'}


# The appgraph command actually works on py27, but due to a bug in click's
# testing (https://github.com/pallets/click/issues/848), it assumes
# stdout must be ascii.
# stdout is a cStringIO.StringIO, which doesn't accept unicode.
# See: https://docs.python.org/2/library/stringio.html#cStringIO.StringIO
@pytest.mark.skipif(sys.version_info[0] == 2,
                    reason="Click bug when writing unicode to stdout.")
def test_can_generate_appgraph(runner, mock_cli_factory):
    with runner.isolated_filesystem():
        newproj.create_new_project_skeleton('testproject')
        os.chdir('testproject')
        result = _run_cli_command(runner, cli.appgraph, [])
        assert result.exit_code == 0
        # Just sanity checking some of the output
        assert 'Application' in result.output
        assert 'RestAPI(' in result.output


def test_chalice_cli_mode_env_var_always_set(runner):
    with runner.isolated_filesystem():
        result = runner.invoke(cli.new_project, ['testproject'], obj={})
        assert result.exit_code == 0
        assert os.environ['AWS_CHALICE_CLI_MODE'] == 'true'
