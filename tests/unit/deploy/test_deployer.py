import botocore.session
import json
import os
import socket

import pytest
import mock
from botocore.stub import Stubber
from botocore.exceptions import ClientError
from botocore.vendored.requests import ConnectionError as \
    RequestsConnectionError
from pytest import fixture

from chalice import __version__ as chalice_version
from chalice.app import Chalice
from chalice.app import CORSConfig
from chalice.awsclient import TypedAWSClient
from chalice.awsclient import ResourceDoesNotExistError
from chalice.awsclient import LambdaClientError
from chalice.awsclient import DeploymentPackageTooLargeError
from chalice.awsclient import LambdaErrorContext
from chalice.config import Config, DeployedResources
from chalice.policy import AppPolicyGenerator
from chalice.deploy.deployer import ChaliceDeploymentError
from chalice.deploy.deployer import APIGatewayDeployer
from chalice.deploy.deployer import ApplicationPolicyHandler
from chalice.deploy.deployer import Deployer
from chalice.deploy.deployer import LambdaDeployer
from chalice.deploy.deployer import NoPrompt
from chalice.deploy.deployer import validate_configuration
from chalice.deploy.deployer import validate_routes
from chalice.deploy.deployer import validate_route_content_types
from chalice.deploy.deployer import validate_python_version
from chalice.deploy.packager import LambdaDeploymentPackager


_SESSION = None


class SimpleStub(object):
    def __init__(self, stubber):
        pass


class InMemoryOSUtils(object):
    def __init__(self, filemap=None):
        if filemap is None:
            filemap = {}
        self.filemap = filemap

    def file_exists(self, filename):
        return filename in self.filemap

    def get_file_contents(self, filename, binary=True):
        return self.filemap[filename]

    def set_file_contents(self, filename, contents, binary=True):
        self.filemap[filename] = contents


class CustomConfirmPrompt():
    def __init__(self, confirm_response=False):
        self._confirm_response = confirm_response

    def confirm(self, text, default=False, abort=False):
        return self._confirm_response

    def Abort(self):
        return Exception('Aborted!')


@fixture
def stubbed_api_gateway():
    return stubbed_client('apigateway')


@fixture
def stubbed_lambda():
    return stubbed_client('lambda')


@fixture
def in_memory_osutils():
    return InMemoryOSUtils()


@fixture
def app_policy(in_memory_osutils):
    return ApplicationPolicyHandler(
        in_memory_osutils,
        AppPolicyGenerator(in_memory_osutils))


def stubbed_client(service_name):
    global _SESSION
    if _SESSION is None:
        _SESSION = botocore.session.get_session()
    client = _SESSION.create_client(service_name,
                                    region_name='us-west-2')
    stubber = Stubber(client)
    return client, stubber


@fixture
def config_obj(sample_app):
    config = Config.create(
        chalice_app=sample_app,
        stage='dev',
    )
    return config


def test_api_gateway_deployer_initial_deploy(config_obj):
    aws_client = mock.Mock(spec=TypedAWSClient, region_name='us-west-2')

    # The rest_api_id does not exist which will trigger
    # the initial import
    aws_client.get_rest_api_id.return_value = None
    aws_client.import_rest_api.return_value = 'rest-api-id'
    lambda_arn = 'arn:aws:lambda:us-west-2:account-id:function:func-name'

    d = APIGatewayDeployer(aws_client)
    d.deploy(config_obj, None, {'api_handler_arn': lambda_arn})

    # mock.ANY because we don't want to test the contents of the swagger
    # doc.  That's tested exhaustively elsewhere.
    # We will do a basic sanity check to make sure it looks like a swagger
    # doc.
    aws_client.import_rest_api.assert_called_with(mock.ANY)
    first_arg = aws_client.import_rest_api.call_args[0][0]
    assert isinstance(first_arg, dict)
    assert 'swagger' in first_arg

    aws_client.deploy_rest_api.assert_called_with('rest-api-id', 'dev')
    aws_client.add_permission_for_apigateway_if_needed.assert_called_with(
        'func-name', 'us-west-2', 'account-id', 'rest-api-id', mock.ANY
    )


def test_api_gateway_deployer_redeploy_api(config_obj):
    aws_client = mock.Mock(spec=TypedAWSClient, region_name='us-west-2')

    # The rest_api_id does not exist which will trigger
    # the initial import
    deployed = DeployedResources(
        None, None, None, 'existing-id', 'dev', None, None)
    aws_client.rest_api_exists.return_value = True
    lambda_arn = 'arn:aws:lambda:us-west-2:account-id:function:func-name'

    d = APIGatewayDeployer(aws_client)
    d.deploy(config_obj, deployed, {'api_handler_arn': lambda_arn})

    aws_client.update_api_from_swagger.assert_called_with('existing-id',
                                                          mock.ANY)
    second_arg = aws_client.update_api_from_swagger.call_args[0][1]
    assert isinstance(second_arg, dict)
    assert 'swagger' in second_arg

    aws_client.deploy_rest_api.assert_called_with('existing-id', 'dev')
    aws_client.add_permission_for_apigateway_if_needed.assert_called_with(
        'func-name', 'us-west-2', 'account-id', 'existing-id', mock.ANY
    )


def test_api_gateway_deployer_delete(config_obj):
    aws_client = mock.Mock(spec=TypedAWSClient, region_name='us-west-2')

    rest_api_id = 'abcdef1234'
    deployed = DeployedResources(
        None, None, None, rest_api_id, 'dev', None, None)
    aws_client.rest_api_exists.return_value = True

    d = APIGatewayDeployer(aws_client)
    d.delete(deployed)
    aws_client.delete_rest_api.assert_called_with(rest_api_id)


