import json
import datetime
import time

from pytest import fixture
import pytest
import mock
import botocore.session
from botocore.stub import Stubber

from chalice.awsclient import TypedAWSClient


class StubbedSession(botocore.session.Session):
    def __init__(self, *args, **kwargs):
        super(StubbedSession, self).__init__(*args, **kwargs)
        self._cached_clients = {}
        self._client_stubs = {}

    def create_client(self, service_name, *args, **kwargs):
        if service_name not in self._cached_clients:
            client = self._create_stubbed_client(service_name, *args, **kwargs)
            self._cached_clients[service_name] = client
        return self._cached_clients[service_name]

    def _create_stubbed_client(self, service_name, *args, **kwargs):
        client = super(StubbedSession, self).create_client(
            service_name, *args, **kwargs)
        stubber = StubBuilder(Stubber(client))
        self._client_stubs[service_name] = stubber
        return client

    def stub(self, service_name):
        if service_name not in self._client_stubs:
            self.create_client(service_name)
        return self._client_stubs[service_name]

    def activate_stubs(self):
        for stub in self._client_stubs.values():
            stub.activate()

    def verify_stubs(self):
        for stub in self._client_stubs.values():
            stub.assert_no_pending_responses()


class StubBuilder(object):
    def __init__(self, stub):
        self.stub = stub
        self.activated = False
        self.pending_args = {}

    def __getattr__(self, name):
        if self.activated:
            # I want to be strict here to guide common test behavior.
            # This helps encourage the "record" "replay" "verify"
            # idiom in traditional mock frameworks.
            raise RuntimeError("Stub has already been activated: %s, "
                               "you must set up your stub calls before "
                               "calling .activate()" % self.stub)
        if not name.startswith('_'):
            # Assume it's an API call.
            self.pending_args['operation_name'] = name
            return self

    def assert_no_pending_responses(self):
        self.stub.assert_no_pending_responses()

    def activate(self):
        self.activated = True
        self.stub.activate()

    def returns(self, response):
        self.pending_args['service_response'] = response
        # returns() is essentially our "build()" method and triggers
        # creations of a stub response creation.
        p = self.pending_args
        self.stub.add_response(p['operation_name'],
                               expected_params=p['expected_params'],
                               service_response=p['service_response'])
        # And reset the pending_args for the next stub creation.
        self.pending_args = {}

    def raises_error(self, error_code, message):
        p = self.pending_args
        self.stub.add_client_error(p['operation_name'],
                                   service_error_code=error_code,
                                   service_message=message)
        # Reset pending args for next expectation.
        self.pending_args = {}

    def __call__(self, **kwargs):
        self.pending_args['expected_params'] = kwargs
        return self


@fixture
def stubbed_session():
    s = StubbedSession()
    return s


@fixture(autouse=True)
def set_region(monkeypatch):
    monkeypatch.setenv('AWS_DEFAULT_REGION', 'us-west-2')
    monkeypatch.setenv('AWS_ACCESS_KEY_ID', 'foo')
    monkeypatch.setenv('AWS_SECRET_ACCESS_KEY', 'bar')
    monkeypatch.delenv('AWS_PROFILE', raising=False)
    # Ensure that the existing ~/.aws/{config,credentials} file
    # don't influence test results.
    monkeypatch.setenv('AWS_CONFIG_FILE', '/tmp/asdfasdfaf/does/not/exist')
    monkeypatch.setenv('AWS_SHARED_CREDENTIALS_FILE',
                       '/tmp/asdfasdfaf/does/not/exist2')


def test_region_name_is_exposed(stubbed_session):
    assert TypedAWSClient(stubbed_session).region_name == 'us-west-2'


def test_deploy_rest_api(stubbed_session):
    stub_client = stubbed_session.stub('apigateway')
    stub_client.create_deployment(
        restApiId='api_id', stageName='stage').returns({})

    stubbed_session.activate_stubs()
    awsclient = TypedAWSClient(stubbed_session)
    awsclient.deploy_rest_api('api_id', 'stage')
    stubbed_session.verify_stubs()


