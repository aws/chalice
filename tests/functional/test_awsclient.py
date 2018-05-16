import json
import datetime
import time

import pytest
import mock
import botocore.exceptions
from botocore.vendored.requests import ConnectionError as \
    RequestsConnectionError
from botocore import stub

from chalice.awsclient import TypedAWSClient
from chalice.awsclient import ResourceDoesNotExistError
from chalice.awsclient import DeploymentPackageTooLargeError
from chalice.awsclient import LambdaClientError


class FixedIDTypedAWSClient(TypedAWSClient):
    def __init__(self, session, random_id):
        super(FixedIDTypedAWSClient, self).__init__(session)
        self._fixed_random_id = random_id

    def _random_id(self):
        return self._fixed_random_id


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


def test_can_get_function_configuration(stubbed_session):
    stubbed_session.stub('lambda').get_function_configuration(
        FunctionName='myfunction',
    ).returns({
        "FunctionName": "myfunction",
        "MemorySize": 128,
        "Handler": "app.app",
        "Runtime": "python3.6",
    })

    stubbed_session.activate_stubs()
    awsclient = TypedAWSClient(stubbed_session)
    assert (awsclient.get_function_configuration('myfunction')['Runtime'] ==
            'python3.6')


def test_can_iterate_logs(stubbed_session):
    stubbed_session.stub('logs').filter_log_events(
        logGroupName='loggroup', interleaved=True).returns({
            "events": [{
                "logStreamName": "logStreamName",
                "timestamp": 1501278366000,
                "message": "message",
                "ingestionTime": 1501278366000,
                "eventId": "eventId"
            }],
        })

    stubbed_session.activate_stubs()

    awsclient = TypedAWSClient(stubbed_session)
    logs = list(awsclient.iter_log_events('loggroup'))
    timestamp = datetime.datetime.fromtimestamp(1501278366)
    assert logs == [
        {'logStreamName': 'logStreamName',
         # We should have converted the ints to timestamps.
         'timestamp': timestamp,
         'message': 'message',
         'ingestionTime': timestamp,
         'eventId': 'eventId'}
    ]

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


class TestDeleteLambdaFunction(object):
    def test_lambda_delete_function(self, stubbed_session):
        stubbed_session.stub('lambda')\
                       .delete_function(FunctionName='name').returns({})
        stubbed_session.activate_stubs()
        awsclient = TypedAWSClient(stubbed_session)
        assert awsclient.delete_function('name') is None
        stubbed_session.verify_stubs()

    def test_lambda_delete_function_already_deleted(self, stubbed_session):
        stubbed_session.stub('lambda')\
                       .delete_function(FunctionName='name')\
                       .raises_error(error_code='ResourceNotFoundException',
                                     message='Unknown')
        stubbed_session.activate_stubs()

        awsclient = TypedAWSClient(stubbed_session)
        with pytest.raises(ResourceDoesNotExistError):
            assert awsclient.delete_function('name')


class TestDeleteRestAPI(object):
    def test_rest_api_delete(self, stubbed_session):
        stubbed_session.stub('apigateway')\
                       .delete_rest_api(restApiId='name').returns({})
        stubbed_session.activate_stubs()
        awsclient = TypedAWSClient(stubbed_session)
        assert awsclient.delete_rest_api('name') is None
        stubbed_session.verify_stubs()

    def test_rest_api_delete_already_deleted(self, stubbed_session):
        stubbed_session.stub('apigateway')\
                       .delete_rest_api(restApiId='name')\
                       .raises_error(error_code='NotFoundException',
                                     message='Unknown')
        stubbed_session.activate_stubs()

        awsclient = TypedAWSClient(stubbed_session)
        with pytest.raises(ResourceDoesNotExistError):
            assert awsclient.delete_rest_api('name')


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
        with pytest.raises(ResourceDoesNotExistError):
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


class TestGetRole(object):
    def test_get_role_success(self, stubbed_session):
        today = datetime.datetime.today()
        response = {
            'Role': {
                'Path': '/',
                'RoleName': 'Yes',
                'RoleId': 'abcd' * 4,
                'CreateDate': today,
                'Arn': 'good_arn' * 3,
            }
        }
        stubbed_session.stub('iam').get_role(RoleName='Yes').returns(response)
        stubbed_session.activate_stubs()
        awsclient = TypedAWSClient(stubbed_session)
        actual = awsclient.get_role(name='Yes')
        assert actual == response['Role']
        stubbed_session.verify_stubs()

    def test_get_role_raises_exception_when_no_exists(self, stubbed_session):
        stubbed_session.stub('iam').get_role(RoleName='Yes').raises_error(
            error_code='NoSuchEntity',
            message='Foo')
        stubbed_session.activate_stubs()
        awsclient = TypedAWSClient(stubbed_session)
        with pytest.raises(ResourceDoesNotExistError):
            awsclient.get_role(name='Yes')
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

    def test_create_role_raises_error_on_failure(self, stubbed_session):
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
            PolicyDocument={'policy': 'document'}
        ).raises_error(
            error_code='MalformedPolicyDocumentException',
            message='MalformedPolicyDocument'
        )
        stubbed_session.activate_stubs()
        awsclient = TypedAWSClient(stubbed_session)
        with pytest.raises(botocore.exceptions.ClientError):
            awsclient.create_role(
                'role_name', {'trust': 'policy'}, {'policy': 'document'})
        stubbed_session.verify_stubs()