def test_api_gateway_deployer_delete_already_deleted(capsys):
    rest_api_id = 'abcdef1234'
    aws_client = mock.Mock(spec=TypedAWSClient, region_name='us-west-2')
    aws_client.delete_rest_api.side_effect = ResourceDoesNotExistError(
        rest_api_id)
    deployed = DeployedResources(
        None, None, None, rest_api_id, 'dev', None, None)
    aws_client.rest_api_exists.return_value = True
    d = APIGatewayDeployer(aws_client)
    d.delete(deployed)

    # Check that we printed out that no rest api with that id was found
    out, _ = capsys.readouterr()
    assert "No rest API with id %s found." % rest_api_id in out
    aws_client.delete_rest_api.assert_called_with(rest_api_id)


def test_policy_autogenerated_when_enabled(app_policy,
                                           in_memory_osutils):
    in_memory_osutils.filemap['./app.py'] = ''
    config = Config.create(project_dir='.', autogen_policy=True)
    generated = app_policy.generate_policy_from_app_source(config)
    # We don't actually need to validate the exact policy, we'll just
    # check that it looks ok.
    assert 'Statement' in generated
    assert 'Version' in generated


def test_can_load_non_stage_specific_name(app_policy, in_memory_osutils):
    # This is a test for backcompat loading of .chalice/policy.json
    # for the dev stage.  The default name is suppose to include
    # the chalice stage name, e.g. policy-dev.json, but to support
    # existing use cases we'll look for .chalice/policy.json only
    # if you're in dev stage.
    previous_policy = '{"Statement": ["foo"]}'
    filename = os.path.join('.', '.chalice', 'policy.json')
    in_memory_osutils.filemap[filename] = previous_policy
    config = Config.create(project_dir='.', autogen_policy=False)
    generated = app_policy.generate_policy_from_app_source(config)
    assert generated == json.loads(previous_policy)


def test_legacy_file_not_loaded_in_non_dev_stage(app_policy,
                                                 in_memory_osutils):
    previous_policy = '{"Statement": ["foo"]}'
    filename = os.path.join('.', '.chalice', 'policy.json')
    in_memory_osutils.filemap[filename] = previous_policy
    config = Config.create(project_dir='.', autogen_policy=False,
                           chalice_stage='not-dev')
    generated = app_policy.generate_policy_from_app_source(config)
    # We should not have loaded the previously policy from policy.json
    # because that's only supported for the 'dev' stage.
    assert generated != json.loads(previous_policy)


def test_can_provide_stage_specific_policy_file(app_policy, in_memory_osutils):
    policy_filename = 'my-custom-policy.json'
    config = Config.create(project_dir='.', autogen_policy=False,
                           iam_policy_file=policy_filename,
                           chalice_stage='dev')

    previous_policy = '{"Statement": ["foo"]}'
    filename = os.path.join('.', '.chalice', policy_filename)
    in_memory_osutils.filemap[filename] = previous_policy
    generated = app_policy.generate_policy_from_app_source(config)
    assert generated == json.loads(previous_policy)


def test_can_provide_stage_specific_policy_for_other_stage(app_policy,
                                                           in_memory_osutils):
    policy_filename = 'my-prod-filename.json'
    config = Config.create(project_dir='.',
                           autogen_policy=False,
                           iam_policy_file=policy_filename,
                           chalice_stage='prod')
    previous_policy = '{"Statement": ["foo"]}'
    filename = os.path.join('.', '.chalice', policy_filename)
    in_memory_osutils.filemap[filename] = previous_policy
    generated = app_policy.generate_policy_from_app_source(config)
    assert generated == json.loads(previous_policy)


def test_autogen_policy_for_non_dev_stage(app_policy, in_memory_osutils):
    in_memory_osutils.filemap['./app.py'] = ''
    config = Config.create(
        project_dir='.',
        chalice_stage='prod',
        autogen_policy=True,
    )
    generated = app_policy.generate_policy_from_app_source(config)
    assert 'Statement' in generated
    assert 'Version' in generated


def test_no_policy_generated_when_disabled_in_config(app_policy,
                                                     in_memory_osutils):
    previous_policy = '{"Statement": ["foo"]}'
    filename = os.path.join('.', '.chalice', 'policy-dev.json')
    in_memory_osutils.filemap[filename] = previous_policy
    config = Config.create(project_dir='.', autogen_policy=False)
    generated = app_policy.generate_policy_from_app_source(config)
    assert generated == json.loads(previous_policy)


def test_load_last_policy_when_file_does_not_exist(app_policy):
    loaded = app_policy.load_last_policy(Config.create(project_dir='.'))
    assert loaded == {
        "Statement": [],
        "Version": "2012-10-17",
    }


def test_load_policy_from_disk_when_file_exists(app_policy,
                                                in_memory_osutils):
    previous_policy = '{"Statement": ["foo"]}'
    config = Config.create(project_dir='.')
    filename = os.path.join('.', '.chalice', 'policy-dev.json')
    in_memory_osutils.filemap[filename] = previous_policy
    loaded = app_policy.load_last_policy(config)
    assert loaded == json.loads(previous_policy)


def test_can_record_policy_to_disk(app_policy):
    latest_policy = {"Statement": ["policy"]}
    config = Config.create(project_dir='.')
    app_policy.record_policy(config, latest_policy)
    assert app_policy.load_last_policy(config) == latest_policy


def test_trailing_slash_routes_result_in_error():
    app = Chalice('appname')
    app.routes = {'/trailing-slash/': None}
    config = Config.create(chalice_app=app)
    with pytest.raises(ValueError):
        validate_configuration(config)


