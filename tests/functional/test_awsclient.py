import json
import datetime
import time

import pytest
import mock
import botocore.exceptions

from chalice.awsclient import TypedAWSClient


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


def test_always_update_function_code(stubbed_session):
    lambda_client = stubbed_session.stub('lambda')
    lambda_client.update_function_code(
        FunctionName='name', ZipFile=b'foo').returns({})
    # Even if there's only a code change, we'll always call
    # update_function_configuration.
    lambda_client.update_function_configuration(
        FunctionName='name', Environment={'Variables': {}}).returns({})
    stubbed_session.activate_stubs()
    awsclient = TypedAWSClient(stubbed_session)
    awsclient.update_function('name', b'foo')
    stubbed_session.verify_stubs()


def test_update_function_code_and_deploy(stubbed_session):
    lambda_client = stubbed_session.stub('lambda')
    lambda_client.update_function_code(
        FunctionName='name', ZipFile=b'foo').returns({})
    lambda_client.update_function_configuration(
        FunctionName='name',
        Environment={'Variables': {"FOO": "BAR"}}).returns({})
    stubbed_session.activate_stubs()
    awsclient = TypedAWSClient(stubbed_session)
    awsclient.update_function(
        'name', b'foo', {"FOO": "BAR"})
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


def test_rest_api_exists(stubbed_session):
    stubbed_session.stub('apigateway').get_rest_api(
        restApiId='api').returns({})
    stubbed_session.activate_stubs()

    awsclient = TypedAWSClient(stubbed_session)
    assert awsclient.rest_api_exists('api')

    stubbed_session.verify_stubs()


def test_rest_api_not_exists(stubbed_session):
    stubbed_session.stub('apigateway').get_rest_api(
        restApiId='api').raises_error(
            error_code='NotFoundException',
            message='ResourceNotFound')
    stubbed_session.activate_stubs()

    awsclient = TypedAWSClient(stubbed_session)
    assert not awsclient.rest_api_exists('api')

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
        role_id = 'abcd' * 4
        today = datetime.datetime.today()
        stubbed_session.stub('iam').get_role(RoleName='Yes').returns({
            'Role': {
                'Path': '/',
                'RoleName': 'Yes',
                'RoleId': role_id,
                'CreateDate': today,
                'Arn': good_arn
            }
        })
        stubbed_session.activate_stubs()
        awsclient = TypedAWSClient(stubbed_session)
        assert awsclient.get_role_arn_for_name(name='Yes') == good_arn
        stubbed_session.verify_stubs()

    def test_got_role_arn_not_found_raises_value_error(self, stubbed_session):
        stubbed_session.stub('iam').get_role(RoleName='Yes').raises_error(
            error_code='NoSuchEntity',
            message='Foo')
        stubbed_session.activate_stubs()
        awsclient = TypedAWSClient(stubbed_session)
        with pytest.raises(ValueError):
            awsclient.get_role_arn_for_name(name='Yes')
        stubbed_session.verify_stubs()

    def test_unexpected_error_is_propagated(self, stubbed_session):
        stubbed_session.stub('iam').get_role(RoleName='Yes').raises_error(
            error_code='InternalError',
            message='Foo')
        stubbed_session.activate_stubs()
        awsclient = TypedAWSClient(stubbed_session)
        with pytest.raises(botocore.exceptions.ClientError):
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
            Environment={'Variables': {'FOO': 'BAR'}},
        ).returns({'FunctionArn': 'arn:12345:name'})
        stubbed_session.activate_stubs()
        awsclient = TypedAWSClient(stubbed_session)
        assert awsclient.create_function(
            'name', 'myarn', b'foo', {'FOO': 'BAR'}) == 'arn:12345:name'
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
        for _ in range(TypedAWSClient.LAMBDA_CREATE_ATTEMPTS):
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