class TestCreateLambdaFunction(object):
    def test_create_function_succeeds_first_try(self, stubbed_session):
        stubbed_session.stub('lambda').create_function(
            FunctionName='name',
            Runtime='python2.7',
            Code={'ZipFile': b'foo'},
            Handler='app.app',
            Role='myarn'
        ).returns({'FunctionArn': 'arn:12345:name'})
        stubbed_session.activate_stubs()
        awsclient = TypedAWSClient(stubbed_session)
        assert awsclient.create_function(
            'name', 'myarn', b'foo',
            'python2.7', 'app.app') == 'arn:12345:name'
        stubbed_session.verify_stubs()

    def test_create_function_with_non_python2_runtime(self, stubbed_session):
        stubbed_session.stub('lambda').create_function(
            FunctionName='name',
            Runtime='python3.6',
            Code={'ZipFile': b'foo'},
            Handler='app.app',
            Role='myarn',
        ).returns({'FunctionArn': 'arn:12345:name'})
        stubbed_session.activate_stubs()
        awsclient = TypedAWSClient(stubbed_session)
        assert awsclient.create_function(
            'name', 'myarn', b'foo', runtime='python3.6',
            handler='app.app') == 'arn:12345:name'
        stubbed_session.verify_stubs()

    def test_create_function_with_environment_variables(self, stubbed_session):
        stubbed_session.stub('lambda').create_function(
            FunctionName='name',
            Runtime='python2.7',
            Code={'ZipFile': b'foo'},
            Handler='app.app',
            Role='myarn',
            Environment={'Variables': {'FOO': 'BAR'}}
        ).returns({'FunctionArn': 'arn:12345:name'})
        stubbed_session.activate_stubs()
        awsclient = TypedAWSClient(stubbed_session)
        assert awsclient.create_function(
            'name', 'myarn', b'foo', 'python2.7',
            handler='app.app',
            environment_variables={'FOO': 'BAR'}) == 'arn:12345:name'
        stubbed_session.verify_stubs()

    def test_create_function_with_tags(self, stubbed_session):
        stubbed_session.stub('lambda').create_function(
            FunctionName='name',
            Runtime='python2.7',
            Code={'ZipFile': b'foo'},
            Handler='app.app',
            Role='myarn',
            Timeout=240
        ).returns({'FunctionArn': 'arn:12345:name'})
        stubbed_session.activate_stubs()
        awsclient = TypedAWSClient(stubbed_session)
        assert awsclient.create_function(
            'name', 'myarn', b'foo', 'python2.7', 'app.app',
            timeout=240) == 'arn:12345:name'
        stubbed_session.verify_stubs()

    def test_create_function_with_timeout(self, stubbed_session):
        stubbed_session.stub('lambda').create_function(
            FunctionName='name',
            Runtime='python2.7',
            Code={'ZipFile': b'foo'},
            Handler='app.app',
            Role='myarn',
            Tags={'mykey': 'myvalue'}
        ).returns({'FunctionArn': 'arn:12345:name'})
        stubbed_session.activate_stubs()
        awsclient = TypedAWSClient(stubbed_session)
        assert awsclient.create_function(
            'name', 'myarn', b'foo', 'python2.7', 'app.app',
            tags={'mykey': 'myvalue'}) == 'arn:12345:name'
        stubbed_session.verify_stubs()

    def test_create_function_with_memory_size(self, stubbed_session):
        stubbed_session.stub('lambda').create_function(
            FunctionName='name',
            Runtime='python2.7',
            Code={'ZipFile': b'foo'},
            Handler='app.app',
            Role='myarn',
            MemorySize=256
        ).returns({'FunctionArn': 'arn:12345:name'})
        stubbed_session.activate_stubs()
        awsclient = TypedAWSClient(stubbed_session)
        assert awsclient.create_function(
            'name', 'myarn', b'foo', 'python2.7', 'app.app',
            memory_size=256) == 'arn:12345:name'
        stubbed_session.verify_stubs()

    def test_create_function_with_vpc_config(self, stubbed_session):
        stubbed_session.stub('lambda').create_function(
            FunctionName='name',
            Runtime='python2.7',
            Code={'ZipFile': b'foo'},
            Handler='app.app',
            Role='myarn',
            VpcConfig={
                'SecurityGroupIds': ['sg1', 'sg2'],
                'SubnetIds': ['sn1', 'sn2']
            }
        ).returns({'FunctionArn': 'arn:12345:name'})
        stubbed_session.activate_stubs()
        awsclient = TypedAWSClient(stubbed_session)
        assert awsclient.create_function(
            'name', 'myarn', b'foo', 'python2.7', 'app.app',
            subnet_ids=['sn1', 'sn2'],
            security_group_ids=['sg1', 'sg2'],
            ) == 'arn:12345:name'
        stubbed_session.verify_stubs()

    def test_create_function_is_retried_and_succeeds(self, stubbed_session):
        kwargs = {
            'FunctionName': 'name',
            'Runtime': 'python2.7',
            'Code': {'ZipFile': b'foo'},
            'Handler': 'app.app',
            'Role': 'myarn',
        }
        stubbed_session.stub('lambda').create_function(
            **kwargs).raises_error(
            error_code='InvalidParameterValueException',
            message=('The role defined for the function cannot '
                     'be assumed by Lambda.'))
        stubbed_session.stub('lambda').create_function(
            **kwargs).raises_error(
            error_code='InvalidParameterValueException',
            message=('The role defined for the function cannot '
                     'be assumed by Lambda.'))
        stubbed_session.stub('lambda').create_function(
            **kwargs).returns({'FunctionArn': 'arn:12345:name'})
        stubbed_session.activate_stubs()
        awsclient = TypedAWSClient(stubbed_session, mock.Mock(spec=time.sleep))
        assert awsclient.create_function(
            'name', 'myarn', b'foo',
            'python2.7', 'app.app') == 'arn:12345:name'
        stubbed_session.verify_stubs()

    def test_retry_happens_on_insufficient_permissions(self, stubbed_session):
        # This can happen if we deploy a lambda in a VPC.  Instead of the role
        # not being able to be assumed, we can instead not have permissions
        # to modify ENIs.  These can be retried.
        kwargs = {
            'FunctionName': 'name',
            'Runtime': 'python2.7',
            'Code': {'ZipFile': b'foo'},
            'Handler': 'app.app',
            'Role': 'myarn',
            'VpcConfig': {'SubnetIds': ['sn-1'],
                          'SecurityGroupIds': ['sg-1']},
        }
        stubbed_session.stub('lambda').create_function(
            **kwargs).raises_error(
            error_code='InvalidParameterValueException',
            message=('The provided execution role does not have permissions '
                     'to call CreateNetworkInterface on EC2 be assumed by '
                     'Lambda.'))
        stubbed_session.stub('lambda').create_function(
            **kwargs).returns({'FunctionArn': 'arn:12345:name'})
        stubbed_session.activate_stubs()
        awsclient = TypedAWSClient(stubbed_session, mock.Mock(spec=time.sleep))
        assert awsclient.create_function(
            'name', 'myarn', b'foo',
            'python2.7', 'app.app', security_group_ids=['sg-1'],
            subnet_ids=['sn-1']) == 'arn:12345:name'
        stubbed_session.verify_stubs()

    def test_create_function_fails_after_max_retries(self, stubbed_session):
        kwargs = {
            'FunctionName': 'name',
            'Runtime': 'python2.7',
            'Code': {'ZipFile': b'foo'},
            'Handler': 'app.app',
            'Role': 'myarn',
        }
        for _ in range(TypedAWSClient.LAMBDA_CREATE_ATTEMPTS):
            stubbed_session.stub('lambda').create_function(
                **kwargs).raises_error(
                error_code='InvalidParameterValueException',
                message=('The role defined for the function cannot '
                         'be assumed by Lambda.')
                )

        stubbed_session.activate_stubs()
        awsclient = TypedAWSClient(stubbed_session, mock.Mock(spec=time.sleep))
        with pytest.raises(LambdaClientError) as excinfo:
            awsclient.create_function('name', 'myarn', b'foo', 'python2.7',
                                      'app.app')
        assert isinstance(
            excinfo.value.original_error, botocore.exceptions.ClientError)
        stubbed_session.verify_stubs()

    def test_can_pass_python_runtime(self, stubbed_session):
        stubbed_session.stub('lambda').create_function(
            FunctionName='name',
            Runtime='python3.6',
            Code={'ZipFile': b'foo'},
            Handler='app.app',
            Role='myarn',
        ).returns({'FunctionArn': 'arn:12345:name'})
        stubbed_session.activate_stubs()
        awsclient = TypedAWSClient(stubbed_session)
        assert awsclient.create_function(
            'name', 'myarn', b'foo',
            runtime='python3.6', handler='app.app') == 'arn:12345:name'
        stubbed_session.verify_stubs()

    def test_create_function_propagates_unknown_error(self, stubbed_session):
        kwargs = {
            'FunctionName': 'name',
            'Runtime': 'python2.7',
            'Code': {'ZipFile': b'foo'},
            'Handler': 'app.app',
            'Role': 'myarn',
        }
        stubbed_session.stub('lambda').create_function(
            **kwargs).raises_error(
            error_code='UnknownException', message='')
        stubbed_session.activate_stubs()
        awsclient = TypedAWSClient(stubbed_session, mock.Mock(spec=time.sleep))
        with pytest.raises(LambdaClientError) as excinfo:
            awsclient.create_function('name', 'myarn', b'foo', 'pytohn2.7',
                                      'app.app')
        assert isinstance(
            excinfo.value.original_error, botocore.exceptions.ClientError)
        stubbed_session.verify_stubs()

    def test_can_provide_tags(self, stubbed_session):
        stubbed_session.stub('lambda').create_function(
            FunctionName='name',
            Runtime='python2.7',
            Code={'ZipFile': b'foo'},
            Handler='app.app',
            Role='myarn',
            Tags={'key': 'value'},
        ).returns({'FunctionArn': 'arn:12345:name'})
        stubbed_session.activate_stubs()
        awsclient = TypedAWSClient(stubbed_session)
        assert awsclient.create_function(
            function_name='name',
            role_arn='myarn',
            zip_contents=b'foo',
            runtime='python2.7',
            tags={'key': 'value'},
            handler='app.app') == 'arn:12345:name'
        stubbed_session.verify_stubs()

    def test_raises_large_deployment_error_for_connection_error(
            self, stubbed_session):
        too_large_content = b'a' * 60 * (1024 ** 2)
        kwargs = {
            'FunctionName': 'name',
            'Runtime': 'python2.7',
            'Code': {'ZipFile': too_large_content},
            'Handler': 'app.app',
            'Role': 'myarn',
        }

        stubbed_session.stub('lambda').create_function(
            **kwargs).raises_error(error=RequestsConnectionError())
        stubbed_session.activate_stubs()
        awsclient = TypedAWSClient(stubbed_session, mock.Mock(spec=time.sleep))
        with pytest.raises(DeploymentPackageTooLargeError) as excinfo:
            awsclient.create_function('name', 'myarn', too_large_content,
                                      'python2.7', 'app.app')
        stubbed_session.verify_stubs()
        assert excinfo.value.context.function_name == 'name'
        assert excinfo.value.context.client_method_name == 'create_function'
        assert excinfo.value.context.deployment_size == 60 * (1024 ** 2)

    def test_no_raise_large_deployment_error_when_small_deployment_size(
            self, stubbed_session):
        kwargs = {
            'FunctionName': 'name',
            'Runtime': 'python2.7',
            'Code': {'ZipFile': b'foo'},
            'Handler': 'app.app',
            'Role': 'myarn',
        }

        stubbed_session.stub('lambda').create_function(
            **kwargs).raises_error(error=RequestsConnectionError())
        stubbed_session.activate_stubs()
        awsclient = TypedAWSClient(stubbed_session, mock.Mock(spec=time.sleep))
        with pytest.raises(LambdaClientError) as excinfo:
            awsclient.create_function('name', 'myarn', b'foo',
                                      'python2.7', 'app.app')
        stubbed_session.verify_stubs()
        assert not isinstance(excinfo.value, DeploymentPackageTooLargeError)
        assert isinstance(
            excinfo.value.original_error, RequestsConnectionError)

    def test_raises_large_deployment_error_request_entity_to_large(
            self, stubbed_session):
        kwargs = {
            'FunctionName': 'name',
            'Runtime': 'python2.7',
            'Code': {'ZipFile': b'foo'},
            'Handler': 'app.app',
            'Role': 'myarn',
        }
        stubbed_session.stub('lambda').create_function(
            **kwargs).raises_error(
                error_code='RequestEntityTooLargeException',
                message='')
        stubbed_session.activate_stubs()
        awsclient = TypedAWSClient(stubbed_session, mock.Mock(spec=time.sleep))
        with pytest.raises(DeploymentPackageTooLargeError):
            awsclient.create_function('name', 'myarn', b'foo', 'python2.7',
                                      'app.app')
        stubbed_session.verify_stubs()

    def test_raises_large_deployment_error_for_too_large_unzip(
            self, stubbed_session):
        kwargs = {
            'FunctionName': 'name',
            'Runtime': 'python2.7',
            'Code': {'ZipFile': b'foo'},
            'Handler': 'app.app',
            'Role': 'myarn',
        }
        stubbed_session.stub('lambda').create_function(
            **kwargs).raises_error(
                error_code='InvalidParameterValueException',
                message='Unzipped size must be smaller than ...')
        stubbed_session.activate_stubs()
        awsclient = TypedAWSClient(stubbed_session, mock.Mock(spec=time.sleep))
        with pytest.raises(DeploymentPackageTooLargeError):
            awsclient.create_function('name', 'myarn', b'foo', 'python2.7',
                                      'app.app')
        stubbed_session.verify_stubs()