def test_validate_python_version_invalid():
    config = mock.Mock(spec=Config)
    config.lambda_python_version = 'python1.0'
    with pytest.warns(UserWarning):
        validate_python_version(config)


def test_python_version_invalid_from_real_config():
    config = Config.create()
    with pytest.warns(UserWarning):
        validate_python_version(config, 'python1.0')


def test_python_version_is_valid():
    config = Config.create()
    with pytest.warns(None) as record:
        validate_python_version(config, config.lambda_python_version)
    assert len(record) == 0


def test_manage_iam_role_false_requires_role_arn(sample_app):
    config = Config.create(chalice_app=sample_app, manage_iam_role=False,
                           iam_role_arn='arn:::foo')
    assert validate_configuration(config) is None


def test_validation_error_if_no_role_provided_when_manage_false(sample_app):
    # We're indicating that we should not be managing the
    # IAM role, but we're not giving a role ARN to use.
    # This is a validation error.
    config = Config.create(chalice_app=sample_app, manage_iam_role=False)
    with pytest.raises(ValueError):
        validate_configuration(config)

class TestChaliceDeploymentError(object):
    def test_general_exception(self):
        general_exception = Exception('My Exception')
        deploy_error = ChaliceDeploymentError(general_exception)
        deploy_error_msg = str(deploy_error)
        assert (
            'ERROR - While deploying your chalice application'
            in deploy_error_msg
        )
        assert 'My Exception' in deploy_error_msg

    def test_lambda_client_error(self):
        lambda_error = LambdaClientError(
            Exception('My Exception'),
            context=LambdaErrorContext(
                function_name='foo',
                client_method_name='create_function',
                deployment_size=1024 ** 2
            )
        )
        deploy_error = ChaliceDeploymentError(lambda_error)
        deploy_error_msg = str(deploy_error)
        assert (
            'ERROR - While sending your chalice handler code to '
            'Lambda to create function \n"foo"' in deploy_error_msg
        )
        assert 'My Exception' in deploy_error_msg

    def test_lambda_client_error_wording_for_update(self):
        lambda_error = LambdaClientError(
            Exception('My Exception'),
            context=LambdaErrorContext(
                function_name='foo',
                client_method_name='update_function_code',
                deployment_size=1024 ** 2
            )
        )
        deploy_error = ChaliceDeploymentError(lambda_error)
        deploy_error_msg = str(deploy_error)
        assert (
            'sending your chalice handler code to '
            'Lambda to update function' in deploy_error_msg
        )

    def test_gives_where_and_suggestion_for_too_large_deployment_error(self):
        too_large_error = DeploymentPackageTooLargeError(
            Exception('Too large of deployment pacakge'),
            context=LambdaErrorContext(
                function_name='foo',
                client_method_name='create_function',
                deployment_size=1024 ** 2,
            )
        )
        deploy_error = ChaliceDeploymentError(too_large_error)
        deploy_error_msg = str(deploy_error)
        assert (
            'ERROR - While sending your chalice handler code to '
            'Lambda to create function \n"foo"' in deploy_error_msg
        )
        assert 'Too large of deployment pacakge' in deploy_error_msg
        assert (
            'To avoid this error, decrease the size of your chalice '
            'application ' in deploy_error_msg
        )

    def test_include_size_context_for_too_large_deployment_error(self):
        too_large_error = DeploymentPackageTooLargeError(
            Exception('Too large of deployment pacakge'),
            context=LambdaErrorContext(
                function_name='foo',
                client_method_name='create_function',
                deployment_size=58 * (1024 ** 2),
            )
        )
        deploy_error = ChaliceDeploymentError(
            too_large_error)
        deploy_error_msg = str(deploy_error)
        print(repr(deploy_error_msg))
        assert 'deployment package is 58.0 MB' in deploy_error_msg
        assert '50.0 MB or less' in deploy_error_msg
        assert 'To avoid this error' in deploy_error_msg

    def test_error_msg_for_general_connection(self):
        lambda_error = DeploymentPackageTooLargeError(
            RequestsConnectionError(
                Exception(
                    'Connection aborted.',
                    socket.error('Some vague reason')
                )
            ),
            context=LambdaErrorContext(
                function_name='foo',
                client_method_name='create_function',
                deployment_size=1024 ** 2
            )
        )
        deploy_error = ChaliceDeploymentError(lambda_error)
        deploy_error_msg = str(deploy_error)
        assert 'Connection aborted.' in deploy_error_msg
        assert 'Some vague reason' not in deploy_error_msg

    def test_simplifies_error_msg_for_broken_pipe(self):
        lambda_error = DeploymentPackageTooLargeError(
            RequestsConnectionError(
                Exception(
                    'Connection aborted.',
                    socket.error(32, 'Broken pipe')
                )
            ),
            context=LambdaErrorContext(
                function_name='foo',
                client_method_name='create_function',
                deployment_size=1024 ** 2
            )
        )
        deploy_error = ChaliceDeploymentError(lambda_error)
        deploy_error_msg = str(deploy_error)
        assert (
            'Connection aborted. Lambda closed the connection' in
            deploy_error_msg
        )

    def test_simplifies_error_msg_for_timeout(self):
        lambda_error = DeploymentPackageTooLargeError(
            RequestsConnectionError(
                Exception(
                    'Connection aborted.',
                    socket.timeout('The write operation timed out')
                )
            ),
            context=LambdaErrorContext(
                function_name='foo',
                client_method_name='create_function',
                deployment_size=1024 ** 2
            )
        )
        deploy_error = ChaliceDeploymentError(lambda_error)
        deploy_error_msg = str(deploy_error)
        assert (
            'Connection aborted. Timed out sending your app to Lambda.' in
            deploy_error_msg
        )


