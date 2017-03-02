import json
import datetime
import os
import tempfile
import time

import pytest
import mock
import botocore.exceptions
from botocore.response import StreamingBody

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


def test_create_security_group(stubbed_session):
    stubbed_session.stub('ec2').create_security_group(
        GroupName='name',
        Description='Default SG for name',
        VpcId='67890'
    ).returns({'GroupId': 'abc'})
    stubbed_session.stub('ec2').authorize_security_group_ingress(
        GroupId='abc',
        IpPermissions=[
            {
                'IpProtocol': 'tcp',
                'FromPort': 80,
                'ToPort': 80,
                'IpRanges': [{'CidrIp': '0.0.0.0/0'}]
            },
            {
                'IpProtocol': 'tcp',
                'FromPort': 443,
                'ToPort': 443,
                'IpRanges': [{'CidrIp': '0.0.0.0/0'}]
            }
        ]
    ).returns({})
    stubbed_session.activate_stubs()
    awsclient = TypedAWSClient(stubbed_session)
    assert awsclient.create_security_group('name', '67890') == 'abc'
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
            Environment={'Variables': {'KEY': 'value'}},
            VpcConfig={'SubnetIds': ['12345'], 'SecurityGroupIds': ['67890']}
        ).returns({'FunctionArn': 'arn:12345:name'})
        stubbed_session.activate_stubs()
        awsclient = TypedAWSClient(stubbed_session)
        assert awsclient.create_function(
            'name', 'myarn', b'foo', {'KEY': 'value'},
            {'subnet_ids': ['12345'], 'security_group_ids': ['67890']}
        ) == 'arn:12345:name'
        stubbed_session.verify_stubs()

    def test_create_function_succeeds_no_extras(self, stubbed_session):
        stubbed_session.stub('lambda').create_function(
            FunctionName='name',
            Runtime='python2.7',
            Code={'ZipFile': b'foo'},
            Handler='app.app',
            Role='myarn',
            Timeout=60
        ).returns({'FunctionArn': 'arn:12345:name'})
        stubbed_session.activate_stubs()
        awsclient = TypedAWSClient(stubbed_session)
        assert awsclient.create_function(
            'name', 'myarn', b'foo', {}, {}) == 'arn:12345:name'
        stubbed_session.verify_stubs()

    def test_create_function_is_retried_and_succeeds(self, stubbed_session):
        kwargs = {
            'FunctionName': 'name',
            'Runtime': 'python2.7',
            'Code': {'ZipFile': b'foo'},
            'Handler': 'app.app',
            'Role': 'myarn',
            'Timeout': 60,
            'Environment': {'Variables': {'KEY': 'value'}},
            'VpcConfig': {'SubnetIds': ['12345'], 'SecurityGroupIds': ['67890']}
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
            'name', 'myarn', b'foo', {'KEY': 'value'},
            {'subnet_ids': ['12345'], 'security_group_ids': ['67890']}
        ) == 'arn:12345:name'
        stubbed_session.verify_stubs()

    def test_create_function_fails_after_max_retries(self, stubbed_session):
        kwargs = {
            'FunctionName': 'name',
            'Runtime': 'python2.7',
            'Code': {'ZipFile': b'foo'},
            'Handler': 'app.app',
            'Role': 'myarn',
            'Timeout': 60,
            'Environment': {'Variables': {'KEY': 'value'}},
            'VpcConfig': {'SubnetIds': ['12345'], 'SecurityGroupIds': ['67890']}
        }
        for _ in range(TypedAWSClient.LAMBDA_CREATE_ATTEMPTS):
            stubbed_session.stub('lambda').create_function(
                **kwargs).raises_error(
                error_code='InvalidParameterValueException', message='')

        stubbed_session.activate_stubs()
        awsclient = TypedAWSClient(stubbed_session, mock.Mock(spec=time.sleep))
        with pytest.raises(botocore.exceptions.ClientError):
            awsclient.create_function(
                'name', 'myarn', b'foo', {'KEY': 'value'},
                {'subnet_ids': ['12345'], 'security_group_ids': ['67890']}
            )
        stubbed_session.verify_stubs()

    def test_create_function_propagates_unknown_error(self, stubbed_session):
        kwargs = {
            'FunctionName': 'name',
            'Runtime': 'python2.7',
            'Code': {'ZipFile': b'foo'},
            'Handler': 'app.app',
            'Role': 'myarn',
            'Timeout': 60,
            'Environment': {'Variables': {'KEY': 'value'}},
            'VpcConfig': {'SubnetIds': ['12345'], 'SecurityGroupIds': ['67890']}
        }
        stubbed_session.stub('lambda').create_function(
            **kwargs).raises_error(
            error_code='UnknownException', message='')
        stubbed_session.activate_stubs()
        awsclient = TypedAWSClient(stubbed_session, mock.Mock(spec=time.sleep))
        with pytest.raises(botocore.exceptions.ClientError):
            awsclient.create_function(
                'name', 'myarn', b'foo', {'KEY': 'value'},
                {'subnet_ids': ['12345'], 'security_group_ids': ['67890']}
            )
        stubbed_session.verify_stubs()