class TestUpdateLambdaFunction(object):
    def test_always_update_function_code(self, stubbed_session):
        lambda_client = stubbed_session.stub('lambda')
        lambda_client.update_function_code(
            FunctionName='name', ZipFile=b'foo').returns({})
        stubbed_session.activate_stubs()
        awsclient = TypedAWSClient(stubbed_session)
        awsclient.update_function('name', b'foo')
        stubbed_session.verify_stubs()

    def test_update_function_code_with_runtime(self, stubbed_session):
        lambda_client = stubbed_session.stub('lambda')
        lambda_client.update_function_code(
            FunctionName='name', ZipFile=b'foo').returns({})
        lambda_client.update_function_configuration(
            FunctionName='name',
            Runtime='python3.6').returns({})
        stubbed_session.activate_stubs()
        awsclient = TypedAWSClient(stubbed_session)
        awsclient.update_function('name', b'foo', runtime='python3.6')
        stubbed_session.verify_stubs()

    def test_update_function_code_with_environment_vars(self, stubbed_session):
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

    def test_update_function_code_with_timeout(self, stubbed_session):
        lambda_client = stubbed_session.stub('lambda')
        lambda_client.update_function_code(
            FunctionName='name', ZipFile=b'foo').returns({})
        lambda_client.update_function_configuration(
            FunctionName='name',
            Timeout=240).returns({})
        stubbed_session.activate_stubs()
        awsclient = TypedAWSClient(stubbed_session)
        awsclient.update_function('name', b'foo', timeout=240)
        stubbed_session.verify_stubs()

    def test_update_function_code_with_memory(self, stubbed_session):
        lambda_client = stubbed_session.stub('lambda')
        lambda_client.update_function_code(
            FunctionName='name', ZipFile=b'foo').returns({})
        lambda_client.update_function_configuration(
            FunctionName='name',
            MemorySize=256).returns({})
        stubbed_session.activate_stubs()
        awsclient = TypedAWSClient(stubbed_session)
        awsclient.update_function('name', b'foo', memory_size=256)
        stubbed_session.verify_stubs()

    def test_update_function_with_vpc_config(self, stubbed_session):
        lambda_client = stubbed_session.stub('lambda')
        lambda_client.update_function_code(
            FunctionName='name', ZipFile=b'foo').returns({})
        lambda_client.update_function_configuration(
            FunctionName='name', VpcConfig={
                'SecurityGroupIds': ['sg1', 'sg2'],
                'SubnetIds': ['sn1', 'sn2']
            }
        ).returns({})
        stubbed_session.activate_stubs()
        awsclient = TypedAWSClient(stubbed_session)
        awsclient.update_function(
            'name', b'foo',
            subnet_ids=['sn1', 'sn2'],
            security_group_ids=['sg1', 'sg2'],
        )
        stubbed_session.verify_stubs()

    def test_update_function_with_adding_tags(self, stubbed_session):
        function_arn = 'arn'

        lambda_client = stubbed_session.stub('lambda')
        lambda_client.update_function_code(
            FunctionName='name', ZipFile=b'foo').returns(
                {'FunctionArn': function_arn})
        lambda_client.list_tags(
            Resource=function_arn).returns({'Tags': {}})
        lambda_client.tag_resource(
            Resource=function_arn, Tags={'MyKey': 'MyValue'}).returns({})
        stubbed_session.activate_stubs()

        awsclient = TypedAWSClient(stubbed_session)
        awsclient.update_function('name', b'foo', tags={'MyKey': 'MyValue'})
        stubbed_session.verify_stubs()

    def test_update_function_with_updating_tags(self, stubbed_session):
        function_arn = 'arn'

        lambda_client = stubbed_session.stub('lambda')
        lambda_client.update_function_code(
            FunctionName='name', ZipFile=b'foo').returns(
                {'FunctionArn': function_arn})
        lambda_client.list_tags(
            Resource=function_arn).returns({'Tags': {'MyKey': 'MyOrigValue'}})
        lambda_client.tag_resource(
            Resource=function_arn, Tags={'MyKey': 'MyNewValue'}).returns({})
        stubbed_session.activate_stubs()

        awsclient = TypedAWSClient(stubbed_session)
        awsclient.update_function('name', b'foo', tags={'MyKey': 'MyNewValue'})
        stubbed_session.verify_stubs()

    def test_update_function_with_removing_tags(self, stubbed_session):
        function_arn = 'arn'

        lambda_client = stubbed_session.stub('lambda')
        lambda_client.update_function_code(
            FunctionName='name', ZipFile=b'foo').returns(
                {'FunctionArn': function_arn})
        lambda_client.list_tags(
            Resource=function_arn).returns(
                {'Tags': {'KeyToRemove': 'Value'}})
        lambda_client.untag_resource(
            Resource=function_arn, TagKeys=['KeyToRemove']).returns({})
        stubbed_session.activate_stubs()

        awsclient = TypedAWSClient(stubbed_session)
        awsclient.update_function('name', b'foo', tags={})
        stubbed_session.verify_stubs()

    def test_update_function_with_no_tag_updates_needed(self, stubbed_session):
        function_arn = 'arn'

        lambda_client = stubbed_session.stub('lambda')
        lambda_client.update_function_code(
            FunctionName='name', ZipFile=b'foo').returns(
                {'FunctionArn': function_arn})
        lambda_client.list_tags(
            Resource=function_arn).returns({'Tags': {'MyKey': 'SameValue'}})
        stubbed_session.activate_stubs()

        awsclient = TypedAWSClient(stubbed_session)
        awsclient.update_function('name', b'foo', tags={'MyKey': 'SameValue'})
        stubbed_session.verify_stubs()

    def test_update_function_with_iam_role(self, stubbed_session):
        function_arn = 'arn'

        lambda_client = stubbed_session.stub('lambda')
        lambda_client.update_function_code(
            FunctionName='name', ZipFile=b'foo').returns(
                {'FunctionArn': function_arn})
        lambda_client.update_function_configuration(
            FunctionName='name',
            Role='role-arn').returns({})
        stubbed_session.activate_stubs()

        awsclient = TypedAWSClient(stubbed_session)
        awsclient.update_function('name', b'foo', role_arn='role-arn')
        stubbed_session.verify_stubs()

    def test_update_function_is_retried_and_succeeds(self, stubbed_session):
        stubbed_session.stub('lambda').update_function_code(
            FunctionName='name', ZipFile=b'foo').returns(
                {'FunctionArn': 'arn'})

        update_config_kwargs = {
            'FunctionName': 'name',
            'Role': 'role-arn'
        }
        # This should fail two times with retryable exceptions and
        # then succeed to update the lambda function.
        stubbed_session.stub('lambda').update_function_configuration(
            **update_config_kwargs).raises_error(
                error_code='InvalidParameterValueException',
                message=('The role defined for the function cannot '
                         'be assumed by Lambda.'))
        stubbed_session.stub('lambda').update_function_configuration(
            **update_config_kwargs).raises_error(
            error_code='InvalidParameterValueException',
            message=('The role defined for the function cannot '
                     'be assumed by Lambda.'))
        stubbed_session.stub('lambda').update_function_configuration(
            **update_config_kwargs).returns({})
        stubbed_session.activate_stubs()
        awsclient = TypedAWSClient(stubbed_session, mock.Mock(spec=time.sleep))
        awsclient.update_function('name', b'foo', role_arn='role-arn')
        stubbed_session.verify_stubs()

    def test_update_function_fails_after_max_retries(self, stubbed_session):
        stubbed_session.stub('lambda').update_function_code(
            FunctionName='name', ZipFile=b'foo').returns(
                {'FunctionArn': 'arn'})

        update_config_kwargs = {
            'FunctionName': 'name',
            'Role': 'role-arn'
        }
        for _ in range(TypedAWSClient.LAMBDA_CREATE_ATTEMPTS):
            stubbed_session.stub('lambda').update_function_configuration(
                **update_config_kwargs).raises_error(
                    error_code='InvalidParameterValueException',
                    message=('The role defined for the function cannot '
                             'be assumed by Lambda.'))
        stubbed_session.activate_stubs()
        awsclient = TypedAWSClient(stubbed_session, mock.Mock(spec=time.sleep))

        with pytest.raises(botocore.exceptions.ClientError):
            awsclient.update_function('name', b'foo', role_arn='role-arn')
        stubbed_session.verify_stubs()

    def test_raises_large_deployment_error_for_connection_error(
            self, stubbed_session):
        too_large_content = b'a' * 60 * (1024 ** 2)
        stubbed_session.stub('lambda').update_function_code(
            FunctionName='name', ZipFile=too_large_content).raises_error(
                error=RequestsConnectionError())

        stubbed_session.activate_stubs()
        awsclient = TypedAWSClient(stubbed_session, mock.Mock(spec=time.sleep))
        with pytest.raises(DeploymentPackageTooLargeError) as excinfo:
            awsclient.update_function('name', too_large_content)
        stubbed_session.verify_stubs()
        assert excinfo.value.context.function_name == 'name'
        assert (
            excinfo.value.context.client_method_name == 'update_function_code')
        assert excinfo.value.context.deployment_size == 60 * (1024 ** 2)

    def test_no_raise_large_deployment_error_when_small_deployment_size(
            self, stubbed_session):
        stubbed_session.stub('lambda').update_function_code(
            FunctionName='name', ZipFile=b'foo').raises_error(
                error=RequestsConnectionError())

        stubbed_session.activate_stubs()
        awsclient = TypedAWSClient(stubbed_session, mock.Mock(spec=time.sleep))
        with pytest.raises(LambdaClientError) as excinfo:
            awsclient.update_function('name', b'foo')
        stubbed_session.verify_stubs()
        assert not isinstance(excinfo.value, DeploymentPackageTooLargeError)
        assert isinstance(
            excinfo.value.original_error, RequestsConnectionError)

    def test_raises_large_deployment_error_request_entity_to_large(
            self, stubbed_session):
        stubbed_session.stub('lambda').update_function_code(
            FunctionName='name', ZipFile=b'foo').raises_error(
                error_code='RequestEntityTooLargeException',
                message='')
        stubbed_session.activate_stubs()
        awsclient = TypedAWSClient(stubbed_session, mock.Mock(spec=time.sleep))
        with pytest.raises(DeploymentPackageTooLargeError):
            awsclient.update_function('name', b'foo')
        stubbed_session.verify_stubs()

    def test_raises_large_deployment_error_for_too_large_unzip(
            self, stubbed_session):
        stubbed_session.stub('lambda').update_function_code(
            FunctionName='name', ZipFile=b'foo').raises_error(
                error_code='InvalidParameterValueException',
                message='Unzipped size must be smaller than ...')
        stubbed_session.activate_stubs()
        awsclient = TypedAWSClient(stubbed_session, mock.Mock(spec=time.sleep))
        with pytest.raises(DeploymentPackageTooLargeError):
            awsclient.update_function('name', b'foo')
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