class TestDeployer(object):
    def test_can_deploy_apig_and_lambda(self, sample_app):
        lambda_deploy = mock.Mock(spec=LambdaDeployer)
        apig_deploy = mock.Mock(spec=APIGatewayDeployer)

        lambda_deploy.deploy.return_value = {
            'api_handler_name': 'lambda_function',
            'api_handler_arn': 'my_lambda_arn',
        }
        apig_deploy.deploy.return_value = ('api_id', 'region', 'stage')

        d = Deployer(apig_deploy, lambda_deploy)
        cfg = Config.create(
            chalice_stage='dev',
            chalice_app=sample_app,
            project_dir='.')
        d.deploy(cfg)
        lambda_deploy.deploy.assert_called_with(cfg, None, 'dev')
        apig_deploy.deploy.assert_called_with(cfg, None, {
            'rest_api_id': 'api_id',
            'chalice_version': chalice_version,
            'region': 'region',
            'api_gateway_stage': 'stage',
            'api_handler_name': 'lambda_function',
            'api_handler_arn': 'my_lambda_arn', 'backend': 'api'
        })

    def test_deployer_returns_deployed_resources(self, sample_app):
        cfg = Config.create(
            chalice_stage='dev',
            chalice_app=sample_app,
            project_dir='.',
        )
        lambda_deploy = mock.Mock(spec=LambdaDeployer)
        apig_deploy = mock.Mock(spec=APIGatewayDeployer)

        apig_deploy.deploy.return_value = ('api_id', 'region', 'stage')
        lambda_deploy.deploy.return_value = {
            'api_handler_name': 'lambda_function',
            'api_handler_arn': 'my_lambda_arn',
        }

        d = Deployer(apig_deploy, lambda_deploy)
        deployed_values = d.deploy(cfg)
        assert deployed_values == {
            'dev': {
                'backend': 'api',
                'api_handler_arn': 'my_lambda_arn',
                'api_handler_name': 'lambda_function',
                'rest_api_id': 'api_id',
                'api_gateway_stage': 'stage',
                'region': 'region',
                'chalice_version': chalice_version,
            }
        }

    def test_deployer_delete_calls_deletes(self):
        # Check that athe deployer class calls other deployer classes delete
        # methods.
        lambda_deploy = mock.Mock(spec=LambdaDeployer)
        apig_deploy = mock.Mock(spec=APIGatewayDeployer)
        cfg = mock.Mock(spec=Config)
        deployed_resources = DeployedResources.from_dict({
            'backend': 'api',
            'api_handler_arn': 'lambda_arn',
            'api_handler_name': 'lambda_name',
            'rest_api_id': 'rest_id',
            'api_gateway_stage': 'dev',
            'region': 'us-west-2',
            'chalice_version': '0',
        })
        cfg.deployed_resources.return_value = deployed_resources

        d = Deployer(apig_deploy, lambda_deploy)
        d.delete(cfg)

        lambda_deploy.delete.assert_called_with(deployed_resources)
        apig_deploy.delete.assert_called_with(deployed_resources)

    def test_deployer_does_not_call_delete_when_no_resources(self, capsys):
        # If there is nothing to clean up the deployer should not call delete.
        lambda_deploy = mock.Mock(spec=LambdaDeployer)
        apig_deploy = mock.Mock(spec=APIGatewayDeployer)
        cfg = mock.Mock(spec=Config)
        deployed_resources = None
        cfg.deployed_resources.return_value = deployed_resources
        d = Deployer(apig_deploy, lambda_deploy)
        d.delete(cfg)

        out, _ = capsys.readouterr()
        assert 'No existing resources found for stage dev' in out
        lambda_deploy.delete.assert_not_called()
        apig_deploy.delete.assert_not_called()

    def test_raises_deployment_error_for_botcore_client_error(self,
                                                              sample_app):
        lambda_deploy = mock.Mock(spec=LambdaDeployer)
        apig_deploy = mock.Mock(spec=APIGatewayDeployer)
        lambda_deploy.deploy.side_effect = ClientError(
            {
                'Error': {
                    'Code': 'AccessDenied',
                    'Message': 'Denied'
                }
            },
            'CreateFunction'
        )
        d = Deployer(apig_deploy, lambda_deploy)
        cfg = Config.create(
            chalice_stage='dev',
            chalice_app=sample_app,
            project_dir='.',
        )
        with pytest.raises(ChaliceDeploymentError) as excinfo:
            d.deploy(cfg)
        assert excinfo.match('ERROR - While deploying')
        assert excinfo.match('Denied')

    def test_raises_deployment_error_for_lambda_client_error(self, sample_app):
        lambda_deploy = mock.Mock(spec=LambdaDeployer)
        apig_deploy = mock.Mock(spec=APIGatewayDeployer)
        lambda_deploy.deploy.side_effect = LambdaClientError(
            Exception('my error'),
            context=LambdaErrorContext(
                function_name='foo',
                client_method_name='create_function',
                deployment_size=1024 ** 2
            )
        )
        d = Deployer(apig_deploy, lambda_deploy)
        cfg = Config.create(
            chalice_stage='dev',
            chalice_app=sample_app,
            project_dir='.',
        )
        with pytest.raises(ChaliceDeploymentError) as excinfo:
            d.deploy(cfg)
        assert excinfo.match('ERROR - While sending')
        assert excinfo.match('my error')

    def test_raises_deployment_error_for_apig_error(self, sample_app):
        lambda_deploy = mock.Mock(spec=LambdaDeployer)
        apig_deploy = mock.Mock(spec=APIGatewayDeployer)
        lambda_deploy.deploy.return_value = {
            'api_handler_name': 'lambda_function',
            'api_handler_arn': 'my_lambda_arn',
        }
        apig_deploy.deploy.side_effect = ClientError(
            {
                'Error': {
                    'Code': 'AccessDenied',
                    'Message': 'Denied'
                }
            },
            'CreateStage'
        )
        d = Deployer(apig_deploy, lambda_deploy)
        cfg = Config.create(
            chalice_stage='dev',
            chalice_app=sample_app,
            project_dir='.',
        )
        with pytest.raises(ChaliceDeploymentError) as excinfo:
            d.deploy(cfg)
        assert excinfo.match('ERROR - While deploying')
        assert excinfo.match('Denied')