class TestAddPermissionsForAPIGateway(object):
    def test_can_add_permission_for_apigateway(self, stubbed_session):
        stubbed_session.stub('lambda').add_permission(
            Action='lambda:InvokeFunction',
            FunctionName='function_name',
            StatementId='random-id',
            Principal='apigateway.amazonaws.com',
            SourceArn='arn:aws:execute-api:us-west-2:123:rest-api-id/*',
        ).returns({})
        stubbed_session.activate_stubs()
        TypedAWSClient(stubbed_session).add_permission_for_apigateway(
            'function_name', 'us-west-2', '123', 'rest-api-id', 'random-id')
        stubbed_session.verify_stubs()

    def should_call_add_permission(self, lambda_stub):
        lambda_stub.add_permission(
            Action='lambda:InvokeFunction',
            FunctionName='name',
            StatementId='random-id',
            Principal='apigateway.amazonaws.com',
            SourceArn='arn:aws:execute-api:us-west-2:123:rest-api-id/*',
        ).returns({})

    def test_can_add_permission_for_apigateway_needed(self, stubbed_session):
        # An empty policy means we need to add permissions.
        lambda_stub = stubbed_session.stub('lambda')
        lambda_stub.get_policy(FunctionName='name').returns({'Policy': '{}'})
        self.should_call_add_permission(lambda_stub)
        stubbed_session.activate_stubs()
        TypedAWSClient(stubbed_session).add_permission_for_apigateway_if_needed(
            'name', 'us-west-2', '123', 'rest-api-id', 'random-id')
        stubbed_session.verify_stubs()

    def test_can_add_permission_for_apigateway_not_needed(self, stubbed_session):
        source_arn = 'arn:aws:execute-api:us-west-2:123:rest-api-id/*'
        policy = {
            'Id': 'default',
            'Statement': [{
                'Action': 'lambda:InvokeFunction',
                'Condition': {
                    'ArnLike': {
                        'AWS:SourceArn': source_arn,
                    }
                },
                'Effect': 'Allow',
                'Principal': {'Service': 'apigateway.amazonaws.com'},
                'Resource': 'arn:aws:lambda:us-west-2:account_id:function:name',
                'Sid': 'e4755709-067e-4254-b6ec-e7f9639e6f7b'}],
            'Version': '2012-10-17'
        }
        stubbed_session.stub('lambda').get_policy(
            FunctionName='name').returns({'Policy': json.dumps(policy)})

        # Because the policy above indicates that API gateway already has the
        # necessary permissions, we should not call add_permission.
        stubbed_session.activate_stubs()
        TypedAWSClient(stubbed_session).add_permission_for_apigateway_if_needed(
            'name', 'us-west-2', '123', 'rest-api-id', 'random-id')
        stubbed_session.verify_stubs()

    def test_can_add_permission_when_policy_does_not_exist(self, stubbed_session):
        # It's also possible to receive a ResourceNotFoundException
        # if you call get_policy() on a lambda function with no policy.
        lambda_stub = stubbed_session.stub('lambda')
        lambda_stub.get_policy(FunctionName='name').raises_error(
            error_code='ResourceNotFoundException', message='Does not exist.')
        self.should_call_add_permission(lambda_stub)
        stubbed_session.activate_stubs()
        TypedAWSClient(stubbed_session).add_permission_for_apigateway_if_needed(
            'name', 'us-west-2', '123', 'rest-api-id', 'random-id')
        stubbed_session.verify_stubs()

    def test_get_sdk(self, stubbed_session):
        apig = stubbed_session.stub('apigateway')
        apig.get_sdk(
            restApiId='rest-api-id',
            stageName='dev',
            sdkType='javascript').returns({'body': 'foo'})
        stubbed_session.activate_stubs()
        awsclient = TypedAWSClient(stubbed_session)
        response = awsclient.get_sdk_download_stream(
            'rest-api-id', 'dev', 'javascript')
        stubbed_session.verify_stubs()
        assert response == 'foo'

    def test_import_rest_api(self, stubbed_session):
        apig = stubbed_session.stub('apigateway')
        swagger_doc = {'swagger': 'doc'}
        apig.import_rest_api(
            body=json.dumps(swagger_doc, indent=2)).returns(
                {'id': 'rest_api_id'})

        stubbed_session.activate_stubs()
        awsclient = TypedAWSClient(stubbed_session)
        rest_api_id = awsclient.import_rest_api(swagger_doc)
        stubbed_session.verify_stubs()
        assert rest_api_id == 'rest_api_id'

    def test_update_api_from_swagger(self, stubbed_session):
        apig = stubbed_session.stub('apigateway')
        swagger_doc = {'swagger': 'doc'}
        apig.put_rest_api(
            restApiId='rest_api_id',
            body=json.dumps(swagger_doc, indent=2)).returns({})

        stubbed_session.activate_stubs()
        awsclient = TypedAWSClient(stubbed_session)

        awsclient.update_api_from_swagger('rest_api_id',
                                          swagger_doc)
        stubbed_session.verify_stubs()