class TestCanDeleteRole(object):
    def test_can_delete_role(self, stubbed_session):
        stubbed_session.stub('iam').list_role_policies(
            RoleName='myrole').returns({
                'PolicyNames': ['mypolicy']
            })
        stubbed_session.stub('iam').delete_role_policy(
            RoleName='myrole',
            PolicyName='mypolicy').returns({})
        stubbed_session.stub('iam').delete_role(
            RoleName='myrole'
        ).returns({})
        stubbed_session.activate_stubs()

        awsclient = TypedAWSClient(stubbed_session)
        awsclient.delete_role('myrole')
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

    def test_random_id_can_be_omitted(self, stubbed_session):
        stubbed_session.stub('lambda').add_permission(
            Action='lambda:InvokeFunction',
            FunctionName='function_name',
            StatementId=stub.ANY,
            Principal='apigateway.amazonaws.com',
            SourceArn='arn:aws:execute-api:us-west-2:123:rest-api-id/*',
        ).returns({})
        stubbed_session.activate_stubs()
        TypedAWSClient(stubbed_session).add_permission_for_apigateway(
            # random_id is omitted here.
            'function_name', 'us-west-2', '123', 'rest-api-id')
        stubbed_session.verify_stubs()

    def should_call_add_permission(self, lambda_stub,
                                   statement_id='random-id'):
        lambda_stub.add_permission(
            Action='lambda:InvokeFunction',
            FunctionName='name',
            StatementId=statement_id,
            Principal='apigateway.amazonaws.com',
            SourceArn='arn:aws:execute-api:us-west-2:123:rest-api-id/*',
        ).returns({})

    def test_can_add_permission_for_apigateway_needed(self, stubbed_session):
        # An empty policy means we need to add permissions.
        lambda_stub = stubbed_session.stub('lambda')
        lambda_stub.get_policy(FunctionName='name').returns({'Policy': '{}'})
        self.should_call_add_permission(lambda_stub)
        stubbed_session.activate_stubs()
        client = TypedAWSClient(stubbed_session)
        client.add_permission_for_apigateway_if_needed(
            'name', 'us-west-2', '123', 'rest-api-id', 'random-id')
        stubbed_session.verify_stubs()

    def test_can_add_permission_random_id_optional(self, stubbed_session):
        lambda_stub = stubbed_session.stub('lambda')
        lambda_stub.get_policy(FunctionName='name').returns({'Policy': '{}'})
        self.should_call_add_permission(lambda_stub, 'my-random-id')
        stubbed_session.activate_stubs()
        client = FixedIDTypedAWSClient(stubbed_session, 'my-random-id')
        client.add_permission_for_apigateway_if_needed(
            'name', 'us-west-2', '123', 'rest-api-id')
        stubbed_session.verify_stubs()

    def test_can_add_permission_for_apigateway_not_needed(self,
                                                          stubbed_session):
        source_arn = 'arn:aws:execute-api:us-west-2:123:rest-api-id/*'
        wrong_action = {
            'Action': 'lambda:NotInvoke',
            'Condition': {
                'ArnLike': {
                    'AWS:SourceArn': source_arn,
                }
            },
            'Effect': 'Allow',
            'Principal': {'Service': 'apigateway.amazonaws.com'},
            'Resource': 'arn:aws:lambda:us-west-2:account_id:function:name',
            'Sid': 'e4755709-067e-4254-b6ec-e7f9639e6f7b',
        }
        wrong_service_name = {
            'Action': 'lambda:Invoke',
            'Condition': {
                'ArnLike': {
                    'AWS:SourceArn': source_arn,
                }
            },
            'Effect': 'Allow',
            'Principal': {'Service': 'NOT-apigateway.amazonaws.com'},
            'Resource': 'arn:aws:lambda:us-west-2:account_id:function:name',
            'Sid': 'e4755709-067e-4254-b6ec-e7f9639e6f7b',
        }
        correct_statement = {
            'Action': 'lambda:InvokeFunction',
            'Condition': {
                'ArnLike': {
                    'AWS:SourceArn': source_arn,
                }
            },
            'Effect': 'Allow',
            'Principal': {'Service': 'apigateway.amazonaws.com'},
            'Resource': 'arn:aws:lambda:us-west-2:account_id:function:name',
            'Sid': 'e4755709-067e-4254-b6ec-e7f9639e6f7b',
        }
        policy = {
            'Id': 'default',
            'Statement': [
                wrong_action,
                wrong_service_name,
                correct_statement,
            ],
            'Version': '2012-10-17'
        }
        stubbed_session.stub('lambda').get_policy(
            FunctionName='name').returns({'Policy': json.dumps(policy)})

        # Because the policy above indicates that API gateway already has the
        # necessary permissions, we should not call add_permission.
        stubbed_session.activate_stubs()
        client = TypedAWSClient(stubbed_session)
        client.add_permission_for_apigateway_if_needed(
            'name', 'us-west-2', '123', 'rest-api-id', 'random-id')
        stubbed_session.verify_stubs()

    def test_can_add_permission_when_policy_does_not_exist(self,
                                                           stubbed_session):
        # It's also possible to receive a ResourceNotFoundException
        # if you call get_policy() on a lambda function with no policy.
        lambda_stub = stubbed_session.stub('lambda')
        lambda_stub.get_policy(FunctionName='name').raises_error(
            error_code='ResourceNotFoundException', message='Does not exist.')
        self.should_call_add_permission(lambda_stub)
        stubbed_session.activate_stubs()
        client = TypedAWSClient(stubbed_session)
        client.add_permission_for_apigateway_if_needed(
            'name', 'us-west-2', '123', 'rest-api-id', 'random-id')
        stubbed_session.verify_stubs()