def test_noprompt_always_returns_default():
    assert not NoPrompt().confirm("You sure you want to do this?",
                                  default=False)
    assert NoPrompt().confirm("You sure you want to do this?",
                              default=True)
    assert NoPrompt().confirm("You sure?", default='yes') == 'yes'


def test_lambda_deployer_repeated_deploy(app_policy, sample_app):
    osutils = InMemoryOSUtils({'packages.zip': b'package contents'})
    aws_client = mock.Mock(spec=TypedAWSClient)
    packager = mock.Mock(spec=LambdaDeploymentPackager)

    packager.deployment_package_filename.return_value = 'packages.zip'
    # Given the lambda function already exists:
    aws_client.lambda_function_exists.return_value = True
    aws_client.update_function.return_value = {"FunctionArn": "myarn"}
    # And given we don't want chalice to manage our iam role for the lambda
    # function:
    cfg = Config.create(
        chalice_stage='dev',
        chalice_app=sample_app,
        manage_iam_role=False,
        app_name='appname',
        iam_role_arn='role-arn',
        project_dir='./myproject',
        environment_variables={"FOO": "BAR"},
        lambda_timeout=120,
        lambda_memory_size=256,
        tags={'mykey': 'myvalue'}
    )
    aws_client.get_function_configuration.return_value = {
        'Runtime': cfg.lambda_python_version,
    }
    prompter = mock.Mock(spec=NoPrompt)
    prompter.confirm.return_value = True

    d = LambdaDeployer(aws_client, packager, prompter, osutils, app_policy)
    # Doing a lambda deploy:
    lambda_function_name = 'lambda_function_name'
    deployed = DeployedResources(
        'api', 'api_handler_arn', lambda_function_name,
        None, 'dev', None, None)
    d.deploy(cfg, deployed, 'dev')

    # Should result in injecting the latest app code.
    packager.inject_latest_app.assert_called_with('packages.zip',
                                                  './myproject')

    # And should result in the lambda function being updated with the API.
    aws_client.update_function.assert_called_with(
        function_name=lambda_function_name,
        zip_contents=b'package contents',
        runtime=cfg.lambda_python_version,
        environment_variables={"FOO": "BAR"},
        tags={
            'aws-chalice': 'version=%s:stage=%s:app=%s' % (
                chalice_version, 'dev', 'appname'),
            'mykey': 'myvalue'
        },
        timeout=120, memory_size=256,
        role_arn='role-arn'
    )


def test_lambda_deployer_delete():
    aws_client = mock.Mock(spec=TypedAWSClient)
    aws_client.get_role_arn_for_name.return_value = 'arn_prefix/role_name'
    lambda_function_name = 'lambda_name'
    deployed = DeployedResources(
        'api', 'api_handler_arn/lambda_name', lambda_function_name,
        None, 'dev', None, None)
    d = LambdaDeployer(
        aws_client, None, CustomConfirmPrompt(True), None, None)
    d.delete(deployed)

    aws_client.get_role_arn_for_name.assert_called_with(lambda_function_name)
    aws_client.delete_function.assert_called_with(lambda_function_name)
    aws_client.delete_role.assert_called_with('role_name')


def test_lambda_deployer_delete_already_deleted(capsys):
    lambda_function_name = 'lambda_name'
    aws_client = mock.Mock(spec=TypedAWSClient)
    aws_client.get_role_arn_for_name.return_value = 'arn_prefix/role_name'
    aws_client.delete_function.side_effect = ResourceDoesNotExistError(
        lambda_function_name)
    deployed = DeployedResources(
        'api', 'api_handler_arn/lambda_name', lambda_function_name,
        None, 'dev', None, None)
    d = LambdaDeployer(
        aws_client, None, NoPrompt(), None, None)
    d.delete(deployed)

    # check that we printed that no lambda function with that name was found
    out, _ = capsys.readouterr()
    assert "No lambda function named %s found." % lambda_function_name in out
    aws_client.delete_function.assert_called_with(lambda_function_name)


def test_prompted_on_runtime_change_can_reject_change(app_policy, sample_app):
    osutils = InMemoryOSUtils({'packages.zip': b'package contents'})
    aws_client = mock.Mock(spec=TypedAWSClient)
    packager = mock.Mock(spec=LambdaDeploymentPackager)
    packager.deployment_package_filename.return_value = 'packages.zip'
    aws_client.lambda_function_exists.return_value = True
    aws_client.get_function_configuration.return_value = {
        'Runtime': 'python1.0',
    }
    aws_client.update_function.return_value = {"FunctionArn": "myarn"}
    cfg = Config.create(
        chalice_stage='dev',
        chalice_app=sample_app,
        manage_iam_role=False,
        app_name='appname',
        iam_role_arn=True,
        project_dir='./myproject',
        environment_variables={"FOO": "BAR"},
    )
    prompter = mock.Mock(spec=NoPrompt)
    prompter.confirm.side_effect = RuntimeError("Aborted")

    d = LambdaDeployer(aws_client, packager, prompter, osutils, app_policy)
    # Doing a lambda deploy with a different runtime:
    lambda_function_name = 'lambda_function_name'
    deployed = DeployedResources(
        'api', 'api_handler_arn', lambda_function_name,
        None, 'dev', None, None)
    with pytest.raises(RuntimeError):
        d.deploy(cfg, deployed, 'dev')

    assert not packager.inject_latest_app.called
    assert not aws_client.update_function.called
    assert prompter.confirm.called
    message = prompter.confirm.call_args[0][0]
    assert 'runtime will change' in message