class TestUpdateFunctionConfiguration(object):
    def test_update_function_configuration_provided_args(self, stubbed_session):
        stubbed_session.stub('lambda').update_function_configuration(
            FunctionName='name',
            Role='myarn',
            Environment={'Variables': {'KEY': 'value'}},
            VpcConfig={'SubnetIds': ['12345'], 'SecurityGroupIds': ['67890']}
        ).returns({})
        stubbed_session.activate_stubs()
        awsclient = TypedAWSClient(stubbed_session)
        awsclient.update_function_configuration(
            'name', 'myarn', {'KEY': 'value'},
            {'subnet_ids': ['12345'], 'security_group_ids': ['67890']}
        )
        stubbed_session.verify_stubs()

    def test_update_function_configuration_generates_args(self, stubbed_session):
        stubbed_session.stub('lambda').update_function_configuration(
            FunctionName='name',
            Role='myarn',
            Environment={'Variables': {}},
            VpcConfig={'SubnetIds': [], 'SecurityGroupIds': []}
        ).returns({})
        stubbed_session.activate_stubs()
        awsclient = TypedAWSClient(stubbed_session)
        awsclient.update_function_configuration('name', 'myarn', {}, {})
        stubbed_session.verify_stubs()


class TestCanDeleteRolePolicy(object):
    def test_can_delete_role_policy_succeeds(self, stubbed_session):
        stubbed_session.stub('iam').delete_role_policy(
            RoleName='myrole', PolicyName='mypolicy'
        ).returns({})
        stubbed_session.activate_stubs()
        awsclient = TypedAWSClient(stubbed_session)
        awsclient.delete_role_policy('myrole', 'mypolicy')
        stubbed_session.verify_stubs()

    def test_can_delete_role_policy_succeeds_missing(self, stubbed_session):
        stubbed_session.stub('iam').delete_role_policy(
            RoleName='myrole', PolicyName='mypolicy'
        ).raises_error(error_code='NoSuchEntity', message='Missing')
        stubbed_session.activate_stubs()
        awsclient = TypedAWSClient(stubbed_session)
        awsclient.delete_role_policy('myrole', 'mypolicy')
        stubbed_session.verify_stubs()

    def test_can_delete_role_policy_fails_not_missing(self, stubbed_session):
        stubbed_session.stub('iam').delete_role_policy(
            RoleName='myrole', PolicyName='mypolicy'
        ).raises_error(error_code='TestException', message='Test Error')
        stubbed_session.activate_stubs()
        awsclient = TypedAWSClient(stubbed_session)
        with pytest.raises(botocore.exceptions.ClientError):
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

    def test_can_add_permission_for_apigateway_needed_with_policy(self, stubbed_session):
        source_arn = 'arn:aws:execute-api:us-west-2:123:rest-api-id/*'
        bad_source_arn = 'arn:aws:execute-api:us-east-1:456:not-rest-api-id/*'
        policy = {
            'Id': 'default',
            'Statement': [
                {  # Fails check on "Action"
                    'Action': 'ec2:RunInstances',
                    'Condition': {
                        'ArnLike': {
                            'AWS:SourceArn': source_arn,
                        }
                    },
                    'Effect': 'Allow',
                    'Principal': {'Service': 'apigateway.amazonaws.com'},
                    'Resource': 'arn:aws:lambda:us-west-2:account_id:function:name',
                    'Sid': 'e4755709-067e-4254-b6ec-e7f9639e6f7b'
                },
                {  # Fails check on "Condition"
                    'Action': 'lambda:InvokeFunction',
                    'Condition': {
                        'ArnLike': {
                            'AWS:SourceArn': bad_source_arn,
                        }
                    },
                    'Effect': 'Allow',
                    'Principal': {'Service': 'apigateway.amazonaws.com'},
                    'Resource': 'arn:aws:lambda:us-west-2:account_id:function:name',
                    'Sid': 'e4755709-067e-4254-b6ec-e7f9639e6f7b'
                },
                {  # Fails check on "Principal"
                    'Action': 'lambda:InvokeFunction',
                    'Condition': {
                        'ArnLike': {
                            'AWS:SourceArn': source_arn,
                        }
                    },
                    'Effect': 'Allow',
                    'Principal': {'Service': 'ec2.amazonaws.com'},
                    'Resource': 'arn:aws:lambda:us-west-2:account_id:function:name',
                    'Sid': 'e4755709-067e-4254-b6ec-e7f9639e6f7b'
                }
            ],
            'Version': '2012-10-17'
        }
        lambda_stub = stubbed_session.stub('lambda')
        lambda_stub.get_policy(
            FunctionName='name').returns({'Policy': json.dumps(policy)})
        self.should_call_add_permission(lambda_stub)

        # Because the policy above indicates that a policy exists but API
        # gateway does NOT have the necessary permissions, we call add_permission.
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

    def test_can_add_permission_fails_get(self, stubbed_session):
        # It's also possible to receive a ResourceNotFoundException
        # if you call get_policy() on a lambda function with no policy.
        lambda_stub = stubbed_session.stub('lambda')
        lambda_stub.get_policy(FunctionName='name').raises_error(
            error_code='FakeError', message='Does not exist.')
        self.should_call_add_permission(lambda_stub)
        stubbed_session.activate_stubs()
        with pytest.raises(botocore.exceptions.ClientError):
            TypedAWSClient(stubbed_session).add_permission_for_apigateway_if_needed(
                'name', 'us-west-2', '123', 'rest-api-id', 'random-id')