class TestAddPermissionsForAuthorizer(object):

    FUNCTION_ARN = (
        'arn:aws:lambda:us-west-2:1:function:app-dev-name'
    )
    GOOD_ARN = (
        'arn:aws:apigateway:us-west-2:lambda:path/2015-03-31/functions/'
        '%s/invocations' % FUNCTION_ARN
    )

    def test_can_add_permission_for_authorizer(self, stubbed_session):
        apigateway = stubbed_session.stub('apigateway')
        apigateway.get_authorizers(restApiId='rest-api-id').returns({
            'items': [
                {'authorizerUri': 'not:arn', 'id': 'bad'},
                {'authorizerUri': self.GOOD_ARN, 'id': 'good'},
            ]
        })
        source_arn = (
            'arn:aws:execute-api:us-west-2:1:rest-api-id/authorizers/good'
        )
        # We should call the appropriate add_permission call.
        lambda_client = stubbed_session.stub('lambda')
        lambda_client.add_permission(
            Action='lambda:InvokeFunction',
            FunctionName='app-dev-name',
            StatementId='random-id',
            Principal='apigateway.amazonaws.com',
            SourceArn=source_arn
        ).returns({})
        stubbed_session.activate_stubs()

        TypedAWSClient(stubbed_session).add_permission_for_authorizer(
            'rest-api-id', self.FUNCTION_ARN, 'random-id'
        )
        stubbed_session.verify_stubs()

    def test_random_id_can_be_omitted(self, stubbed_session):
        stubbed_session.stub('apigateway').get_authorizers(
            restApiId='rest-api-id').returns({
                'items': [{'authorizerUri': self.GOOD_ARN, 'id': 'good'}]})
        source_arn = (
            'arn:aws:execute-api:us-west-2:1:rest-api-id/authorizers/good'
        )
        stubbed_session.stub('lambda').add_permission(
            Action='lambda:InvokeFunction',
            FunctionName='app-dev-name',
            # Autogenerated value here.
            StatementId=stub.ANY,
            Principal='apigateway.amazonaws.com',
            SourceArn=source_arn
        ).returns({})
        stubbed_session.activate_stubs()
        # Note the omission of the random id.
        TypedAWSClient(stubbed_session).add_permission_for_authorizer(
            'rest-api-id', self.FUNCTION_ARN
        )
        stubbed_session.verify_stubs()

    def test_value_error_raised_for_unknown_function(self, stubbed_session):
        apigateway = stubbed_session.stub('apigateway')
        apigateway.get_authorizers(restApiId='rest-api-id').returns({
            'items': [
                {'authorizerUri': 'not:arn', 'id': 'bad'},
                {'authorizerUri': 'also-not:arn', 'id': 'alsobad'},
            ]
        })
        stubbed_session.activate_stubs()

        unknown_function_arn = 'function:arn'
        with pytest.raises(ResourceDoesNotExistError):
            TypedAWSClient(stubbed_session).add_permission_for_authorizer(
                'rest-api-id', unknown_function_arn, 'random-id'
            )
        stubbed_session.verify_stubs()