def test_lambda_deployer_initial_deploy(app_policy, sample_app):
    osutils = InMemoryOSUtils({'packages.zip': b'package contents'})
    aws_client = mock.Mock(spec=TypedAWSClient)
    aws_client.create_function.return_value = 'lambda-arn'
    packager = mock.Mock(LambdaDeploymentPackager)
    packager.create_deployment_package.return_value = 'packages.zip'
    cfg = Config.create(
        chalice_stage='dev',
        app_name='myapp',
        chalice_app=sample_app,
        manage_iam_role=False,
        iam_role_arn='role-arn',
        project_dir='.',
        environment_variables={"FOO": "BAR"},
        lambda_timeout=120,
        lambda_memory_size=256,
        tags={'mykey': 'myvalue'}
    )

    d = LambdaDeployer(aws_client, packager, None, osutils, app_policy)
    deployed = d.deploy(cfg, None, 'dev')
    assert deployed == {
        'api_handler_arn': 'lambda-arn',
        'api_handler_name': 'myapp-dev',
    }
    aws_client.create_function.assert_called_with(
        function_name='myapp-dev', role_arn='role-arn',
        zip_contents=b'package contents',
        environment_variables={"FOO": "BAR"},
        runtime=cfg.lambda_python_version,
        tags={
            'aws-chalice': 'version=%s:stage=dev:app=myapp' % chalice_version,
            'mykey': 'myvalue'
        },
        handler='app.app',
        timeout=120, memory_size=256,
    )

class TestValidateCORS(object):
    def test_cant_have_options_with_cors(self, sample_app):
        @sample_app.route('/badcors', methods=['GET', 'OPTIONS'], cors=True)
        def badview():
            pass

        with pytest.raises(ValueError):
            validate_routes(sample_app.routes)

    def test_cant_have_differing_cors_configurations(self, sample_app):
        custom_cors = CORSConfig(
            allow_origin='https://foo.example.com',
            allow_headers=['X-Special-Header'],
            max_age=600,
            expose_headers=['X-Special-Header'],
            allow_credentials=True
        )

        @sample_app.route('/cors', methods=['GET'], cors=True)
        def cors():
            pass

        @sample_app.route('/cors', methods=['PUT'], cors=custom_cors)
        def different_cors():
            pass

        with pytest.raises(ValueError):
            validate_routes(sample_app.routes)

    def test_can_have_same_cors_configurations(self, sample_app):
        @sample_app.route('/cors', methods=['GET'], cors=True)
        def cors():
            pass

        @sample_app.route('/cors', methods=['PUT'], cors=True)
        def same_cors():
            pass

        try:
            validate_routes(sample_app.routes)
        except ValueError:
            pytest.fail(
                'A ValueError was unexpectedly thrown. Applications '
                'may have multiple view functions that share the same '
                'route and CORS configuration.'
            )

    def test_can_have_same_custom_cors_configurations(self, sample_app):
        custom_cors = CORSConfig(
            allow_origin='https://foo.example.com',
            allow_headers=['X-Special-Header'],
            max_age=600,
            expose_headers=['X-Special-Header'],
            allow_credentials=True
        )
        @sample_app.route('/cors', methods=['GET'], cors=custom_cors)
        def cors():
            pass

        same_custom_cors = CORSConfig(
            allow_origin='https://foo.example.com',
            allow_headers=['X-Special-Header'],
            max_age=600,
            expose_headers=['X-Special-Header'],
            allow_credentials=True
        )
        @sample_app.route('/cors', methods=['PUT'], cors=same_custom_cors)
        def same_cors():
            pass

        try:
            validate_routes(sample_app.routes)
        except ValueError:
            pytest.fail(
                'A ValueError was unexpectedly thrown. Applications '
                'may have multiple view functions that share the same '
                'route and CORS configuration.'
            )

    def test_can_have_one_cors_configured_and_others_not(self, sample_app):
        @sample_app.route('/cors', methods=['GET'], cors=True)
        def cors():
            pass

        @sample_app.route('/cors', methods=['PUT'])
        def no_cors():
            pass

        try:
            validate_routes(sample_app.routes)
        except ValueError:
            pytest.fail(
                'A ValueError was unexpectedly thrown. Applications '
                'may have multiple view functions that share the same '
                'route but only one is configured for CORS.'
            )


def test_cant_have_mixed_content_types(sample_app):
    @sample_app.route('/index', content_types=['application/octet-stream',
                                               'text/plain'])
    def index():
        return {'hello': 'world'}

    with pytest.raises(ValueError):
        validate_route_content_types(sample_app.routes,
                                     sample_app.api.binary_types)


def test_can_validate_updated_custom_binary_types(sample_app):
    sample_app.api.binary_types.extend(['text/plain'])

    @sample_app.route('/index', content_types=['application/octet-stream',
                                               'text/plain'])
    def index():
        return {'hello': 'world'}

    assert validate_route_content_types(sample_app.routes,
                                        sample_app.api.binary_types) is None


