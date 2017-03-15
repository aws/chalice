import pytest
from pytest import fixture
import mock
import json
import os

from chalice.awsclient import TypedAWSClient
from chalice.deployer import build_url_trie
from chalice.deployer import NoPrompt
from chalice.deployer import LambdaDeployer
from chalice.deployer import LambdaDeploymentPackager
from chalice.deployer import APIGatewayDeployer
from chalice.deployer import APIGatewayResourceCreator
from chalice.deployer import APIGatewayMethods
from chalice.deployer import validate_configuration
from chalice.deployer import validate_routes
from chalice.deployer import Deployer
from chalice.deployer import ApplicationPolicyHandler
from chalice.app import RouteEntry
from chalice.app import Chalice
from chalice.config import Config

from botocore.stub import Stubber, ANY
import botocore.session


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


@fixture
def stubbed_api_gateway():
    return stubbed_client('apigateway')


@fixture
def stubbed_lambda():
    return stubbed_client('lambda')


@fixture
def sample_app():
    app = Chalice('sample')

    @app.route('/')
    def foo():
        return {}

    return app


@fixture
def in_memory_osutils():
    return InMemoryOSUtils()


@fixture
def app_policy(in_memory_osutils):
    return ApplicationPolicyHandler(in_memory_osutils)


def stubbed_client(service_name):
    global _SESSION
    if _SESSION is None:
        _SESSION = botocore.session.get_session()
    client = _SESSION.create_client(service_name,
                                    region_name='us-west-2')
    stubber = Stubber(client)
    return client, stubber


def node(name, uri_path, children=None, resource_id=None,
         parent_resource_id=None, is_route=False):
    if children is None:
        children = {}
    return {
        'name': name,
        'uri_path': uri_path,
        'children': children,
        'resource_id': resource_id,
        'parent_resource_id': parent_resource_id,
        'is_route': is_route,
        'route_entry': None,
    }


n = node


def test_url_trie():
    assert build_url_trie({'/': None}) == n(name='', uri_path='/',
                                            is_route=True)


def test_single_nested_route():
    assert build_url_trie({'/foo/bar': None}) == n(
        name='', uri_path='/',
        children={
            'foo': n('foo', '/foo',
                     children={'bar':  n('bar', '/foo/bar', is_route=True)})
        }
    )


def test_multiple_routes():
    assert build_url_trie({'/foo/bar': None, '/bar': None, '/': None}) == n(
        name='', uri_path='/', is_route=True,
        children={
            'bar': n('bar', '/bar', is_route=True),
            'foo': n('foo', '/foo',
                     children={'bar':  n('bar', '/foo/bar', is_route=True)})
        }
    )


def test_multiple_routes_on_single_spine():
    assert build_url_trie({'/foo/bar': None, '/foo': None, '/': None}) == n(
        name='', uri_path='/', is_route=True,
        children={
            'foo': n('foo', '/foo', is_route=True,
                     children={'bar':  n('bar', '/foo/bar', is_route=True)})
        }
    )


def test_trailing_slash_routes_result_in_error():
    app = Chalice('appname')
    app.routes = {'/trailing-slash/': None}
    config = Config.create(chalice_app=app)
    with pytest.raises(ValueError):
        validate_configuration(config)


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


def test_can_build_resource_routes_for_single_view(stubbed_session):
    route_trie = {
        'name': '',
        'uri_path': '/',
        'children': {},
        'resource_id': 'parent-id',
        'parent_resource_id': None,
        'is_route': True,
        'route_entry': RouteEntry(None, 'index_view', '/', ['POST'],
                                  content_types=['application/json']),
    }
    gateway_client = stubbed_session.create_client('apigateway')
    gateway_stub = stubbed_session.stub('apigateway')
    lambda_stub = stubbed_session.stub('lambda')
    awsclient = TypedAWSClient(stubbed_session)
    g = APIGatewayResourceCreator(
        awsclient, APIGatewayMethods(gateway_client, 'rest-api-id'),
        'arn:aws:lambda:us-west-2:123:function:name',
        random_id_generator=lambda: "random-id")

    gateway_stub.put_method(
        resourceId='parent-id',
        authorizationType='NONE',
        restApiId='rest-api-id',
        httpMethod='POST',
    ).returns({})
    gateway_stub.put_integration(
        httpMethod='POST',
        integrationHttpMethod='POST',
        passthroughBehavior='WHEN_NO_MATCH',
        resourceId='parent-id',
        restApiId='rest-api-id',
        type='AWS_PROXY',
        contentHandling='CONVERT_TO_TEXT',
        uri=('arn:aws:apigateway:us-west-2:lambda:path'
             '/2015-03-31/functions/arn:aws:lambda:us-west'
             '-2:123:function:name/invocations')
    ).returns({})
    gateway_stub.put_method_response(
        httpMethod='POST',
        resourceId='parent-id',
        responseModels={
            'application/json': 'Empty',
        },
        restApiId='rest-api-id',
        statusCode='200',
    ).returns({})
    gateway_stub.put_integration_response(
        httpMethod='POST',
        resourceId='parent-id',
        responseTemplates={
            'application/json': '',
        },
        restApiId='rest-api-id',
        statusCode='200',
    ).returns({})
    lambda_stub.get_policy(FunctionName='name').returns({'Policy': '{}'})
    lambda_stub.add_permission(
        Action='lambda:InvokeFunction',
        FunctionName='name',
        Principal='apigateway.amazonaws.com',
        SourceArn='arn:aws:execute-api:us-west-2:123:rest-api-id/*',
        StatementId='random-id',
    ).returns({})
    stubbed_session.activate_stubs()
    g.build_resources(route_trie)
    stubbed_session.verify_stubs()