def test_get_sdk(stubbed_session):
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


def test_import_rest_api(stubbed_session):
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


def test_update_api_from_swagger(stubbed_session):
    apig = stubbed_session.stub('apigateway')
    swagger_doc = {'swagger': 'doc'}
    apig.put_rest_api(
        restApiId='rest_api_id',
        mode='overwrite',
        body=json.dumps(swagger_doc, indent=2)).returns({})

    stubbed_session.activate_stubs()
    awsclient = TypedAWSClient(stubbed_session)

    awsclient.update_api_from_swagger('rest_api_id', swagger_doc)
    stubbed_session.verify_stubs()


def test_can_get_or_create_rule_arn(stubbed_session):
    events = stubbed_session.stub('events')
    events.put_rule(
        Name='rule-name',
        ScheduleExpression='rate(1 hour)').returns({
            'RuleArn': 'rule-arn',
        })

    stubbed_session.activate_stubs()
    awsclient = TypedAWSClient(stubbed_session)
    result = awsclient.get_or_create_rule_arn('rule-name', 'rate(1 hour)')
    stubbed_session.verify_stubs()
    assert result == 'rule-arn'


def test_can_connect_rule_to_lambda(stubbed_session):
    events = stubbed_session.stub('events')
    events.put_targets(
        Rule='rule-name',
        Targets=[{'Id': '1', 'Arn': 'function-arn'}]).returns({})

    stubbed_session.activate_stubs()
    awsclient = TypedAWSClient(stubbed_session)
    awsclient.connect_rule_to_lambda('rule-name', 'function-arn')
    stubbed_session.verify_stubs()