def test_delete_resource_for_api(stubbed_session):
    stubbed_session.stub('apigateway').delete_resource(
        restApiId='api_id', resourceId='resource_id').returns({})
    stubbed_session.activate_stubs()
    awsclient = TypedAWSClient(stubbed_session)
    awsclient.delete_resource_for_api('api_id', 'resource_id')
    stubbed_session.verify_stubs()


def test_create_rest_api(stubbed_session):
    stubbed_session.stub('apigateway').create_rest_api(
        name='name').returns({'id': 'rest_api_id'})
    stubbed_session.activate_stubs()
    awsclient = TypedAWSClient(stubbed_session)
    assert awsclient.create_rest_api('name') == 'rest_api_id'
    stubbed_session.verify_stubs()


def test_update_function_code(stubbed_session):
    stubbed_session.stub('lambda').update_function_code(
        FunctionName='name', ZipFile=b'foo').returns({})
    stubbed_session.activate_stubs()
    awsclient = TypedAWSClient(stubbed_session)
    awsclient.update_function_code('name', b'foo')
    stubbed_session.verify_stubs()


def test_put_role_policy(stubbed_session):
    stubbed_session.stub('iam').put_role_policy(
        RoleName='role_name',
        PolicyName='policy_name',
        PolicyDocument=json.dumps({'foo': 'bar'}, indent=2)
    ).returns({})
    stubbed_session.activate_stubs()

    awsclient = TypedAWSClient(stubbed_session)
    awsclient.put_role_policy('role_name', 'policy_name', {'foo': 'bar'})

    stubbed_session.verify_stubs()


def test_get_resources_for_api(stubbed_session):
    expected = {
        'id': 'id',
        'parentId': 'parentId',
        'pathPart': '/foo',
        'path': '/foo',
        'resourceMethods': {},
    }
    stubbed_session.stub('apigateway').get_resources(
        restApiId='rest_api_id').returns({'items': [expected]})
    stubbed_session.activate_stubs()

    awsclient = TypedAWSClient(stubbed_session)
    result = awsclient.get_resources_for_api('rest_api_id')
    assert result == [expected]
    stubbed_session.verify_stubs()


def test_get_root_resource_for_api(stubbed_session):
    expected = {
        'id': 'id',
        'parentId': 'parentId',
        'pathPart': '/foo',
        'path': '/foo',
        'resourceMethods': {},
    }
    stubbed_session.stub('apigateway').get_resources(
        restApiId='rest_api_id').returns({'items': [expected]})

    stubbed_session.activate_stubs()
    awsclient = TypedAWSClient(stubbed_session)
    result = awsclient.get_root_resource_for_api('rest_api_id')
    assert result == expected
    stubbed_session.verify_stubs()


def test_delete_methods_from_root_resource(stubbed_session):
    resource_methods = {
        'GET': 'foo',
    }
    stubbed_session.stub('apigateway').delete_method(
        restApiId='rest_api_id',
        resourceId='resource_id',
        httpMethod='GET').returns({})

    stubbed_session.activate_stubs()
    awsclient = TypedAWSClient(stubbed_session)
    awsclient.delete_methods_from_root_resource(
        'rest_api_id', {'resourceMethods': resource_methods, 'id': 'resource_id'})
    stubbed_session.verify_stubs()


class TestLambdaFunctionExists(object):

    def test_can_query_lambda_function_exists(self, stubbed_session):
        stubbed_session.stub('lambda').get_function(FunctionName='myappname')\
                .returns({'Code': {}, 'Configuration': {}})

        stubbed_session.activate_stubs()

        awsclient = TypedAWSClient(stubbed_session)
        assert awsclient.lambda_function_exists(name='myappname')

        stubbed_session.verify_stubs()

    def test_can_query_lambda_function_does_not_exist(self, stubbed_session):
        stubbed_session.stub('lambda').get_function(FunctionName='myappname')\
                .raises_error(error_code='ResourceNotFoundException',
                              message='ResourceNotFound')

        stubbed_session.activate_stubs()

        awsclient = TypedAWSClient(stubbed_session)
        assert not awsclient.lambda_function_exists(name='myappname')

        stubbed_session.verify_stubs()

    def test_lambda_function_bad_error_propagates(self, stubbed_session):
        stubbed_session.stub('lambda').get_function(FunctionName='myappname')\
                .raises_error(error_code='UnexpectedError',
                              message='Unknown')

        stubbed_session.activate_stubs()

        awsclient = TypedAWSClient(stubbed_session)
        with pytest.raises(botocore.exceptions.ClientError):
            awsclient.lambda_function_exists(name='myappname')

        stubbed_session.verify_stubs()