def test_cors_adds_required_headers(stubbed_session):
    cors_route_entry = RouteEntry(None, 'index_view', '/', ['PUT'],
                                  cors=True,
                                  content_types=['application/json'])
    route_trie = {
        'name': '',
        'uri_path': '/',
        'children': {},
        'resource_id': 'parent-id',
        'parent_resource_id': None,
        'is_route': True,
        'route_entry': cors_route_entry,
    }
    gateway_client = stubbed_session.create_client('apigateway')
    gateway_stub = stubbed_session.stub('apigateway')
    lambda_stub = stubbed_session.stub('lambda')
    awsclient = TypedAWSClient(stubbed_session)
    g = APIGatewayResourceCreator(
        awsclient, APIGatewayMethods(gateway_client, 'rest-api-id'),
        'arn:aws:lambda:us-west-2:123:function:name',
        random_id_generator=lambda: "random-id")
    gateway_stub.put_method(
        resourceId='parent-id',
        authorizationType='NONE',
        restApiId='rest-api-id',
        httpMethod='PUT',
    ).returns({})
    gateway_stub.put_integration(
        httpMethod='PUT',
        integrationHttpMethod='POST',
        passthroughBehavior='WHEN_NO_MATCH',
        resourceId='parent-id',
        restApiId='rest-api-id',
        contentHandling='CONVERT_TO_TEXT',
        type='AWS_PROXY',
        uri=('arn:aws:apigateway:us-west-2:lambda:path'
             '/2015-03-31/functions/arn:aws:lambda:us-west'
             '-2:123:function:name/invocations')
    ).returns({})
    gateway_stub.put_method_response(
        httpMethod='PUT',
        resourceId='parent-id',
        responseModels={
            'application/json': 'Empty',
        },
        restApiId='rest-api-id',
        statusCode='200',
    ).returns({})
    gateway_stub.put_integration_response(
        httpMethod='PUT',
        resourceId='parent-id',
        responseTemplates={
            'application/json': '',
        },
        restApiId='rest-api-id',
        statusCode='200',
    ).returns({})
    gateway_stub.put_method(
        restApiId=ANY,
        resourceId=ANY,
        httpMethod='OPTIONS',
        authorizationType='NONE',
    ).returns({})
    gateway_stub.put_integration(
        restApiId=ANY,
        resourceId=ANY,
        httpMethod='OPTIONS',
        type='MOCK',
        requestTemplates={'application/json': '{"statusCode": 200}'}
    ).returns({})
    gateway_stub.put_method_response(
        restApiId=ANY,
        resourceId=ANY,
        httpMethod='OPTIONS',
        statusCode='200',
        responseModels=ANY,
        responseParameters={
            'method.response.header.Access-Control-Allow-Origin': False,
            'method.response.header.Access-Control-Allow-Methods': False,
            'method.response.header.Access-Control-Allow-Headers': False,
        }
    ).returns({})
    gateway_stub.put_integration_response(
        restApiId=ANY,
        resourceId=ANY,
        httpMethod='OPTIONS',
        statusCode='200',
        responseTemplates=ANY,
        responseParameters={
            'method.response.header.Access-Control-Allow-Origin': "'*'",
            'method.response.header.Access-Control-Allow-Methods': (
                "'PUT,OPTIONS'"
            ),
            'method.response.header.Access-Control-Allow-Headers': (
                "'Content-Type,X-Amz-Date,Authorization,X-Api-Key"
                ",X-Amz-Security-Token'"
            ),
        }
    ).returns({})
    lambda_stub.get_policy(FunctionName='name').returns({'Policy': '{}'})
    lambda_stub.add_permission(
        Action='lambda:InvokeFunction',
        FunctionName='name',
        Principal='apigateway.amazonaws.com',
        SourceArn='arn:aws:execute-api:us-west-2:123:rest-api-id/*',
        StatementId='random-id',
    ).returns({})
    stubbed_session.activate_stubs()
    g.build_resources(route_trie)
    stubbed_session.verify_stubs()