def test_add_permission_for_scheduled_event(stubbed_session):
    lambda_client = stubbed_session.stub('lambda')
    lambda_client.get_policy(FunctionName='function-arn').returns(
        {'Policy': '{}'})
    lambda_client.add_permission(
        Action='lambda:InvokeFunction',
        FunctionName='function-arn',
        StatementId=stub.ANY,
        Principal='events.amazonaws.com',
        SourceArn='rule-arn'
    ).returns({})

    stubbed_session.activate_stubs()

    awsclient = TypedAWSClient(stubbed_session)
    awsclient.add_permission_for_scheduled_event(
        'rule-arn', 'function-arn')

    stubbed_session.verify_stubs()


def test_skip_if_permission_already_granted(stubbed_session):
    lambda_client = stubbed_session.stub('lambda')
    policy = {
        'Id': 'default',
        'Statement': [
            {'Action': 'lambda:InvokeFunction',
                'Condition': {
                    'ArnLike': {
                        'AWS:SourceArn': 'rule-arn',
                    }
                },
                'Effect': 'Allow',
                'Principal': {'Service': 'events.amazonaws.com'},
                'Resource': 'resource-arn',
                'Sid': 'statement-id'},
        ],
        'Version': '2012-10-17'
    }
    lambda_client.get_policy(
        FunctionName='function-arn').returns({'Policy': json.dumps(policy)})

    stubbed_session.activate_stubs()
    awsclient = TypedAWSClient(stubbed_session)
    awsclient.add_permission_for_scheduled_event(
        'rule-arn', 'function-arn')
    stubbed_session.verify_stubs()


def test_can_delete_rule(stubbed_session):
    events = stubbed_session.stub('events')
    events.remove_targets(
        Rule='rule-name',
        Ids=['1']).returns({})
    events.delete_rule(Name='rule-name').returns({})

    stubbed_session.activate_stubs()
    awsclient = TypedAWSClient(stubbed_session)
    awsclient.delete_rule('rule-name')
    stubbed_session.verify_stubs()
