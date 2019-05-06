import json
import datetime
import time

import pytest
import mock
import botocore.exceptions
from botocore.vendored.requests import ConnectionError as \
    RequestsConnectionError
from botocore.vendored.requests.exceptions import ReadTimeout as \
    RequestsReadTimeout
from botocore import stub

from chalice.awsclient import TypedAWSClient
from chalice.awsclient import ResourceDoesNotExistError
from chalice.awsclient import DeploymentPackageTooLargeError
from chalice.awsclient import LambdaClientError
from chalice.awsclient import ReadTimeout


def create_policy_statement(source_arn, service_name, statement_id):
    return {
        'Action': 'lambda:InvokeFunction',
        'Condition': {
            'ArnLike': {
                'AWS:SourceArn': source_arn,
            }
        },
        'Effect': 'Allow',
        'Principal': {'Service': '%s.amazonaws.com' % service_name},
        'Resource': 'function-arn',
        'Sid': statement_id,
    }


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


class TestInvokeLambdaFunction(object):
    def test_invoke_no_payload_no_context(self, stubbed_session):
        stubbed_session.stub('lambda').invoke(
            FunctionName='name',
            InvocationType='RequestResponse',
        ).returns({})
        stubbed_session.activate_stubs()
        awsclient = TypedAWSClient(stubbed_session)
        assert awsclient.invoke_function('name') == {}
        stubbed_session.verify_stubs()

    def test_invoke_payload_provided(self, stubbed_session):
        stubbed_session.stub('lambda').invoke(
            FunctionName='name',
            Payload=b'payload',
            InvocationType='RequestResponse',
        ).returns({})
        stubbed_session.activate_stubs()
        awsclient = TypedAWSClient(stubbed_session)
        assert awsclient.invoke_function('name', payload=b'payload') == {}
        stubbed_session.verify_stubs()

    def test_invoke_read_timeout_raises_correct_error(self, stubbed_session):
        stubbed_session.stub('lambda').invoke(
            FunctionName='name',
            Payload=b'payload',
            InvocationType='RequestResponse',
        ).raises_error(error=RequestsReadTimeout())
        stubbed_session.activate_stubs()
        awsclient = TypedAWSClient(stubbed_session)
        with pytest.raises(ReadTimeout):
            awsclient.invoke_function('name', payload=b'payload') == {}


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

    def test_create_function_with_layers(self, stubbed_session):
        layers = ['arn:aws:lambda:us-east-1:111:layer:test_layer:1']
        stubbed_session.stub('lambda').create_function(
            FunctionName='name',
            Runtime='python2.7',
            Code={'ZipFile': b'foo'},
            Handler='app.app',
            Role='myarn',
            Layers=layers
        ).returns({'FunctionArn': 'arn:12345:name'})
        stubbed_session.activate_stubs()
        awsclient = TypedAWSClient(stubbed_session)
        assert awsclient.create_function(
            'name', 'myarn', b'foo', 'python2.7', 'app.app',
            layers=layers
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

    def test_create_function_retries_on_kms_errors(self, stubbed_session):
        # You'll sometimes get this message when you first create a role.
        # We want to ensure that we're trying when this happens.
        error_code = 'InvalidParameterValueException'
        error_message = (
            'Lambda was unable to configure access to your '
            'environment variables because the KMS key '
            'is invalid for CreateGrant. Please '
            'check your KMS key settings. '
            'KMS Exception: InvalidArnException KMS Message: '
            'ARN does not refer to a valid principal'
        )
        kwargs = {
            'FunctionName': 'name',
            'Runtime': 'python2.7',
            'Code': {'ZipFile': b'foo'},
            'Handler': 'app.app',
            'Role': 'myarn',
        }
        client = stubbed_session.stub('lambda')
        client.create_function(**kwargs).raises_error(
            error_code=error_code,
            message=error_message
        )
        client.create_function(**kwargs).returns(
            {'FunctionArn': 'arn:12345:name'}
        )
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

    def test_update_function_with_layers_config(self, stubbed_session):
        layers = ['arn:aws:lambda:us-east-1:111:layer:test_layer:1']
        lambda_client = stubbed_session.stub('lambda')
        lambda_client.update_function_code(
            FunctionName='name', ZipFile=b'foo').returns({})
        lambda_client.update_function_configuration(
            FunctionName='name', Layers=layers
        ).returns({})
        stubbed_session.activate_stubs()
        awsclient = TypedAWSClient(stubbed_session)
        awsclient.update_function(
            'name', b'foo',
            layers=layers
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


class TestPutFunctionConcurrency(object):
    def test_put_function_concurrency(self, stubbed_session):
        lambda_client = stubbed_session.stub('lambda')
        lambda_client.put_function_concurrency(
            FunctionName='name', ReservedConcurrentExecutions=5).returns({})
        stubbed_session.activate_stubs()
        awsclient = TypedAWSClient(stubbed_session)
        awsclient.put_function_concurrency('name', 5)
        stubbed_session.verify_stubs()


class TestDeleteFunctionConcurrency(object):
    def test_delete_function_concurrency(self, stubbed_session):
        lambda_client = stubbed_session.stub('lambda')
        lambda_client.delete_function_concurrency(
            FunctionName='name').returns({})
        stubbed_session.activate_stubs()
        awsclient = TypedAWSClient(stubbed_session)
        awsclient.delete_function_concurrency('name')
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
    def should_call_add_permission(self, lambda_stub,
                                   statement_id=stub.ANY):
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
        client.add_permission_for_apigateway(
            'name', 'us-west-2', '123', 'rest-api-id')
        stubbed_session.verify_stubs()

    def test_can_add_permission_random_id_optional(self, stubbed_session):
        lambda_stub = stubbed_session.stub('lambda')
        lambda_stub.get_policy(FunctionName='name').returns({'Policy': '{}'})
        self.should_call_add_permission(lambda_stub)
        stubbed_session.activate_stubs()
        client = TypedAWSClient(stubbed_session)
        client.add_permission_for_apigateway(
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
        client.add_permission_for_apigateway(
            'name', 'us-west-2', '123', 'rest-api-id')
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
        client.add_permission_for_apigateway(
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


def test_can_connect_bucket_to_lambda_new_config(stubbed_session):
    s3 = stubbed_session.stub('s3')
    s3.get_bucket_notification_configuration(Bucket='mybucket').returns({
        'ResponseMetadata': {},
    })
    s3.put_bucket_notification_configuration(
        Bucket='mybucket',
        NotificationConfiguration={
            'LambdaFunctionConfigurations': [{
                'LambdaFunctionArn': 'function-arn',
                'Events': ['s3:ObjectCreated:*'],
            }]
        }
    ).returns({})

    stubbed_session.activate_stubs()
    awsclient = TypedAWSClient(stubbed_session)
    awsclient.connect_s3_bucket_to_lambda(
        'mybucket', 'function-arn', ['s3:ObjectCreated:*'])
    stubbed_session.verify_stubs()


def test_can_connect_bucket_with_prefix_and_suffix(stubbed_session):
    s3 = stubbed_session.stub('s3')
    s3.get_bucket_notification_configuration(Bucket='mybucket').returns({})
    s3.put_bucket_notification_configuration(
        Bucket='mybucket',
        NotificationConfiguration={
            'LambdaFunctionConfigurations': [{
                'LambdaFunctionArn': 'function-arn',
                'Filter': {
                    'Key': {
                        'FilterRules': [
                            {
                                'Name': 'Prefix',
                                'Value': 'images/'
                            },
                            {
                                'Name': 'Suffix',
                                'Value': '.jpg'
                            }
                        ]
                    }
                },
                'Events': ['s3:ObjectCreated:*'],
            }]
        }
    ).returns({})

    stubbed_session.activate_stubs()
    awsclient = TypedAWSClient(stubbed_session)
    awsclient.connect_s3_bucket_to_lambda(
        'mybucket', 'function-arn', ['s3:ObjectCreated:*'],
        prefix='images/', suffix='.jpg',
    )
    stubbed_session.verify_stubs()


def test_can_merge_s3_notification_config(stubbed_session):
    s3 = stubbed_session.stub('s3')
    s3.get_bucket_notification_configuration(Bucket='mybucket').returns({
        'LambdaFunctionConfigurations': [
            {'Events': ['s3:ObjectCreated:*'],
             'LambdaFunctionArn': 'other-function-arn'}],
    })
    s3.put_bucket_notification_configuration(
        Bucket='mybucket',
        NotificationConfiguration={
            'LambdaFunctionConfigurations': [
                # The existing function arn remains untouched.
                {'LambdaFunctionArn': 'other-function-arn',
                 'Events': ['s3:ObjectCreated:*']},
                # This is the new function arn that we've injected.
                {'LambdaFunctionArn': 'function-arn',
                 'Events': ['s3:ObjectCreated:*']},
            ]
        }
    ).returns({})

    stubbed_session.activate_stubs()
    awsclient = TypedAWSClient(stubbed_session)
    awsclient.connect_s3_bucket_to_lambda(
        'mybucket', 'function-arn', ['s3:ObjectCreated:*'])
    stubbed_session.verify_stubs()


def test_can_replace_existing_config(stubbed_session):
    s3 = stubbed_session.stub('s3')
    s3.get_bucket_notification_configuration(Bucket='mybucket').returns({
        'LambdaFunctionConfigurations': [
            {'Events': ['s3:ObjectRemoved:*'],
             'LambdaFunctionArn': 'function-arn'}],
    })
    s3.put_bucket_notification_configuration(
        Bucket='mybucket',
        NotificationConfiguration={
            'LambdaFunctionConfigurations': [
                # Note the event is replaced from ObjectRemoved
                # to ObjectCreated.
                {'LambdaFunctionArn': 'function-arn',
                 'Events': ['s3:ObjectCreated:*']},
            ]
        }
    ).returns({})

    stubbed_session.activate_stubs()
    awsclient = TypedAWSClient(stubbed_session)
    awsclient.connect_s3_bucket_to_lambda(
        'mybucket', 'function-arn', ['s3:ObjectCreated:*'])
    stubbed_session.verify_stubs()


def test_add_permission_for_s3_event(stubbed_session):
    lambda_client = stubbed_session.stub('lambda')
    lambda_client.get_policy(FunctionName='function-arn').returns(
        {'Policy': '{}'})
    lambda_client.add_permission(
        Action='lambda:InvokeFunction',
        FunctionName='function-arn',
        StatementId=stub.ANY,
        Principal='s3.amazonaws.com',
        SourceArn='arn:aws:s3:::mybucket',
    ).returns({})

    stubbed_session.activate_stubs()

    awsclient = TypedAWSClient(stubbed_session)
    awsclient.add_permission_for_s3_event(
        'mybucket', 'function-arn')
    stubbed_session.verify_stubs()


def test_skip_if_permission_already_granted_to_s3(stubbed_session):
    lambda_client = stubbed_session.stub('lambda')
    policy = {
        'Id': 'default',
        'Statement': [{
            'Action': 'lambda:InvokeFunction',
            'Condition': {
                'ArnLike': {
                    'AWS:SourceArn': 'arn:aws:s3:::mybucket',
                }
            },
            'Effect': 'Allow',
            'Principal': {'Service': 's3.amazonaws.com'},
            'Resource': 'resource-arn',
            'Sid': 'statement-id',
        }],
        'Version': '2012-10-17'
    }
    lambda_client.get_policy(
        FunctionName='function-arn').returns({'Policy': json.dumps(policy)})

    stubbed_session.activate_stubs()
    awsclient = TypedAWSClient(stubbed_session)
    awsclient.add_permission_for_s3_event(
        'mybucket', 'function-arn')
    stubbed_session.verify_stubs()


def test_can_disconnect_bucket_to_lambda_merged(stubbed_session):
    s3 = stubbed_session.stub('s3')
    s3.get_bucket_notification_configuration(Bucket='mybucket').returns({
        'LambdaFunctionConfigurations': [
            {'Events': ['s3:ObjectRemoved:*'],
             'LambdaFunctionArn': 'function-arn-1'},
            {'Events': ['s3:ObjectCreated:*'],
             'LambdaFunctionArn': 'function-arn-2'}
        ],
        'ResponseMetadata': {},
    })
    s3.put_bucket_notification_configuration(
        Bucket='mybucket',
        NotificationConfiguration={
            'LambdaFunctionConfigurations': [
                {'Events': ['s3:ObjectCreated:*'],
                 'LambdaFunctionArn': 'function-arn-2'}
            ],
        },
    ).returns({})

    stubbed_session.activate_stubs()
    awsclient = TypedAWSClient(stubbed_session)
    awsclient.disconnect_s3_bucket_from_lambda(
        'mybucket', 'function-arn-1')
    stubbed_session.verify_stubs()


def test_can_disconnect_bucket_to_lambda_not_exists(stubbed_session):
    s3 = stubbed_session.stub('s3')
    s3.get_bucket_notification_configuration(Bucket='mybucket').returns({
        'LambdaFunctionConfigurations': [
            {'Events': ['s3:ObjectRemoved:*'],
             'LambdaFunctionArn': 'function-arn-1'},
            {'Events': ['s3:ObjectCreated:*'],
             'LambdaFunctionArn': 'function-arn-2'}
        ],
    })
    s3.put_bucket_notification_configuration(
        Bucket='mybucket',
        NotificationConfiguration={
            'LambdaFunctionConfigurations': [
                {'Events': ['s3:ObjectRemoved:*'],
                 'LambdaFunctionArn': 'function-arn-1'},
                {'Events': ['s3:ObjectCreated:*'],
                 'LambdaFunctionArn': 'function-arn-2'}
            ],
        },
    ).returns({})

    stubbed_session.activate_stubs()
    awsclient = TypedAWSClient(stubbed_session)
    awsclient.disconnect_s3_bucket_from_lambda('mybucket', 'some-other-arn')
    stubbed_session.verify_stubs()


def test_add_permission_for_sns_publish(stubbed_session):
    lambda_client = stubbed_session.stub('lambda')
    lambda_client.get_policy(FunctionName='function-arn').returns(
        {'Policy': '{"Statement": []}'}
    )
    lambda_client.add_permission(
        Action='lambda:InvokeFunction',
        FunctionName='function-arn',
        StatementId=stub.ANY,
        Principal='sns.amazonaws.com',
        SourceArn='arn:aws:sns:::topic-arn',
    ).returns({})

    stubbed_session.activate_stubs()
    awsclient = TypedAWSClient(stubbed_session)
    awsclient.add_permission_for_sns_topic(
        'arn:aws:sns:::topic-arn', 'function-arn')
    stubbed_session.verify_stubs()


def test_subscribe_function_to_arn(stubbed_session):
    sns_client = stubbed_session.stub('sns')
    topic_arn = 'arn:aws:sns:topic-arn'
    sns_client.subscribe(
        TopicArn=topic_arn,
        Protocol='lambda',
        Endpoint='function-arn'
    ).returns({'SubscriptionArn': 'subscribe-arn'})

    stubbed_session.activate_stubs()

    awsclient = TypedAWSClient(stubbed_session)
    awsclient.subscribe_function_to_topic(
        'arn:aws:sns:topic-arn', 'function-arn')
    stubbed_session.verify_stubs()


def test_can_unsubscribe_from_topic(stubbed_session):
    sns_client = stubbed_session.stub('sns')
    subscription_arn = 'arn:aws:sns:subscribe-arn'
    sns_client.unsubscribe(
        SubscriptionArn=subscription_arn,
    ).returns({})

    stubbed_session.activate_stubs()

    awsclient = TypedAWSClient(stubbed_session)
    awsclient.unsubscribe_from_topic(subscription_arn)
    stubbed_session.verify_stubs()


@pytest.mark.parametrize('topic_arn,function_arn,is_verified', [
    ('arn:aws:sns:mytopic', 'arn:aws:lambda:myfunction', True),
    ('arn:aws:sns:NEW-TOPIC', 'arn:aws:lambda:myfunction', False),
    ('arn:aws:sns:mytopic', 'arn:aws:lambda:NEW-FUNCTION', False),
    ('arn:aws:sns:NEW-TOPIC', 'arn:aws:lambda:NEW-FUNCTION', False),
])
def test_subscription_exists(stubbed_session, topic_arn,
                             function_arn, is_verified):
    sns_client = stubbed_session.stub('sns')
    subscription_arn = 'arn:aws:sns:subscribe-arn'
    sns_client.get_subscription_attributes(
        SubscriptionArn=subscription_arn,
    ).returns({
        "Attributes": {
            "Owner": "12345",
            "RawMessageDelivery": "false",
            "TopicArn": topic_arn,
            "Endpoint": function_arn,
            "Protocol": "lambda",
            "PendingConfirmation": "false",
            "ConfirmationWasAuthenticated": "true",
            "SubscriptionArn": subscription_arn,
        }
    })

    stubbed_session.activate_stubs()

    awsclient = TypedAWSClient(stubbed_session)
    assert awsclient.verify_sns_subscription_current(
        subscription_arn,
        topic_name='mytopic',
        function_arn='arn:aws:lambda:myfunction',
    ) == is_verified
    stubbed_session.verify_stubs()


def test_subscription_not_exists(stubbed_session):
    sns_client = stubbed_session.stub('sns')
    subscription_arn = 'arn:aws:sns:subscribe-arn'
    sns_client.get_subscription_attributes(
        SubscriptionArn=subscription_arn,
    ).raises_error(error_code='NotFound', message='Does not exists.')

    stubbed_session.activate_stubs()

    awsclient = TypedAWSClient(stubbed_session)
    assert not awsclient.verify_sns_subscription_current(
        subscription_arn, 'topic-arn', 'function-arn')
    stubbed_session.verify_stubs()


def test_can_remove_lambda_sns_permission(stubbed_session):
    topic_arn = 'arn:sns:topic'
    policy = {
        'Id': 'default',
        'Statement': [create_policy_statement(topic_arn,
                                              service_name='sns',
                                              statement_id='12345')],
        'Version': '2012-10-17'
    }
    lambda_stub = stubbed_session.stub('lambda')
    lambda_stub.get_policy(
        FunctionName='name').returns({'Policy': json.dumps(policy)})
    lambda_stub.remove_permission(
        FunctionName='name', StatementId='12345',
    ).returns({})

    # Because the policy above indicates that API gateway already has the
    # necessary permissions, we should not call add_permission.
    stubbed_session.activate_stubs()
    client = TypedAWSClient(stubbed_session)
    client.remove_permission_for_sns_topic(
        topic_arn, 'name')
    stubbed_session.verify_stubs()


def test_can_remove_s3_permission(stubbed_session):
    policy = {
        'Id': 'default',
        'Statement': [create_policy_statement('arn:aws:s3:::mybucket',
                                              service_name='s3',
                                              statement_id='12345')],
        'Version': '2012-10-17'
    }
    lambda_stub = stubbed_session.stub('lambda')
    lambda_stub.get_policy(
        FunctionName='name').returns({'Policy': json.dumps(policy)})
    lambda_stub.remove_permission(
        FunctionName='name', StatementId='12345',
    ).returns({})

    # Because the policy above indicates that API gateway already has the
    # necessary permissions, we should not call add_permission.
    stubbed_session.activate_stubs()
    client = TypedAWSClient(stubbed_session)
    client.remove_permission_for_s3_event(
        'mybucket', 'name')
    stubbed_session.verify_stubs()


def test_can_create_sqs_event_source(stubbed_session):
    queue_arn = 'arn:sqs:queue-name'
    function_name = 'myfunction'
    batch_size = 100

    lambda_stub = stubbed_session.stub('lambda')
    lambda_stub.create_event_source_mapping(
        EventSourceArn=queue_arn,
        FunctionName=function_name,
        BatchSize=batch_size
    ).returns({'UUID': 'my-uuid'})

    stubbed_session.activate_stubs()
    client = TypedAWSClient(stubbed_session)
    result = client.create_sqs_event_source(
        queue_arn, function_name, batch_size
    )
    assert result == 'my-uuid'
    stubbed_session.verify_stubs()


def test_can_retry_create_sqs_event_source(stubbed_session):
    queue_arn = 'arn:sqs:queue-name'
    function_name = 'myfunction'
    batch_size = 100

    lambda_stub = stubbed_session.stub('lambda')
    lambda_stub.create_event_source_mapping(
        EventSourceArn=queue_arn,
        FunctionName=function_name,
        BatchSize=batch_size
    ).raises_error(
        error_code='InvalidParameterValueException',
        message=('The provided execution role does not '
                 'have permissions to call ReceiveMessage on SQS')
    )
    lambda_stub.create_event_source_mapping(
        EventSourceArn=queue_arn,
        FunctionName=function_name,
        BatchSize=batch_size
    ).returns({'UUID': 'my-uuid'})

    stubbed_session.activate_stubs()
    client = TypedAWSClient(stubbed_session, mock.Mock(spec=time.sleep))
    result = client.create_sqs_event_source(
        queue_arn, function_name, batch_size
    )
    assert result == 'my-uuid'

    stubbed_session.verify_stubs()


def test_can_delete_sqs_event_source(stubbed_session):
    lambda_stub = stubbed_session.stub('lambda')
    lambda_stub.delete_event_source_mapping(
        UUID='my-uuid',
    ).returns({})

    stubbed_session.activate_stubs()
    client = TypedAWSClient(stubbed_session, mock.Mock(spec=time.sleep))
    client.remove_sqs_event_source(
        'my-uuid',
    )
    stubbed_session.verify_stubs()


def test_can_retry_delete_event_source(stubbed_session):
    lambda_stub = stubbed_session.stub('lambda')
    lambda_stub.delete_event_source_mapping(
        UUID='my-uuid',
    ).raises_error(
        error_code='ResourceInUseException',
        message=('Cannot update the event source mapping '
                 'because it is in use.')
    )
    lambda_stub.delete_event_source_mapping(
        UUID='my-uuid',
    ).returns({})

    stubbed_session.activate_stubs()
    client = TypedAWSClient(stubbed_session, mock.Mock(spec=time.sleep))
    client.remove_sqs_event_source(
        'my-uuid',
    )
    stubbed_session.verify_stubs()


def test_only_retry_settling_errors(stubbed_session):
    lambda_stub = stubbed_session.stub('lambda')
    lambda_stub.delete_event_source_mapping(
        UUID='my-uuid',
    ).raises_error(
        error_code='ResourceInUseException',
        message='Wrong message'
    )
    stubbed_session.activate_stubs()
    client = TypedAWSClient(stubbed_session, mock.Mock(spec=time.sleep))
    with pytest.raises(botocore.exceptions.ClientError):
        client.remove_sqs_event_source('my-uuid')
    stubbed_session.verify_stubs()


def test_can_retry_update_event_source(stubbed_session):
    lambda_stub = stubbed_session.stub('lambda')
    lambda_stub.update_event_source_mapping(
        UUID='my-uuid',
        BatchSize=5,
    ).returns({})

    stubbed_session.activate_stubs()
    client = TypedAWSClient(stubbed_session)
    client.update_sqs_event_source(
        event_uuid='my-uuid', batch_size=5
    )
    stubbed_session.verify_stubs()


@pytest.mark.parametrize('resource_name,service_name,is_verified', [
    ('queue-name', 'sqs', True),
    ('queue-name', 'not-sqs', False),
    ('not-queue-name', 'sqs', False),
    ('not-queue-name', 'not-sqs', False),
])
def test_verify_event_source_current(stubbed_session, resource_name,
                                     service_name, is_verified):
    client = stubbed_session.stub('lambda')
    uuid = 'uuid-12345'
    client.get_event_source_mapping(
        UUID=uuid,
    ).returns({
        'UUID': uuid,
        'BatchSize': 10,
        'EventSourceArn': 'arn:aws:sqs:us-west-2:123:queue-name',
        'FunctionArn': 'arn:aws:lambda:function-arn',
        'LastModified': '2018-07-02T18:19:03.958000-07:00',
        'State': 'Enabled',
        'StateTransitionReason': 'USER_INITIATED'
    })
    stubbed_session.activate_stubs()

    awsclient = TypedAWSClient(stubbed_session)
    assert awsclient.verify_event_source_current(
        uuid, resource_name=resource_name, service_name=service_name,
        function_arn='arn:aws:lambda:function-arn',
    ) == is_verified
    stubbed_session.verify_stubs()


def test_event_source_does_not_exist(stubbed_session):
    client = stubbed_session.stub('lambda')
    uuid = 'uuid-12345'
    client.get_event_source_mapping(
        UUID=uuid,
    ).raises_error(error_code='ResourceNotFoundException',
                   message='Does not exists.')

    stubbed_session.activate_stubs()

    awsclient = TypedAWSClient(stubbed_session)
    assert not awsclient.verify_event_source_current(
        uuid, 'myqueue', 'sqs', 'function-arn')
    stubbed_session.verify_stubs()


def test_can_update_sqs_event_source(stubbed_session):
    lambda_stub = stubbed_session.stub('lambda')
    lambda_stub.update_event_source_mapping(
        UUID='my-uuid',
        BatchSize=5,
    ).returns({})

    stubbed_session.activate_stubs()
    client = TypedAWSClient(stubbed_session)
    client.update_sqs_event_source(
        event_uuid='my-uuid', batch_size=5
    )
    stubbed_session.verify_stubs()