class TestLambdaInitialDeploymentWithConfigurations(object):
    @fixture(autouse=True)
    def setup_deployer_dependencies(self, app_policy):
        # This autouse fixture is used instead of ``setup_method`` because it:
        # * Is ran for every test
        # * Allows additional fixtures to be passed in to reduce the number
        #   of fixtures that need to be supplied for the test methods.
        # * ``setup_method`` is called before fixtures get applied so
        #   they cannot be applied to the ``setup_method`` or you will
        #   will get a TypeError for too few arguments.
        self.package_name = 'packages.zip'
        self.package_contents = b'package contents'
        self.lambda_arn = 'lambda-arn'
        self.osutils = InMemoryOSUtils(
            {self.package_name: self.package_contents})
        self.aws_client = mock.Mock(spec=TypedAWSClient)
        self.aws_client.create_function.return_value = self.lambda_arn
        self.packager = mock.Mock(LambdaDeploymentPackager)
        self.packager.create_deployment_package.return_value =\
            self.package_name
        self.app_policy = app_policy

    def test_lambda_deployer_defaults(self, sample_app):
        cfg = Config.create(
            chalice_stage='dev', app_name='myapp', chalice_app=sample_app,
            manage_iam_role=False, iam_role_arn='role-arn',
            project_dir='.'
        )
        deployer = LambdaDeployer(
            self.aws_client, self.packager, None, self.osutils,
            self.app_policy)

        deployer.deploy(cfg, None, 'dev')
        self.aws_client.create_function.assert_called_with(
            function_name='myapp-dev', role_arn='role-arn',
            zip_contents=b'package contents',
            runtime=cfg.lambda_python_version,
            tags={
                'aws-chalice': 'version=%s:stage=dev:app=myapp' % (
                    chalice_version)
            },
            environment_variables={},
            handler='app.app',
            timeout=60, memory_size=128
        )

    def test_lambda_deployer_with_environment_vars(self, sample_app):
        cfg = Config.create(
            chalice_stage='dev', app_name='myapp', chalice_app=sample_app,
            manage_iam_role=False, iam_role_arn='role-arn',
            project_dir='.', environment_variables={'FOO': 'BAR'}
        )
        deployer = LambdaDeployer(
            self.aws_client, self.packager, None, self.osutils,
            self.app_policy)

        deployer.deploy(cfg, None, 'dev')
        self.aws_client.create_function.assert_called_with(
            function_name='myapp-dev', role_arn='role-arn',
            zip_contents=b'package contents',
            runtime=cfg.lambda_python_version,
            tags={
                'aws-chalice': 'version=%s:stage=dev:app=myapp' % (
                    chalice_version)
            },
            environment_variables={'FOO': 'BAR'},
            handler='app.app',
            timeout=60, memory_size=128
        )

    def test_lambda_deployer_with_timeout_configured(self, sample_app):
        cfg = Config.create(
            chalice_stage='dev', app_name='myapp', chalice_app=sample_app,
            manage_iam_role=False, iam_role_arn='role-arn',
            project_dir='.', lambda_timeout=120
        )
        deployer = LambdaDeployer(
            self.aws_client, self.packager, None, self.osutils,
            self.app_policy)

        deployer.deploy(cfg, None, 'dev')
        self.aws_client.create_function.assert_called_with(
            function_name='myapp-dev', role_arn='role-arn',
            zip_contents=b'package contents',
            runtime=cfg.lambda_python_version,
            tags={
                'aws-chalice': 'version=%s:stage=dev:app=myapp' % (
                    chalice_version)
            },
            environment_variables={},
            handler='app.app',
            timeout=120, memory_size=128
        )

    def test_lambda_deployer_with_memory_size_configured(self, sample_app):
        cfg = Config.create(
            chalice_stage='dev', app_name='myapp', chalice_app=sample_app,
            manage_iam_role=False, iam_role_arn='role-arn',
            project_dir='.', lambda_memory_size=256
        )
        deployer = LambdaDeployer(
            self.aws_client, self.packager, None, self.osutils,
            self.app_policy)

        deployer.deploy(cfg, None, 'dev')
        self.aws_client.create_function.assert_called_with(
            function_name='myapp-dev', role_arn='role-arn',
            zip_contents=b'package contents',
            runtime=cfg.lambda_python_version,
            tags={
                'aws-chalice': 'version=%s:stage=dev:app=myapp' % (
                    chalice_version)
            },
            environment_variables={},
            handler='app.app',
            timeout=60, memory_size=256
        )

    def test_lambda_deployer_with_tags(self, sample_app):
        cfg = Config.create(
            chalice_stage='dev', app_name='myapp', chalice_app=sample_app,
            manage_iam_role=False, iam_role_arn='role-arn',
            project_dir='.', tags={'mykey': 'myvalue'}
        )
        deployer = LambdaDeployer(
            self.aws_client, self.packager, None, self.osutils,
            self.app_policy)

        deployer.deploy(cfg, None, 'dev')
        self.aws_client.create_function.assert_called_with(
            function_name='myapp-dev', role_arn='role-arn',
            zip_contents=b'package contents',
            runtime=cfg.lambda_python_version,
            tags={
                'aws-chalice': 'version=%s:stage=dev:app=myapp' % (
                    chalice_version),
                'mykey': 'myvalue'
            },
            environment_variables={},
            handler='app.app',
            timeout=60, memory_size=128
        )