class TestGetSecurityGroupIdForName(object):
    def test_get_security_group_id_for_name_finds_group(self, stubbed_session):
        stubbed_session.stub('ec2').describe_security_groups(
            Filters=[{'Name': 'group-name', 'Values': ['name']}]
        ).returns(
            {
                'SecurityGroups': [
                    {'GroupName': 'name', 'GroupId': '55555', 'VpcId': '67890'}
                ]
            }
        )
        stubbed_session.activate_stubs()
        awsclient = TypedAWSClient(stubbed_session)
        assert awsclient.get_security_group_id_for_name('name') == ('55555', '67890')
        stubbed_session.verify_stubs()

    def test_get_security_group_id_for_name_not_find_group(self, stubbed_session):
        stubbed_session.stub('ec2').describe_security_groups(
            Filters=[{'Name': 'group-name', 'Values': ['name']}]
        ).returns({'SecurityGroups': [{'GroupName': 'not_name', 'GroupId': '4444'}]})
        stubbed_session.activate_stubs()
        awsclient = TypedAWSClient(stubbed_session)
        assert awsclient.get_security_group_id_for_name('name') == ('', '')
        stubbed_session.verify_stubs()


class TestGetVpcIdForSubnetId(object):
    def test_get_vpc_id_for_subnet_id_finds_subnet(self, stubbed_session):
        stubbed_session.stub('ec2').describe_subnets(
            SubnetIds=['12345']
        ).returns({'Subnets': [{'VpcId': '67890'}]})
        stubbed_session.activate_stubs()
        awsclient = TypedAWSClient(stubbed_session)
        assert awsclient.get_vpc_id_for_subnet_id('12345') == '67890'
        stubbed_session.verify_stubs()

    def test_get_vpc_id_for_subnet_id_not_finds_subnet(self, stubbed_session):
        stubbed_session.stub('ec2').describe_subnets(
            SubnetIds=['12345']
        ).returns({})
        stubbed_session.activate_stubs()
        awsclient = TypedAWSClient(stubbed_session)
        with pytest.raises(ValueError):
            awsclient.get_vpc_id_for_subnet_id('12345')
        stubbed_session.verify_stubs()


class TestDownloadSdk(object):
    """These tests call on the fake API zip files in the
    test/support_files directory"""
    class FakeRawObject(object):
        def __init__(self, stream):
            self.stored_object = stream

        def read(self, amt):
            return self.stored_object

    def test_download_sdk_succeeds(self, stubbed_session):
        support_files = os.path.join(
            os.path.dirname(os.path.dirname(os.path.realpath(__file__))),
            'support_files'
        )
        with open(os.path.join(support_files, 'good_api.zip'), 'rb') as good_zip:
            good_object = self.FakeRawObject(good_zip.read())
        good_body = StreamingBody(good_object, None)
        stubbed_session.stub('apigateway').get_sdk(
            restApiId='rest-api-id',
            stageName='dev',
            sdkType='javascript'
        ).returns({'body': good_body})
        stubbed_session.activate_stubs()
        awsclient = TypedAWSClient(stubbed_session)
        awsclient.download_sdk(
            'rest-api-id', tempfile.mkdtemp(), 'dev', 'javascript'
        )
        stubbed_session.verify_stubs()

    def test_download_sdk_unexpected_structure(self, stubbed_session):
        support_files = os.path.join(
            os.path.dirname(os.path.dirname(os.path.realpath(__file__))),
            'support_files'
        )
        with open(os.path.join(support_files, 'bad_api.zip'), 'rb') as bad_zip:
            bad_object = self.FakeRawObject(bad_zip.read())
        bad_body = StreamingBody(bad_object, None)
        stubbed_session.stub('apigateway').get_sdk(
            restApiId='rest-api-id',
            stageName='dev',
            sdkType='javascript'
        ).returns({'body': bad_body})
        stubbed_session.activate_stubs()
        awsclient = TypedAWSClient(stubbed_session)
        with pytest.raises(RuntimeError):
            awsclient.download_sdk(
                'rest-api-id', tempfile.mkdtemp(), 'dev', 'javascript'
            )
        stubbed_session.verify_stubs()