def test_can_deploy_apig_and_lambda(sample_app):
    lambda_deploy = mock.Mock(spec=LambdaDeployer)
    apig_deploy = mock.Mock(spec=APIGatewayDeployer)

    apig_deploy.deploy.return_value = ('api_id', 'region', 'stage')

    d = Deployer(apig_deploy, lambda_deploy)
    cfg = Config({'chalice_app': sample_app})
    result = d.deploy(cfg)
    assert result == ('api_id', 'region', 'stage')
    lambda_deploy.deploy.assert_called_with(cfg)
    apig_deploy.deploy.assert_called_with(cfg)


def test_noprompt_always_returns_default():
    assert not NoPrompt().confirm("You sure you want to do this?",
                                  default=False)
    assert NoPrompt().confirm("You sure you want to do this?",
                              default=True)
    assert NoPrompt().confirm("You sure?", default='yes') == 'yes'


def test_lambda_deployer_repeated_deploy(app_policy):
    osutils = InMemoryOSUtils({'packages.zip': b'package contents'})
    aws_client = mock.Mock(spec=TypedAWSClient)
    packager = mock.Mock(spec=LambdaDeploymentPackager)

    packager.deployment_package_filename.return_value = 'packages.zip'
    # Given the lambda function already exists:
    aws_client.lambda_function_exists.return_value = True
    # And given we don't want chalice to manage our iam role for the lambda
    # function:
    cfg = Config({'chalice_app': sample_app, 'manage_iam_role': False,
                  'app_name': 'appname', 'iam_role_arn': True,
                  'project_dir': './myproject'})

    d = LambdaDeployer(aws_client, packager, None, osutils, app_policy)
    # Doing a lambda deploy:
    d.deploy(cfg)

    # Should result in injecting the latest app code.
    packager.inject_latest_app.assert_called_with('packages.zip',
                                                  './myproject')

    # And should result in the lambda function being updated with the API.
    aws_client.update_function_code.assert_called_with(
        'appname', 'package contents')


def test_cant_have_options_with_cors(sample_app):
    @sample_app.route('/badcors', methods=['GET', 'OPTIONS'], cors=True)
    def badview():
        pass

    with pytest.raises(ValueError):
        validate_routes(sample_app.routes)


def test_apig_methods(stubbed_session):
    gateway_stub = stubbed_session.stub('apigateway')
    gateway_stub.put_method(
        authorizationType='NONE',
        httpMethod='GET',
        resourceId='resource_id',
        restApiId='rest_api_id',
        requestParameters={'method.request.path.name': True},
    ).returns({})
    apig = APIGatewayMethods(
        stubbed_session.create_client('apigateway'), 'rest_api_id')

    stubbed_session.activate_stubs()
    apig.create_method_request('resource_id', 'GET', url_params=['name'])
    stubbed_session.verify_stubs()


def test_policy_autogenerated_when_enabled(app_policy,
                                           in_memory_osutils):
    cfg = Config.create(autogen_policy=True, project_dir='.')
    in_memory_osutils.filemap['./app.py'] = ''
    generated = app_policy.generate_policy_from_app_source(cfg)
    # We don't actually need to validate the exact policy, we'll just
    # check that it looks ok.
    assert 'Statement' in generated
    assert 'Version' in generated


def test_no_policy_generated_when_disabled_in_config(app_policy,
                                                     in_memory_osutils):
    previous_policy = '{"Statement": ["foo"]}'
    filename = os.path.join('.', '.chalice', 'policy.json')
    in_memory_osutils.filemap[filename] = previous_policy
    cfg = Config.create(autogen_policy=False, project_dir='.')
    generated = app_policy.generate_policy_from_app_source(cfg)
    assert generated == json.loads(previous_policy)


def test_load_last_policy_when_file_does_not_exist(app_policy):
    cfg = Config.create(project_dir='.')
    loaded = app_policy.load_last_policy(cfg)
    assert loaded == {
        "Statement": [],
        "Version": "2012-10-17",
    }


def test_load_policy_from_disk_when_file_exists(app_policy,
                                                in_memory_osutils):
    previous_policy = '{"Statement": ["foo"]}'
    filename = os.path.join('.', '.chalice', 'policy.json')
    in_memory_osutils.filemap[filename] = previous_policy
    cfg = Config.create(project_dir='.')
    loaded = app_policy.load_last_policy(cfg)
    assert loaded == json.loads(previous_policy)


def test_can_record_policy_to_disk(app_policy):
    cfg = Config.create(project_dir='.')
    latest_policy = {"Statement": ["policy"]}
    app_policy.record_policy(cfg, latest_policy)
    assert app_policy.load_last_policy(cfg) == latest_policy