class TestGetRestAPI(object):
    def test_rest_api_exists(self, stubbed_session):
        desired_name = 'myappname'
        stubbed_session.stub('apigateway').get_rest_apis()\
            .returns(
                {'items': [
                    {'createdDate': 1, 'id': 'wrongid1', 'name': 'wrong1'},
                    {'createdDate': 2, 'id': 'correct', 'name': desired_name},
                    {'createdDate': 3, 'id': 'wrongid3', 'name': 'wrong3'},
                ]})
        stubbed_session.activate_stubs()
        awsclient = TypedAWSClient(stubbed_session)
        assert awsclient.get_rest_api_id(desired_name) == 'correct'
        stubbed_session.verify_stubs()

    def test_rest_api_does_not_exist(self, stubbed_session):
        stubbed_session.stub('apigateway').get_rest_apis()\
            .returns(
                {'items': [
                    {'createdDate': 1, 'id': 'wrongid1', 'name': 'wrong1'},
                    {'createdDate': 2, 'id': 'wrongid1', 'name': 'wrong2'},
                    {'createdDate': 3, 'id': 'wrongid3', 'name': 'wrong3'},
                ]})
        stubbed_session.activate_stubs()
        awsclient = TypedAWSClient(stubbed_session)
        assert awsclient.get_rest_api_id('myappname') is None
        stubbed_session.verify_stubs()


class TestGetRoleArn(object):
    def test_get_role_arn_for_name_found(self, stubbed_session):
        # Need len(20) to pass param validation.
        good_arn = 'good_arn' * 3
        bad_arn = 'bad_arn' * 3
        role_id = 'abcd' * 4
        today = datetime.datetime.today()
        stubbed_session.stub('iam').list_roles().returns({
            'Roles': [
                {'RoleName': 'No', 'Arn': bad_arn, 'Path': '/',
                 'RoleId': role_id, 'CreateDate': today},
                {'RoleName': 'Yes', 'Arn': good_arn,'Path': '/',
                 'RoleId': role_id, 'CreateDate': today},
                {'RoleName': 'No2', 'Arn': bad_arn, 'Path': '/',
                 'RoleId': role_id, 'CreateDate': today},
            ]
        })
        stubbed_session.activate_stubs()
        awsclient = TypedAWSClient(stubbed_session)
        assert awsclient.get_role_arn_for_name(name='Yes') == good_arn
        stubbed_session.verify_stubs()

    def test_got_role_arn_not_found_raises_value_error(self, stubbed_session):
        bad_arn = 'bad_arn' * 3
        role_id = 'abcd' * 4
        today = datetime.datetime.today()
        stubbed_session.stub('iam').list_roles().returns({
            'Roles': [
                {'RoleName': 'No', 'Arn': bad_arn, 'Path': '/',
                 'RoleId': role_id, 'CreateDate': today},
                {'RoleName': 'No2', 'Arn': bad_arn, 'Path': '/',
                 'RoleId': role_id, 'CreateDate': today},
            ]
        })
        stubbed_session.activate_stubs()
        awsclient = TypedAWSClient(stubbed_session)
        with pytest.raises(ValueError):
            awsclient.get_role_arn_for_name(name='Yes')
        stubbed_session.verify_stubs()