class TestLambdaUpdateDeploymentWithConfigurations(object):
    @fixture(autouse=True)
    def setup_deployer_dependencies(self, app_policy):
        # This autouse fixture is used instead of ``setup_method`` because it:
        # * Is ran for every test
        # * Allows additional fixtures to be passed in to reduce the number
        #   of fixtures that need to be supplied for the test methods.
        # * ``setup_method`` is called before fixtures get applied so
        #   they cannot be applied to the ``setup_method`` or you will
        #   will get a TypeError for too few arguments.
        self.package_name = 'packages.zip'
        self.package_contents = b'package contents'
        self.lambda_arn = 'lambda-arn'
        self.lambda_function_name = 'lambda_function_name'

        self.osutils = InMemoryOSUtils(
            {self.package_name: self.package_contents})

        self.aws_client = mock.Mock(spec=TypedAWSClient)
        self.aws_client.lambda_function_exists.return_value = True
        self.aws_client.update_function.return_value = {
            'FunctionArn': self.lambda_arn}
        self.aws_client.get_function_configuration.return_value = {
            'Runtime': 'python2.7',
        }

        self.prompter = mock.Mock(spec=NoPrompt)
        self.prompter.confirm.return_value = True

        self.packager = mock.Mock(LambdaDeploymentPackager)
        self.packager.create_deployment_package.return_value =\
            self.package_name

        self.app_policy = app_policy

        self.deployed_resources = DeployedResources(
            'api', 'api_handler_arn', self.lambda_function_name,
            None, 'dev', None, None)

    def test_lambda_deployer_defaults(self, sample_app):
        cfg = Config.create(
            chalice_stage='dev', app_name='myapp', chalice_app=sample_app,
            manage_iam_role=False, iam_role_arn='role-arn',
            project_dir='.',
        )
        deployer = LambdaDeployer(
            self.aws_client, self.packager, self.prompter, self.osutils,
            self.app_policy)

        deployer.deploy(cfg, self.deployed_resources, 'dev')
        self.aws_client.update_function.assert_called_with(
            function_name=self.lambda_function_name,
            zip_contents=self.package_contents,
            runtime=cfg.lambda_python_version,
            tags={
                'aws-chalice': 'version=%s:stage=dev:app=myapp' % (
                    chalice_version),
            },
            environment_variables={},
            timeout=60, memory_size=128,
            role_arn='role-arn'
        )

    def test_lambda_deployer_with_environment_vars(self, sample_app):
        cfg = Config.create(
            chalice_stage='dev', app_name='myapp', chalice_app=sample_app,
            manage_iam_role=False, iam_role_arn='role-arn',
            project_dir='.', environment_variables={'FOO': 'BAR'}
        )
        deployer = LambdaDeployer(
            self.aws_client, self.packager, self.prompter, self.osutils,
            self.app_policy)

        deployer.deploy(cfg, self.deployed_resources, 'dev')
        self.aws_client.update_function.assert_called_with(
            function_name=self.lambda_function_name,
            zip_contents=self.package_contents,
            runtime=cfg.lambda_python_version,
            tags={
                'aws-chalice': 'version=%s:stage=dev:app=myapp' % (
                    chalice_version),
            },
            environment_variables={'FOO': 'BAR'},
            timeout=60, memory_size=128,
            role_arn='role-arn'
        )

    def test_lambda_deployer_with_timeout_configured(self, sample_app):
        cfg = Config.create(
            chalice_stage='dev', app_name='myapp', chalice_app=sample_app,
            manage_iam_role=False, iam_role_arn='role-arn',
            project_dir='.', lambda_timeout=120
        )
        deployer = LambdaDeployer(
            self.aws_client, self.packager, self.prompter, self.osutils,
            self.app_policy)

        deployer.deploy(cfg, self.deployed_resources, 'dev')
        self.aws_client.update_function.assert_called_with(
            function_name=self.lambda_function_name,
            zip_contents=self.package_contents,
            runtime=cfg.lambda_python_version,
            tags={
                'aws-chalice': 'version=%s:stage=dev:app=myapp' % (
                    chalice_version),
            },
            environment_variables={},
            timeout=120, memory_size=128,
            role_arn='role-arn'
        )

    def test_lambda_deployer_with_memory_size_configured(self, sample_app):
        cfg = Config.create(
            chalice_stage='dev', app_name='myapp', chalice_app=sample_app,
            manage_iam_role=False, iam_role_arn='role-arn',
            project_dir='.', lambda_memory_size=256
        )
        deployer = LambdaDeployer(
            self.aws_client, self.packager, self.prompter, self.osutils,
            self.app_policy)

        deployer.deploy(cfg, self.deployed_resources, 'dev')
        self.aws_client.update_function.assert_called_with(
            function_name=self.lambda_function_name,
            zip_contents=self.package_contents,
            runtime=cfg.lambda_python_version,
            tags={
                'aws-chalice': 'version=%s:stage=dev:app=myapp' % (
                    chalice_version),
            },
            environment_variables={},
            timeout=60, memory_size=256,
            role_arn='role-arn'
        )

    def test_lambda_deployer_with_tags(self, sample_app):
        cfg = Config.create(
            chalice_stage='dev', app_name='myapp', chalice_app=sample_app,
            manage_iam_role=False, iam_role_arn='role-arn',
            project_dir='.', tags={'mykey': 'myvalue'}
        )
        deployer = LambdaDeployer(
            self.aws_client, self.packager, self.prompter, self.osutils,
            self.app_policy)

        deployer.deploy(cfg, self.deployed_resources, 'dev')
        self.aws_client.update_function.assert_called_with(
            function_name=self.lambda_function_name,
            zip_contents=self.package_contents,
            runtime=cfg.lambda_python_version,
            tags={
                'aws-chalice': 'version=%s:stage=dev:app=myapp' % (
                    chalice_version),
                'mykey': 'myvalue'
            },
            environment_variables={},
            timeout=60, memory_size=128,
            role_arn='role-arn'
        )