class TestCreateRole(object):
    def test_create_role(self, stubbed_session):
        arn = 'good_arn' * 3
        role_id = 'abcd' * 4
        today = datetime.datetime.today()
        stubbed_session.stub('iam').create_role(
            RoleName='role_name',
            AssumeRolePolicyDocument=json.dumps({'trust': 'policy'})
        ).returns({'Role': {
            'RoleName': 'No', 'Arn': arn, 'Path': '/',
            'RoleId': role_id, 'CreateDate': today}}
        )
        stubbed_session.stub('iam').put_role_policy(
            RoleName='role_name',
            PolicyName='role_name',
            PolicyDocument=json.dumps({'policy': 'document'}, indent=2)
        ).returns({})
        stubbed_session.activate_stubs()
        awsclient = TypedAWSClient(stubbed_session)
        actual = awsclient.create_role(
            'role_name', {'trust': 'policy'}, {'policy': 'document'})
        assert actual == arn
        stubbed_session.verify_stubs()


class TestCreateLambdaFunction(object):

    def test_create_function_succeeds_first_try(self, stubbed_session):
        stubbed_session.stub('lambda').create_function(
            FunctionName='name',
            Runtime='python2.7',
            Code={'ZipFile': b'foo'},
            Handler='app.app',
            Role='myarn',
            Timeout=60,
        ).returns({'FunctionArn': 'arn:12345:name'})
        stubbed_session.activate_stubs()
        awsclient = TypedAWSClient(stubbed_session)
        assert awsclient.create_function(
            'name', 'myarn', b'foo') == 'arn:12345:name'
        stubbed_session.verify_stubs()

    def test_create_function_is_retried_and_succeeds(self, stubbed_session):
        kwargs = {
            'FunctionName': 'name',
            'Runtime': 'python2.7',
            'Code': {'ZipFile': b'foo'},
            'Handler': 'app.app',
            'Role': 'myarn',
            'Timeout': 60,
        }
        stubbed_session.stub('lambda').create_function(
            **kwargs).raises_error(
            error_code='InvalidParameterValueException', message='')
        stubbed_session.stub('lambda').create_function(
            **kwargs).raises_error(
            error_code='InvalidParameterValueException', message='')
        stubbed_session.stub('lambda').create_function(
            **kwargs).returns({'FunctionArn': 'arn:12345:name'})
        stubbed_session.activate_stubs()
        awsclient = TypedAWSClient(stubbed_session, mock.Mock(spec=time.sleep))
        assert awsclient.create_function(
            'name', 'myarn', b'foo') == 'arn:12345:name'
        stubbed_session.verify_stubs()

    def test_create_function_fails_after_max_retries(self, stubbed_session):
        kwargs = {
            'FunctionName': 'name',
            'Runtime': 'python2.7',
            'Code': {'ZipFile': b'foo'},
            'Handler': 'app.app',
            'Role': 'myarn',
            'Timeout': 60,
        }
        for _ in range(5):
            stubbed_session.stub('lambda').create_function(
                **kwargs).raises_error(
                error_code='InvalidParameterValueException', message='')

        stubbed_session.activate_stubs()
        awsclient = TypedAWSClient(stubbed_session, mock.Mock(spec=time.sleep))
        with pytest.raises(botocore.exceptions.ClientError):
            awsclient.create_function('name', 'myarn', b'foo')
        stubbed_session.verify_stubs()

    def test_create_function_propagates_unknown_error(self, stubbed_session):
        kwargs = {
            'FunctionName': 'name',
            'Runtime': 'python2.7',
            'Code': {'ZipFile': b'foo'},
            'Handler': 'app.app',
            'Role': 'myarn',
            'Timeout': 60,
        }
        stubbed_session.stub('lambda').create_function(
            **kwargs).raises_error(
            error_code='UnknownException', message='')
        stubbed_session.activate_stubs()
        awsclient = TypedAWSClient(stubbed_session, mock.Mock(spec=time.sleep))
        with pytest.raises(botocore.exceptions.ClientError):
            awsclient.create_function('name', 'myarn', b'foo')
        stubbed_session.verify_stubs()


class TestCanDeleteRolePolicy(object):
    def test_can_delete_role_policy(self, stubbed_session):
        stubbed_session.stub('iam').delete_role_policy(
            RoleName='myrole', PolicyName='mypolicy'
        ).returns({})
        stubbed_session.activate_stubs()
        awsclient = TypedAWSClient(stubbed_session)
        awsclient.delete_role_policy('myrole', 'mypolicy')
        stubbed_session.verify_stubs()
