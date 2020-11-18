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
from botocore.utils import datetime2timestamp

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
        restApiId='api_id', stageName='stage',
        tracingEnabled=False).returns({})

    stubbed_session.activate_stubs()
    awsclient = TypedAWSClient(stubbed_session)
    awsclient.deploy_rest_api('api_id', 'stage', False)
    stubbed_session.verify_stubs()


def test_defaults_to_false_if_none_deploy_rest_api(stubbed_session):
    stub_client = stubbed_session.stub('apigateway')
    stub_client.create_deployment(
        restApiId='api_id', stageName='stage',
        tracingEnabled=False).returns({})

    stubbed_session.activate_stubs()
    awsclient = TypedAWSClient(stubbed_session)
    awsclient.deploy_rest_api('api_id', 'stage', None)
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
        restApiId='api').returns({'id': 'api'})
    stubbed_session.activate_stubs()

    awsclient = TypedAWSClient(stubbed_session)
    assert awsclient.get_rest_api('api')

    stubbed_session.verify_stubs()


def test_rest_api_not_exists(stubbed_session):
    stubbed_session.stub('apigateway').get_rest_api(
        restApiId='api').raises_error(
            error_code='NotFoundException',
            message='ResourceNotFound')
    stubbed_session.activate_stubs()

    awsclient = TypedAWSClient(stubbed_session)
    assert not awsclient.get_rest_api('api')

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
    timestamp = datetime.datetime.utcfromtimestamp(1501278366)
    assert logs == [
        {'logStreamName': 'logStreamName',
         # We should have converted the ints to timestamps.
         'timestamp': timestamp,
         'message': 'message',
         'ingestionTime': timestamp,
         'eventId': 'eventId'}
    ]

    stubbed_session.verify_stubs()


def test_can_provide_optional_start_time_iter_logs(stubbed_session):
    timestamp = int(datetime2timestamp(datetime.datetime.utcnow()) * 1000)
    # We need to convert back from timestamp instead of using utcnow() directly
    # because the loss of precision in sub ms time.
    datetime_now = datetime.datetime.utcfromtimestamp(timestamp / 1000.0)
    stubbed_session.stub('logs').filter_log_events(
        logGroupName='loggroup', interleaved=True).returns({
            "events": [{
                "logStreamName": "logStreamName",
                "timestamp": timestamp,
                "message": "message",
                "ingestionTime": timestamp,
                "eventId": "eventId"
            }],
        })

    stubbed_session.activate_stubs()

    awsclient = TypedAWSClient(stubbed_session)
    logs = list(awsclient.iter_log_events('loggroup', start_time=datetime_now))
    assert logs == [
        {'logStreamName': 'logStreamName',
         'timestamp': datetime_now,
         'message': 'message',
         'ingestionTime': datetime_now,
         'eventId': 'eventId'}
    ]

    stubbed_session.verify_stubs()


def test_missing_log_messages_doesnt_fail(stubbed_session):
    stubbed_session.stub('logs').filter_log_events(
        logGroupName='loggroup', interleaved=True).raises_error(
            error_code='ResourceNotFoundException',
            message='ResourceNotFound')
    stubbed_session.activate_stubs()

    awsclient = TypedAWSClient(stubbed_session)
    logs = list(awsclient.iter_log_events('loggroup'))
    assert logs == []


def test_can_call_filter_log_events(stubbed_session):
    stubbed_session.stub('logs').filter_log_events(
        logGroupName='loggroup', interleaved=True,
        nextToken='nexttoken', startTime=1577836800000.0
    ).returns({
        "events": [{
            "logStreamName": "logStreamName",
            "timestamp": 1501278366000,
            "message": "message",
            "ingestionTime": 1501278366000,
            "eventId": "eventId"
        }],
    })
    stubbed_session.activate_stubs()
    timestamp = datetime.datetime.utcfromtimestamp(1501278366)
    awsclient = TypedAWSClient(stubbed_session)
    assert awsclient.filter_log_events(
        log_group_name='loggroup',
        next_token='nexttoken',
        start_time=datetime.datetime(2020, 1, 1)
    ) == {
        'events': [{
            "logStreamName": "logStreamName",
            "timestamp": timestamp,
            "message": "message",
            "ingestionTime": timestamp,
            "eventId": "eventId"
        }]
    }


def test_optional_kwarg_on_filter_logs_omitted(stubbed_session):
    stubbed_session.stub('logs').filter_log_events(
        logGroupName='loggroup', interleaved=True,
    ).returns({
        "events": [{
            "logStreamName": "logStreamName",
            "timestamp": 1501278366000,
            "message": "message",
            "ingestionTime": 1501278366000,
            "eventId": "eventId"
        }],
    })
    stubbed_session.activate_stubs()
    timestamp = datetime.datetime.utcfromtimestamp(1501278366)
    awsclient = TypedAWSClient(stubbed_session)
    assert awsclient.filter_log_events(
        log_group_name='loggroup',
    ) == {
        'events': [{
            "logStreamName": "logStreamName",
            "timestamp": timestamp,
            "message": "message",
            "ingestionTime": timestamp,
            "eventId": "eventId"
        }]
    }


def test_missing_log_events_returns_empty_response(stubbed_session):
    stubbed_session.stub('logs').filter_log_events(
        logGroupName='loggroup', interleaved=True).raises_error(
            error_code='ResourceNotFoundException',
            message='ResourceNotFound')
    stubbed_session.activate_stubs()

    awsclient = TypedAWSClient(stubbed_session)
    assert awsclient.filter_log_events(
        log_group_name='loggroup',
    ) == {'events': []}


def test_rule_arn_requires_expression_or_pattern(stubbed_session):
    client = TypedAWSClient(stubbed_session)
    with pytest.raises(ValueError):
        client.get_or_create_rule_arn("foo")


class TestLambdaLayer(object):

    def test_layer_exists(self, stubbed_session):
        stubbed_session.stub('lambda').get_layer_version_by_arn(
            Arn='arn:xyz').returns(
                {'LayerVersionArn': 'arn:xyz'})
        stubbed_session.activate_stubs()
        awsclient = TypedAWSClient(stubbed_session)
        assert awsclient.get_layer_version('arn:xyz') == {
            'LayerVersionArn': 'arn:xyz'}

    def test_layer_exists_not_found_error(self, stubbed_session):
        stubbed_session.stub('lambda').get_layer_version_by_arn(
            Arn='arn:xyz').raises_error(
                error_code='ResourceNotFoundException',
                message='Not Found')
        stubbed_session.activate_stubs()
        awsclient = TypedAWSClient(stubbed_session)
        assert awsclient.get_layer_version('arn:xyz') == {}

    def test_layer_delete_not_found_error(self, stubbed_session):
        stubbed_session.stub('lambda').delete_layer_version(
            LayerName='xyz',
            VersionNumber=4).raises_error(
                error_code='ResourceNotFoundException',
                message='Not Found')
        stubbed_session.activate_stubs()
        awsclient = TypedAWSClient(stubbed_session)
        assert awsclient.delete_layer_version('arn:xyz:4') is None

    def test_publish_layer_propagate_error(self, stubbed_session):
        stubbed_session.stub('lambda').publish_layer_version(
            LayerName='name',
            CompatibleRuntimes=['python2.7'],
            Content={'ZipFile': b'foo'},
        ).raises_error(error_code='UnexpectedError',
                       message='Unknown')
        stubbed_session.activate_stubs()

        awsclient = TypedAWSClient(stubbed_session)
        with pytest.raises(LambdaClientError) as excinfo:
            awsclient.publish_layer(
                'name', b'foo', 'python2.7') == 'arn:12345:name'
        assert isinstance(
            excinfo.value.original_error, botocore.exceptions.ClientError)
        stubbed_session.verify_stubs()

    def test_can_publish_layer(self, stubbed_session):
        stubbed_session.stub('lambda').publish_layer_version(
            LayerName='name',
            CompatibleRuntimes=['python2.7'],
            Content={'ZipFile': b'foo'},
        ).returns({'LayerVersionArn': 'arn:12345:name:3'})
        stubbed_session.activate_stubs()
        awsclient = TypedAWSClient(stubbed_session)
        assert awsclient.publish_layer(
            'name', b'foo', 'python2.7') == 'arn:12345:name:3'
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


class TestGetDomainName(object):
    def test_get_domain_name(self, stubbed_session):
        domain_name = 'test_domain'
        certificate_arn = 'arn:aws:acm:us-east-1:aws_id:certificate/12345'
        regional_name = 'test.execute-api.us-east-1.amazonaws.com'
        stubbed_session.stub('apigateway')\
            .get_domain_name(domainName=domain_name)\
            .returns({
                'domainName': 'test_domain',
                'certificateUploadDate': datetime.datetime.now(),
                'regionalDomainName': regional_name,
                'regionalHostedZoneId': 'TEST1TEST1TESTQ1',
                'regionalCertificateArn': certificate_arn,
                'endpointConfiguration': {
                    'types': ['REGIONAL']
                },
                'domainNameStatus': 'AVAILABLE',
                'securityPolicy': 'TLS_1_0',
                'tags': {
                    'some_key1': 'test_value1',
                    'some_key2': 'test_value2'
                }
            })
        stubbed_session.activate_stubs()
        awsclient = TypedAWSClient(stubbed_session)
        result = awsclient.get_domain_name(domain_name)['domainName']
        assert result == domain_name

    def test_get_domain_name_failed(self, stubbed_session):
        domain_name = 'unknown_domain'
        stubbed_session.stub('apigateway') \
            .get_domain_name(domainName=domain_name) \
            .raises_error(error_code='NotFoundException',
                          message='Unknown')
        stubbed_session.activate_stubs()

        awsclient = TypedAWSClient(stubbed_session)
        with pytest.raises(ResourceDoesNotExistError):
            assert awsclient.get_domain_name(domain_name)

    def test_domain_name_exists(self, stubbed_session):
        domain_name = 'test_domain'
        certificate_arn = 'arn:aws:acm:us-east-1:aws_id:certificate/12345'
        regional_name = 'test.execute-api.us-east-1.amazonaws.com'
        stubbed_session.stub('apigateway')\
            .get_domain_name(domainName=domain_name)\
            .returns({
                'domainName': 'test_domain',
                'certificateUploadDate': datetime.datetime.now(),
                'regionalDomainName': regional_name,
                'regionalHostedZoneId': 'TEST1TEST1TESTQ1',
                'regionalCertificateArn': certificate_arn,
                'endpointConfiguration': {
                    'types': ['REGIONAL']
                },
                'domainNameStatus': 'AVAILABLE',
                'securityPolicy': 'TLS_1_0',
                'tags': {
                    'some_key1': 'test_value1',
                    'some_key2': 'test_value2'
                }
            })
        stubbed_session.activate_stubs()
        awsclient = TypedAWSClient(stubbed_session)
        assert awsclient.domain_name_exists(domain_name)

    def test_domain_name_does_not_exist(self, stubbed_session):
        domain_name = 'unknown_domain'
        stubbed_session.stub('apigateway') \
            .get_domain_name(domainName=domain_name) \
            .raises_error(error_code='NotFoundException',
                          message='Unknown')
        stubbed_session.activate_stubs()

        awsclient = TypedAWSClient(stubbed_session)
        assert not awsclient.domain_name_exists(domain_name)

    def test_domain_name_exists_v2(self, stubbed_session):
        domain_name = 'test_domain'
        certificate_arn = 'arn:aws:acm:us-east-1:aws_id:certificate/12345'
        regional_name = 'test.execute-api.us-east-1.amazonaws.com'
        stubbed_session.stub('apigatewayv2') \
            .get_domain_name(DomainName=domain_name) \
            .returns({
                'DomainName': 'test_domain',
                'DomainNameConfigurations': [{
                    'ApiGatewayDomainName': regional_name,
                    'CertificateArn': certificate_arn,
                    'EndpointType': 'REGIONAL',
                    'HostedZoneId': 'TEST1TEST1TESTQ1',
                    'SecurityPolicy': 'TLS_1_0',
                    'DomainNameStatus': 'AVAILABLE'
                }],
                'Tags': {
                    'some_key1': 'some_value1',
                    'some_key2': 'some_value2'
                }
            })
        stubbed_session.activate_stubs()
        awsclient = TypedAWSClient(stubbed_session)
        assert awsclient.domain_name_exists_v2(domain_name)

    def test_domain_name_does_not_exist_v2(self, stubbed_session):
        domain_name = 'unknown_domain'
        stubbed_session.stub('apigatewayv2') \
            .get_domain_name(DomainName=domain_name) \
            .raises_error(
                error_code='NotFoundException',
                message='Unknown'
            )
        stubbed_session.activate_stubs()

        awsclient = TypedAWSClient(stubbed_session)
        assert not awsclient.domain_name_exists_v2(domain_name)


class TestGetApiMapping(object):
    def test_api_mapping_exists(self, stubbed_session):
        domain_name = 'test_domain'
        path = '(none)'
        stubbed_session.stub('apigatewayv2') \
            .get_api_mappings(
                DomainName=domain_name,
            ).returns({
                'Items': [{
                    'ApiMappingKey': '(none)',
                    'ApiMappingId': 'mapping_id',
                    'ApiId': 'rest_api_id',
                    'Stage': 'test'
                }]
            })
        stubbed_session.activate_stubs()
        awsclient = TypedAWSClient(stubbed_session)
        assert awsclient.api_mapping_exists(domain_name, path)

    def test_api_mapping_not_exists(self, stubbed_session):
        domain_name = 'test_domain'
        path = 'path-key'
        stubbed_session.stub('apigatewayv2') \
            .get_api_mappings(
                DomainName=domain_name,
            ).returns({
                'Items': [{
                    'ApiMappingKey': '(none)',
                    'ApiMappingId': 'mapping_id',
                    'ApiId': 'rest_api_id',
                    'Stage': 'test'
                }]
            })
        stubbed_session.activate_stubs()
        awsclient = TypedAWSClient(stubbed_session)
        assert not awsclient.api_mapping_exists(domain_name, path)

    def test_api_mapping_does_not_exist(self, stubbed_session):
        domain_name = 'unknown_domain'
        path = '/unknown'
        stubbed_session.stub('apigatewayv2') \
            .get_api_mappings(
                DomainName=domain_name,
            ).raises_error(
                error_code='NotFoundException',
                message='Unknown'
            )
        stubbed_session.activate_stubs()
        awsclient = TypedAWSClient(stubbed_session)
        assert not awsclient.api_mapping_exists(domain_name, path)


class TestCreateApiMapping(object):
    def test_create_api_mapping(self, stubbed_session):
        domain_name = 'test_domain'
        path_key = '(none)'
        api_id = 'rest_api_id'
        stage = 'test'
        stubbed_session.stub('apigatewayv2') \
            .create_api_mapping(
            DomainName=domain_name,
            ApiMappingKey=path_key,
            ApiId=api_id,
            Stage=stage
        ).returns({
            'ApiId': api_id,
            'ApiMappingId': 'key_id',
            'ApiMappingKey': '(none)',
            'Stage': stage
        })
        stubbed_session.activate_stubs()
        awsclient = TypedAWSClient(stubbed_session)
        assert awsclient.create_api_mapping(
            domain_name=domain_name,
            path_key=path_key,
            api_id=api_id,
            stage=stage
        ) == {
            'key': '/'
        }

    def test_create_api_mapping_with_path(self, stubbed_session):
        domain_name = 'test_domain'
        path_key = 'path-key'
        api_id = 'rest_api_id'
        stage = 'test'
        stubbed_session.stub('apigatewayv2') \
            .create_api_mapping(
            DomainName=domain_name,
            ApiMappingKey=path_key,
            ApiId=api_id,
            Stage=stage
        ).returns({
            'ApiId': api_id,
            'ApiMappingId': 'key_id',
            'ApiMappingKey': 'path-key',
            'Stage': stage
        })
        stubbed_session.activate_stubs()
        awsclient = TypedAWSClient(stubbed_session)
        assert awsclient.create_api_mapping(
            domain_name=domain_name,
            path_key=path_key,
            api_id=api_id,
            stage=stage
        ) == {
            'key': '/path-key'
        }


class TestCreateBasePathMapping(object):
    def test_create_base_path_mapping(self, stubbed_session):
        domain_name = 'test_domain'
        path_key = '(none)'
        api_id = 'rest_api_id'
        stage = 'test'
        stubbed_session.stub('apigateway') \
            .create_base_path_mapping(
                domainName=domain_name,
                basePath=path_key,
                restApiId=api_id,
                stage=stage
            ).returns({
                'restApiId': api_id,
                'basePath': '(none)',
                'stage': stage
            })
        stubbed_session.activate_stubs()
        awsclient = TypedAWSClient(stubbed_session)
        assert awsclient.create_base_path_mapping(
            domain_name=domain_name,
            path_key=path_key,
            api_id=api_id,
            stage=stage
        ) == {
            'key': '/'
        }

    def test_create_base_path_mapping_with_path(self, stubbed_session):
        domain_name = 'test_domain'
        path_key = 'path-key'
        api_id = 'rest_api_id'
        stage = 'test'
        stubbed_session.stub('apigateway') \
            .create_base_path_mapping(
                domainName=domain_name,
                basePath=path_key,
                restApiId=api_id,
                stage=stage
            ).returns({
                'restApiId': api_id,
                'basePath': 'path-key',
                'stage': stage
            })
        stubbed_session.activate_stubs()
        awsclient = TypedAWSClient(stubbed_session)
        assert awsclient.create_base_path_mapping(
            domain_name=domain_name,
            path_key=path_key,
            api_id=api_id,
            stage=stage
        ) == {
            'key': '/path-key'
        }

    def test_create_base_path_mapping_failed(self, stubbed_session):
        domain_name = 'test_domain'
        path_key = '/test'
        api_id = 'rest_api_id'
        stage = 'test'

        err_msg = 'An ApiMapping key may contain only letters, ' \
                  'numbers and one of $-_.+!*\'()'
        stubbed_session.stub('apigateway') \
            .create_base_path_mapping(
                domainName=domain_name,
                basePath=path_key,
                restApiId=api_id,
                stage=stage
            ).raises_error(
                error_code='BadRequestException',
                message=err_msg
            )
        stubbed_session.activate_stubs()
        awsclient = TypedAWSClient(stubbed_session)
        with pytest.raises(botocore.exceptions.ClientError):
            awsclient.create_base_path_mapping(
                domain_name=domain_name,
                path_key=path_key,
                api_id=api_id,
                stage=stage
            )


class TestCreateDomainName(object):

    def test_create_domain_name_with_unsupported_protocol(
            self, stubbed_session
    ):
        awsclient = TypedAWSClient(stubbed_session)
        params = {
            'protocol': 'SOME_PROTOCOL',
            'domain_name': 'test_domain',
            'endpoint_type': 'REGIONAL',
            'security_policy': 'TLS_1_0',
            'certificate_arn': 'certificate_arn',
            'tags': None
        }
        with pytest.raises(ValueError):
            awsclient.create_domain_name(**params)

    def test_create_rest_api_domain_name(self, stubbed_session):
        stubbed_session.stub('apigateway') \
            .create_domain_name(
                domainName='test_domain',
                endpointConfiguration={
                    'types': ['REGIONAL']
                },
                securityPolicy='TLS_1_0',
                tags={
                  'some_key1': 'some_value1',
                  'some_key2': 'some_value2'
                },
                regionalCertificateArn='certificate_arn',
            ).returns({
                'domainName': 'test_domain',
                'regionalCertificateName': 'certificate_name',
                'regionalCertificateArn': 'certificate_arn',
                'regionalDomainName': 'regional_domain_name',
                'regionalHostedZoneId': 'hosted_zone_id',
                'endpointConfiguration': {
                    'types': ['REGIONAL'],
                },
                'domainNameStatus': 'AVAILABLE',
                'domainNameStatusMessage': 'string',
                'securityPolicy': 'TLS_1_0',
                'tags': {
                    'some_key1': 'some_value1',
                    'some_key2': 'some_value2'
                }
            })
        stubbed_session.activate_stubs()
        awsclient = TypedAWSClient(stubbed_session)
        assert awsclient.create_domain_name(
            protocol='HTTP',
            domain_name='test_domain',
            endpoint_type='REGIONAL',
            security_policy='TLS_1_0',
            certificate_arn='certificate_arn',
            tags={
              'some_key1': 'some_value1',
              'some_key2': 'some_value2'
            }
        ) == {
            'domain_name': 'test_domain',
            'security_policy': 'TLS_1_0',
            'alias_domain_name': 'regional_domain_name',
            'hosted_zone_id': 'hosted_zone_id',
            'certificate_arn': 'certificate_arn'
        }
        stubbed_session.verify_stubs()

    def test_create_rest_api_domain_name_no_regional(self, stubbed_session):
        stubbed_session.stub('apigateway') \
            .create_domain_name(
                domainName='test_domain',
                endpointConfiguration={
                    'types': ['EDGE']
                },
                securityPolicy='TLS_1_0',
                tags={
                  'some_key1': 'some_value1',
                  'some_key2': 'some_value2'
                },
                certificateArn='certificate_arn',
            ).returns({
                'domainName': 'test_domain',
                'certificateName': 'certificate_name',
                'certificateArn': 'certificate_arn',
                'certificateUploadDate': datetime.datetime.now(),
                'endpointConfiguration': {
                    'types': ['EDGE'],
                },
                'distributionDomainName': 'dist_test_domain',
                'distributionHostedZoneId': 'hosted_zone_id',
                'domainNameStatus': 'AVAILABLE',
                'domainNameStatusMessage': 'string',
                'securityPolicy': 'TLS_1_0',
                'tags': {
                    'some_key1': 'some_value1',
                    'some_key2': 'some_value2'
                }
            })
        stubbed_session.activate_stubs()
        awsclient = TypedAWSClient(stubbed_session)
        assert awsclient.create_domain_name(
            protocol='HTTP',
            domain_name='test_domain',
            endpoint_type='EDGE',
            security_policy='TLS_1_0',
            certificate_arn='certificate_arn',
            tags={
              'some_key1': 'some_value1',
              'some_key2': 'some_value2'
            }
        ) == {
            'domain_name': 'test_domain',
            'security_policy': 'TLS_1_0',
            'hosted_zone_id': 'hosted_zone_id',
            'alias_domain_name': 'dist_test_domain',
            'certificate_arn': 'certificate_arn'
        }
        stubbed_session.verify_stubs()

    def test_create_websocket_api_custom_domain(self, stubbed_session):
        stubbed_session.stub('apigatewayv2') \
            .create_domain_name(
                DomainName='test_websocket_domain',
                DomainNameConfigurations=[{
                    'ApiGatewayDomainName': 'test_websocket_domain',
                    'CertificateArn': 'certificate_arn',
                    'EndpointType': 'REGIONAL',
                    'SecurityPolicy': 'TLS_1_2',
                    'DomainNameStatus': 'AVAILABLE',
                }],
                Tags={
                    'some_key1': 'some_value1',
                    'some_key2': 'some_value2'
                }
            ).returns({
                'DomainName': 'test_websocket_domain',
                'DomainNameConfigurations': [
                    {
                        'ApiGatewayDomainName': 'd-1234',
                        'CertificateArn': 'certificate_arn',
                        'CertificateName': 'certificate_name',
                        'CertificateUploadDate': datetime.datetime.now(),
                        'EndpointType': 'REGIONAL',
                        'HostedZoneId': 'hosted_zone_id',
                        'SecurityPolicy': 'TLS_1_2',
                        'DomainNameStatus': 'AVAILABLE',
                    },
                ],
                'Tags': {
                    'some_key1': 'some_value1',
                    'some_key2': 'some_value2'
                }
            })
        stubbed_session.activate_stubs()
        awsclient = TypedAWSClient(stubbed_session)
        assert awsclient.create_domain_name(
            protocol='WEBSOCKET',
            domain_name='test_websocket_domain',
            endpoint_type='REGIONAL',
            security_policy='TLS_1_2',
            certificate_arn='certificate_arn',
            tags={
              'some_key1': 'some_value1',
              'some_key2': 'some_value2'
            }
        ) == {
            'domain_name': 'test_websocket_domain',
            'alias_domain_name': 'd-1234',
            'security_policy': 'TLS_1_2',
            'hosted_zone_id': 'hosted_zone_id',
            'certificate_arn': 'certificate_arn'
        }
        stubbed_session.verify_stubs()

    def test_get_custom_domain_params_v2(self, stubbed_session):
        awsclient = TypedAWSClient(stubbed_session)
        result = awsclient.get_custom_domain_params_v2(
            domain_name='test_domain_name',
            endpoint_type='EDGE',
            security_policy='TLS_1_2',
            certificate_arn='certificate_arn',
            tags={
              'some_key1': 'some_value1',
              'some_key2': 'some_value2'
            },
        )
        assert result == {
            'DomainName': 'test_domain_name',
            'DomainNameConfigurations': [
                {
                    'ApiGatewayDomainName': 'test_domain_name',
                    'CertificateArn': 'certificate_arn',
                    'EndpointType': 'EDGE',
                    'SecurityPolicy': 'TLS_1_2',
                    'DomainNameStatus': 'AVAILABLE',
                },
            ],
            'Tags': {
                'some_key1': 'some_value1',
                'some_key2': 'some_value2'
            }
        }

    def test_create_domain_name_max_retries(self, stubbed_session):
        for _ in range(6):
            stubbed_session.stub('apigateway') \
                .create_domain_name(
                domainName='test_domain',
                endpointConfiguration={
                    'types': ['EDGE']
                },
                securityPolicy='TLS_1_0',
                tags={
                    'some_key1': 'some_value1',
                    'some_key2': 'some_value2'
                },
                certificateArn='certificate_arn'
            ).raises_error(
                error_code='TooManyRequestsException',
                message='Too Many Requests'
            )
        stubbed_session.activate_stubs()
        awsclient = TypedAWSClient(stubbed_session, mock.Mock(spec=time.sleep))
        with pytest.raises(botocore.exceptions.ClientError):
            awsclient.create_domain_name(
                protocol='HTTP',
                domain_name='test_domain',
                endpoint_type='EDGE',
                security_policy='TLS_1_0',
                certificate_arn='certificate_arn',
                tags={
                    'some_key1': 'some_value1',
                    'some_key2': 'some_value2'
                }
            )

    def test_create_domain_name_v2_max_retries(self, stubbed_session):
        for _ in range(6):
            stubbed_session.stub('apigatewayv2') \
                .create_domain_name(
                DomainName='test_websocket_domain',
                DomainNameConfigurations=[{
                    'ApiGatewayDomainName': 'test_websocket_domain',
                    'CertificateArn': 'certificate_arn',
                    'EndpointType': 'REGIONAL',
                    'SecurityPolicy': 'TLS_1_2',
                    'DomainNameStatus': 'AVAILABLE',
                }],
                Tags={
                    'some_key1': 'some_value1',
                    'some_key2': 'some_value2'
                }
            ).raises_error(
                error_code='TooManyRequestsException',
                message='Too Many Requests'
            )
        stubbed_session.activate_stubs()
        awsclient = TypedAWSClient(stubbed_session, mock.Mock(spec=time.sleep))
        with pytest.raises(botocore.exceptions.ClientError):
            awsclient.create_domain_name(
                protocol='WEBSOCKET',
                domain_name='test_websocket_domain',
                endpoint_type='REGIONAL',
                security_policy='TLS_1_2',
                certificate_arn='certificate_arn',
                tags={
                    'some_key1': 'some_value1',
                    'some_key2': 'some_value2'
                }
            )


class TestUpdateDomainName(object):
    def test_update_domain_name_websocket(self,
                                          stubbed_session):
        stubbed_session.stub('apigatewayv2') \
            .update_domain_name(
            DomainName='test_domain',
            DomainNameConfigurations=[{
                'ApiGatewayDomainName': 'test_domain',
                'CertificateArn': 'certificate_arn',
                'EndpointType': 'REGIONAL',
                'SecurityPolicy': 'TLS_1_2',
                'DomainNameStatus': 'AVAILABLE',
            }]
        ).returns({
            'DomainName': 'test_domain',
            'DomainNameConfigurations': [
                {
                    'ApiGatewayDomainName': 'd-1234',
                    'CertificateArn': 'certificate_arn',
                    'CertificateName': 'certificate_name',
                    'CertificateUploadDate': datetime.datetime.now(),
                    'EndpointType': 'REGIONAL',
                    'HostedZoneId': 'hosted_zone_id',
                    'SecurityPolicy': 'TLS_1_2',
                    'DomainNameStatus': 'AVAILABLE',
                },
            ]
        })
        arn = 'arn:aws:apigateway:us-west-2::/domainnames/test_domain'
        stubbed_session.stub('apigatewayv2') \
            .get_tags(ResourceArn=arn) \
            .returns({
                'Tags': {}
            })
        stubbed_session.activate_stubs()
        awsclient = TypedAWSClient(stubbed_session)
        assert awsclient.update_domain_name(
            protocol='WEBSOCKET',
            domain_name='test_domain',
            endpoint_type='REGIONAL',
            security_policy='TLS_1_2',
            certificate_arn='certificate_arn',
        ) == {
            'domain_name': 'test_domain',
            'alias_domain_name': 'd-1234',
            'security_policy': 'TLS_1_2',
            'hosted_zone_id': 'hosted_zone_id',
            'certificate_arn': 'certificate_arn'
        }
        stubbed_session.verify_stubs()

    def test_update_domain_name_failed(self, stubbed_session):
        err_msg = 'The resource specified in the request was not found.'
        stubbed_session.stub('apigatewayv2') \
            .update_domain_name(
            DomainName='unknown_domain',
            DomainNameConfigurations=[{
                'ApiGatewayDomainName': 'unknown_domain',
                'CertificateArn': 'certificate_arn',
                'EndpointType': 'REGIONAL',
                'SecurityPolicy': 'TLS_1_2',
                'DomainNameStatus': 'AVAILABLE',
            }]).raises_error(
                error_code='NotFoundException',
                message=err_msg
            )

        awsclient = TypedAWSClient(stubbed_session)
        with pytest.raises(botocore.exceptions.ClientError):
            awsclient.update_domain_name(
                protocol='WEBSOCKET',
                domain_name='unknown_domain',
                endpoint_type='REGIONAL',
                security_policy='TLS_1_2',
                certificate_arn='certificate_arn',
            )

    def test_update_domain_v2_name_max_retries(self, stubbed_session):
        for _ in range(6):
            stubbed_session.stub('apigatewayv2') \
                .update_domain_name(
                DomainName='test_domain',
                DomainNameConfigurations=[{
                    'ApiGatewayDomainName': 'test_domain',
                    'CertificateArn': 'certificate_arn',
                    'EndpointType': 'REGIONAL',
                    'SecurityPolicy': 'TLS_1_2',
                    'DomainNameStatus': 'AVAILABLE',
                }],
                Tags={
                    'some_key1': 'some_value1',
                    'some_key2': 'some_value2'
                }
            ).raises_error(
                error_code='TooManyRequestsException',
                message='Too Many Requests'
            )
        stubbed_session.activate_stubs()
        awsclient = TypedAWSClient(stubbed_session, mock.Mock(spec=time.sleep))
        with pytest.raises(botocore.exceptions.ClientError):
            awsclient.update_domain_name(
                protocol='WEBSOCKET',
                domain_name='test_domain',
                endpoint_type='REGIONAL',
                security_policy='TLS_1_2',
                certificate_arn='certificate_arn',
                tags={
                    'some_key1': 'some_value1',
                    'some_key2': 'some_value2'
                }
            )

    def test_unsupported_protocol(self, stubbed_session):
        awsclient = TypedAWSClient(stubbed_session)
        with pytest.raises(ValueError) as err:
            awsclient.update_domain_name(
                protocol='unsupported',
                domain_name='unknown_domain',
                endpoint_type='REGIONAL',
                security_policy='TLS_1_2',
                certificate_arn='certificate_arn',
            )
        assert str(err.value) == 'Unsupported protocol value.'

    def test_get_custom_domain_patch_operations(self, stubbed_session):
        awsclient = TypedAWSClient(stubbed_session)
        patch_operations = awsclient.get_custom_domain_patch_operations(
            security_policy='TLS_1_0',
            certificate_arn='certificate_arn',
            endpoint_type='EDGE',
        )
        assert patch_operations == [
            {
                'op': 'replace',
                'path': '/securityPolicy',
                'value': 'TLS_1_0',
            },
            {
                'op': 'replace',
                'path': '/certificateArn',
                'value': 'certificate_arn',
            }
        ]

    def test_get_custom_domain_patch_operations_regional(
            self,
            stubbed_session
    ):
        awsclient = TypedAWSClient(stubbed_session)
        patch_operations = awsclient.get_custom_domain_patch_operations(
            security_policy='TLS_1_2',
            certificate_arn='regional_certificate_arn',
            endpoint_type='REGIONAL',
        )
        assert patch_operations == [
            {
                'op': 'replace',
                'path': '/securityPolicy',
                'value': 'TLS_1_2',
            },
            {
                'op': 'replace',
                'path': '/regionalCertificateArn',
                'value': 'regional_certificate_arn',
            }
        ]

    def test_update_domain_name_http_protocol_regional(
        self,
        stubbed_session
    ):
        stubbed_session.stub('apigateway') \
            .update_domain_name(
            domainName='test_domain',
            patchOperations=[
                {
                    'op': 'replace',
                    'path': '/securityPolicy',
                    'value': 'TLS_1_2',
                },
            ]
        ).returns({
            'domainName': 'test_domain',
            'regionalHostedZoneId': 'hosted_zone_id',
            'regionalDomainName': 'regional_domain_name',
            'regionalCertificateArn': 'old_regional_certificate_arn',
            'endpointConfiguration': {
                'types': [
                    'REGIONAL',
                ],
            },
            'domainNameStatus': 'AVAILABLE',
            'securityPolicy': 'TLS_1_2'
        })
        stubbed_session.stub('apigateway') \
            .update_domain_name(
            domainName='test_domain',
            patchOperations=[
                {
                    'op': 'replace',
                    'path': '/regionalCertificateArn',
                    'value': 'regional_certificate_arn',
                }
            ]
        ).returns({
            'domainName': 'test_domain',
            'regionalHostedZoneId': 'hosted_zone_id',
            'regionalCertificateArn': 'regional_certificate_arn',
            'regionalDomainName': 'regional_domain_name',
            'endpointConfiguration': {
                'types': [
                    'REGIONAL',
                ],
            },
            'domainNameStatus': 'AVAILABLE',
            'securityPolicy': 'TLS_1_2'
        })
        arn = 'arn:aws:apigateway:us-west-2::/domainnames/test_domain'
        stubbed_session.stub('apigatewayv2') \
            .get_tags(ResourceArn=arn) \
            .returns({
                'Tags': {}
            })
        stubbed_session.activate_stubs()
        awsclient = TypedAWSClient(stubbed_session)
        assert awsclient.update_domain_name(
            protocol='HTTP',
            domain_name='test_domain',
            endpoint_type='REGIONAL',
            security_policy='TLS_1_2',
            certificate_arn='regional_certificate_arn',
        ) == {
            'domain_name': 'test_domain',
            'alias_domain_name': 'regional_domain_name',
            'security_policy': 'TLS_1_2',
            'hosted_zone_id': 'hosted_zone_id',
            'certificate_arn': 'regional_certificate_arn'
        }
        stubbed_session.verify_stubs()

    def test_update_domain_name_http_protocol(
            self,
            stubbed_session
    ):
        stubbed_session.stub('apigateway') \
            .update_domain_name(
            domainName='test_domain',
            patchOperations=[
                {
                    'op': 'replace',
                    'path': '/securityPolicy',
                    'value': 'TLS_1_0',
                },
            ]
        ).returns({
            'domainName': 'test_domain',
            'distributionHostedZoneId': 'hosted_zone_id',
            'certificateArn': 'old_certificate_arn',
            'distributionDomainName': 'dist_domain_name',
            'endpointConfiguration': {
                'types': [
                    'EDGE',
                ],
            },
            'domainNameStatus': 'AVAILABLE',
            'securityPolicy': 'TLS_1_0'
        })
        stubbed_session.stub('apigateway') \
            .update_domain_name(
            domainName='test_domain',
            patchOperations=[
                {
                    'op': 'replace',
                    'path': '/certificateArn',
                    'value': 'certificate_arn',
                }
            ]
        ).returns({
            'domainName': 'test_domain',
            'distributionHostedZoneId': 'hosted_zone_id',
            'distributionDomainName': 'dist_domain_name',
            'certificateArn': 'certificate_arn',
            'endpointConfiguration': {
                'types': [
                    'EDGE',
                ],
            },
            'domainNameStatus': 'AVAILABLE',
            'securityPolicy': 'TLS_1_0'
        })
        arn = 'arn:aws:apigateway:us-west-2::/domainnames/test_domain'
        stubbed_session.stub('apigatewayv2') \
            .get_tags(ResourceArn=arn) \
            .returns({
                'Tags': {}
            })
        stubbed_session.activate_stubs()
        awsclient = TypedAWSClient(stubbed_session)
        assert awsclient.update_domain_name(
            protocol='HTTP',
            domain_name='test_domain',
            endpoint_type='EDGE',
            security_policy='TLS_1_0',
            certificate_arn='certificate_arn',
        ) == {
            'domain_name': 'test_domain',
            'security_policy': 'TLS_1_0',
            'alias_domain_name': 'dist_domain_name',
            'hosted_zone_id': 'hosted_zone_id',
            'certificate_arn': 'certificate_arn'
        }
        stubbed_session.verify_stubs()

    def test_update_domain_name_max_retries(self, stubbed_session):
        for _ in range(6):
            stubbed_session.stub('apigateway') \
                .update_domain_name(
                domainName='test_domain',
                patchOperations=[
                    {
                        'op': 'replace',
                        'path': '/certificateArn',
                        'value': 'certificate_arn',
                    }
                ]
            ).raises_error(
                error_code='TooManyRequestsException',
                message='Too Many Requests'
            )
        stubbed_session.activate_stubs()
        awsclient = TypedAWSClient(stubbed_session, mock.Mock(spec=time.sleep))
        with pytest.raises(botocore.exceptions.ClientError):
            awsclient.update_domain_name(
                protocol='HTTP',
                domain_name='test_domain',
                endpoint_type='EDGE',
                security_policy='TLS_1_0',
                certificate_arn='certificate_arn',
            )

    def test_update_resource_tags(self, stubbed_session):
        arn = 'arn:aws:apigateway:us-west-2::/domainnames/test_domain'
        stubbed_session.stub('apigatewayv2') \
            .get_tags(
            ResourceArn=arn
        ).returns({
            'Tags': {
                'key': 'value',
                'key1': 'value1'
            }
        })
        stubbed_session.stub('apigatewayv2') \
            .untag_resource(
            ResourceArn=arn,
            TagKeys=['key1']
        ).returns({})
        stubbed_session.stub('apigatewayv2') \
            .tag_resource(
            ResourceArn=arn,
            Tags={
                'key2': 'value2'
            }
        ).returns({})
        stubbed_session.activate_stubs()
        awsclient = TypedAWSClient(stubbed_session)
        tags = {
            'key': 'value',
            'key2': 'value2'
        }
        awsclient._update_resource_tags(arn, tags)
        stubbed_session.verify_stubs()


class TestDeleteDomainName(object):
    def test_delete_domain_name(self, stubbed_session):
        domain_name = 'test_domain'
        stubbed_session.stub('apigatewayv2') \
            .delete_domain_name(DomainName=domain_name).returns({})
        stubbed_session.activate_stubs()

        awsclient = TypedAWSClient(stubbed_session)
        awsclient.delete_domain_name(domain_name=domain_name)
        stubbed_session.verify_stubs()

    def test_delete_domain_name_failed(self, stubbed_session):
        domain_name = 'unknown_domain'
        err_msg = 'The resource specified in the request was not found.'
        stubbed_session.stub('apigatewayv2') \
            .delete_domain_name(DomainName=domain_name) \
            .raises_error(
                error_code='NotFoundException',
                message=err_msg
            )
        stubbed_session.activate_stubs()
        awsclient = TypedAWSClient(stubbed_session)
        with pytest.raises(botocore.exceptions.ClientError):
            awsclient.delete_domain_name(domain_name=domain_name)

    def test_delete_domain_name_max_retries(self, stubbed_session):
        for _ in range(6):
            stubbed_session.stub('apigatewayv2') \
                .delete_domain_name(
                domainName='test_domain',
            ).raises_error(
                error_code='TooManyRequestsException',
                message='Too Many Requests'
            )
        stubbed_session.activate_stubs()
        awsclient = TypedAWSClient(stubbed_session, mock.Mock(spec=time.sleep))
        with pytest.raises(botocore.exceptions.ClientError):
            awsclient.delete_domain_name(domain_name='test_domain')


class TestDeleteApiMapping(object):
    def test_delete_api_mapping(self, stubbed_session):
        domain_name = 'test_domain'
        stubbed_session.stub('apigateway') \
            .delete_base_path_mapping(
                domainName=domain_name,
                basePath='foo'
            ).returns({})
        stubbed_session.activate_stubs()

        awsclient = TypedAWSClient(stubbed_session)
        awsclient.delete_api_mapping(
            domain_name=domain_name,
            path_key='foo'
        )
        stubbed_session.verify_stubs()

    def test_delete_api_mapping_failed(self, stubbed_session):
        domain_name = 'unknown_domain'
        err_msg = 'The resource specified in the request was not found.'
        stubbed_session.stub('apigateway') \
            .delete_base_path_mapping(
                domainName=domain_name,
                basePath='foo'
            ).raises_error(
                error_code='NotFoundException',
                message=err_msg
            )
        stubbed_session.activate_stubs()
        awsclient = TypedAWSClient(stubbed_session)
        with pytest.raises(botocore.exceptions.ClientError):
            awsclient.delete_api_mapping(
                domain_name=domain_name,
                path_key='foo'
            )


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


class TestAddPermissionsForAPIGatewayV2(object):
    def should_call_add_permission(self, lambda_stub,
                                   statement_id=stub.ANY):
        lambda_stub.add_permission(
            Action='lambda:InvokeFunction',
            FunctionName='name',
            StatementId=statement_id,
            Principal='apigateway.amazonaws.com',
            SourceArn='arn:aws:execute-api:us-west-2:123:websocket-api-id/*',
        ).returns({})

    def test_can_add_permission_for_apigateway_v2_needed(self,
                                                         stubbed_session):
        # An empty policy means we need to add permissions.
        lambda_stub = stubbed_session.stub('lambda')
        lambda_stub.get_policy(FunctionName='name').returns({'Policy': '{}'})
        self.should_call_add_permission(lambda_stub)
        stubbed_session.activate_stubs()
        client = TypedAWSClient(stubbed_session)
        client.add_permission_for_apigateway_v2(
            'name', 'us-west-2', '123', 'websocket-api-id')
        stubbed_session.verify_stubs()

    def test_can_add_permission_random_id_optional(self, stubbed_session):
        lambda_stub = stubbed_session.stub('lambda')
        lambda_stub.get_policy(FunctionName='name').returns({'Policy': '{}'})
        self.should_call_add_permission(lambda_stub)
        stubbed_session.activate_stubs()
        client = TypedAWSClient(stubbed_session)
        client.add_permission_for_apigateway_v2(
            'name', 'us-west-2', '123', 'websocket-api-id')
        stubbed_session.verify_stubs()

    def test_can_add_permission_for_apigateway_v2_not_needed(self,
                                                             stubbed_session):
        source_arn = 'arn:aws:execute-api:us-west-2:123:websocket-api-id/*'
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
            'name', 'us-west-2', '123', 'websocket-api-id')
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
        client.add_permission_for_apigateway_v2(
            'name', 'us-west-2', '123', 'websocket-api-id', 'random-id')
        stubbed_session.verify_stubs()


class TestWebsocketAPI(object):
    def test_can_create_websocket_api(self, stubbed_session):
        stubbed_session.stub('apigatewayv2').create_api(
            Name='name',
            ProtocolType='WEBSOCKET',
            RouteSelectionExpression='$request.body.action',
        ).returns({'ApiId': 'id'})
        stubbed_session.activate_stubs()
        client = TypedAWSClient(stubbed_session)
        api_id = client.create_websocket_api('name')
        stubbed_session.verify_stubs()
        assert api_id == 'id'

    def test_can_get_websocket_api(self, stubbed_session):
        stubbed_session.stub('apigatewayv2').get_apis(
        ).returns({
            'Items': [
                {'Name': 'some-other-api',
                 'ApiId': 'foo bar',
                 'RouteSelectionExpression': 'unused',
                 'ProtocolType': 'WEBSOCKET'},
                {'Name': 'target-api',
                 'ApiId': 'id',
                 'RouteSelectionExpression': 'unused',
                 'ProtocolType': 'WEBSOCKET'},
            ],
        })
        stubbed_session.activate_stubs()
        client = TypedAWSClient(stubbed_session)
        api_id = client.get_websocket_api_id('target-api')
        stubbed_session.verify_stubs()
        assert api_id == 'id'

    def test_does_return_none_on_websocket_api_missing(self, stubbed_session):
        stubbed_session.stub('apigatewayv2').get_apis(
        ).returns({
            'Items': [],
        })
        stubbed_session.activate_stubs()
        client = TypedAWSClient(stubbed_session)
        api_id = client.get_websocket_api_id('target-api')
        stubbed_session.verify_stubs()
        assert api_id is None

    def test_can_check_get_websocket_api_exists(self, stubbed_session):
        stubbed_session.stub('apigatewayv2').get_api(
            ApiId='api-id',
        ).returns({})
        stubbed_session.activate_stubs()
        client = TypedAWSClient(stubbed_session)
        exists = client.websocket_api_exists('api-id')
        stubbed_session.verify_stubs()
        assert exists is True

    def test_can_check_get_websocket_api_not_exists(self, stubbed_session):
        stubbed_session.stub('apigatewayv2').get_api(
            ApiId='api-id',
        ).raises_error(
            error_code='NotFoundException',
            message='Does not exists.',
        )
        stubbed_session.activate_stubs()
        client = TypedAWSClient(stubbed_session)
        exists = client.websocket_api_exists('api-id')
        stubbed_session.verify_stubs()
        assert exists is False

    def test_can_delete_websocket_api(self, stubbed_session):
        stubbed_session.stub('apigatewayv2').delete_api(
            ApiId='id',
        ).returns({})
        stubbed_session.activate_stubs()
        client = TypedAWSClient(stubbed_session)
        client.delete_websocket_api('id')
        stubbed_session.verify_stubs()

    def test_rest_api_delete_already_deleted(self, stubbed_session):
        stubbed_session.stub('apigatewayv2')\
                       .delete_api(ApiId='name')\
                       .raises_error(error_code='NotFoundException',
                                     message='Unknown')
        stubbed_session.activate_stubs()

        awsclient = TypedAWSClient(stubbed_session)
        with pytest.raises(ResourceDoesNotExistError):
            assert awsclient.delete_websocket_api('name')

    def test_can_create_integration(self, stubbed_session):
        stubbed_session.stub('apigatewayv2').create_integration(
            ApiId='api-id',
            ConnectionType='INTERNET',
            ContentHandlingStrategy='CONVERT_TO_TEXT',
            Description='connect',
            IntegrationType='AWS_PROXY',
            IntegrationUri='arn:aws:lambda',
        ).returns({'IntegrationId': 'integration-id'})
        stubbed_session.activate_stubs()
        client = TypedAWSClient(stubbed_session)
        integration_id = client.create_websocket_integration(
            api_id='api-id',
            lambda_function='arn:aws:lambda',
            handler_type='connect',
        )
        stubbed_session.verify_stubs()
        assert integration_id == 'integration-id'

    def test_can_create_route(self, stubbed_session):
        stubbed_session.stub('apigatewayv2').create_route(
            ApiId='api-id',
            RouteKey='route-key',
            RouteResponseSelectionExpression='$default',
            Target='integrations/integration-id',
        ).returns({})
        stubbed_session.activate_stubs()
        client = TypedAWSClient(stubbed_session)
        client.create_websocket_route(
            api_id='api-id',
            route_key='route-key',
            integration_id='integration-id',
        )
        stubbed_session.verify_stubs()

    def test_can_delete_all_websocket_routes(self, stubbed_session):
        stubbed_session.stub('apigatewayv2').delete_route(
            ApiId='api-id',
            RouteId='route-id',
        ).returns({})
        stubbed_session.stub('apigatewayv2').delete_route(
            ApiId='api-id',
            RouteId='old-route-id',
        ).returns({})
        stubbed_session.activate_stubs()
        client = TypedAWSClient(stubbed_session)
        client.delete_websocket_routes(
            api_id='api-id',
            routes=['route-id', 'old-route-id'],
        )
        stubbed_session.verify_stubs()

    def test_can_delete_all_websocket_integrations(self, stubbed_session):
        stubbed_session.stub('apigatewayv2').delete_integration(
            ApiId='api-id',
            IntegrationId='integration-id',
        ).returns({})
        stubbed_session.stub('apigatewayv2').delete_integration(
            ApiId='api-id',
            IntegrationId='old-integration-id',
        ).returns({})
        stubbed_session.activate_stubs()
        client = TypedAWSClient(stubbed_session)
        client.delete_websocket_integrations(
            api_id='api-id',
            integrations=['integration-id', 'old-integration-id'],
        )
        stubbed_session.verify_stubs()

    def test_can_deploy_websocket_api(self, stubbed_session):
        stubbed_session.stub('apigatewayv2').create_deployment(
            ApiId='api-id',
        ).returns({'DeploymentId': 'deployment-id'})
        stubbed_session.activate_stubs()
        client = TypedAWSClient(stubbed_session)
        deployment_id = client.deploy_websocket_api(
            api_id='api-id',
        )
        stubbed_session.verify_stubs()
        assert deployment_id == 'deployment-id'

    def test_can_get_routes(self, stubbed_session):
        stubbed_session.stub('apigatewayv2').get_routes(
            ApiId='api-id',
        ).returns(
            {
                'Items': [
                    {'RouteKey': 'route-key-foo',
                     'RouteId': 'route-id-foo'},
                    {'RouteKey': 'route-key-bar',
                     'RouteId': 'route-id-bar'},
                ],
            }
        )
        stubbed_session.activate_stubs()
        client = TypedAWSClient(stubbed_session)
        routes = client.get_websocket_routes(
            api_id='api-id',
        )
        stubbed_session.verify_stubs()
        assert routes == ['route-id-foo', 'route-id-bar']

    def test_can_get_integrations(self, stubbed_session):
        stubbed_session.stub('apigatewayv2').get_integrations(
            ApiId='api-id',
        ).returns(
            {
                'Items': [
                    {
                        'Description': 'connect',
                        'IntegrationId': 'connect-integration-id'
                    },
                    {
                        'Description': 'message',
                        'IntegrationId': 'message-integration-id'
                    },
                    {
                        'Description': 'disconnect',
                        'IntegrationId': 'disconnect-integration-id'
                    },
                ]
            }
        )
        stubbed_session.activate_stubs()
        client = TypedAWSClient(stubbed_session)
        integration_ids = client.get_websocket_integrations(
            api_id='api-id',
        )
        stubbed_session.verify_stubs()
        assert integration_ids == [
            'connect-integration-id',
            'message-integration-id',
            'disconnect-integration-id',
        ]

    def test_can_create_stage(self, stubbed_session):
        stubbed_session.stub('apigatewayv2').create_stage(
            ApiId='api-id',
            StageName='stage-name',
            DeploymentId='deployment-id',
        ).returns({})
        stubbed_session.activate_stubs()
        client = TypedAWSClient(stubbed_session)
        client.create_stage(
            api_id='api-id',
            stage_name='stage-name',
            deployment_id='deployment-id',
        )
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
        parameters={'endpointConfigurationTypes': 'EDGE'},
        body=json.dumps(swagger_doc, indent=2)).returns(
            {'id': 'rest_api_id'})

    stubbed_session.activate_stubs()
    awsclient = TypedAWSClient(stubbed_session)
    rest_api_id = awsclient.import_rest_api(swagger_doc, 'EDGE')
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


def test_update_rest_api(stubbed_session):
    apig = stubbed_session.stub('apigateway')
    patch_operations = [{'op': 'replace',
                         'path': '/minimumCompressionSize',
                         'value': '2'}]
    apig.update_rest_api(
        restApiId='rest_api_id',
        patchOperations=patch_operations).returns({})

    stubbed_session.activate_stubs()
    awsclient = TypedAWSClient(stubbed_session)

    awsclient.update_rest_api('rest_api_id',
                              patch_operations)
    stubbed_session.verify_stubs()


def test_can_get_or_create_rule_arn_with_pattern(stubbed_session):
    events = stubbed_session.stub('events')
    events.put_rule(
        Name='rule-name',
        EventPattern='{"source": ["aws.ec2"]}').returns({
            'RuleArn': 'rule-arn',
        })

    stubbed_session.activate_stubs()
    awsclient = TypedAWSClient(stubbed_session)
    result = awsclient.get_or_create_rule_arn(
        rule_name='rule-name',
        event_pattern='{"source": ["aws.ec2"]}')
    stubbed_session.verify_stubs()
    assert result == 'rule-arn'


def test_can_get_or_create_rule_arn(stubbed_session):
    events = stubbed_session.stub('events')
    events.put_rule(
        Name='rule-name',
        Description='rule-description',
        ScheduleExpression='rate(1 hour)').returns({
            'RuleArn': 'rule-arn',
        })

    stubbed_session.activate_stubs()
    awsclient = TypedAWSClient(stubbed_session)
    result = awsclient.get_or_create_rule_arn(
        'rule-name',
        schedule_expression='rate(1 hour)',
        rule_description='rule-description'
    )
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
        SourceArn='arn:aws:events:us-east-1:123456789012:rule/MyScheduledRule'
    ).returns({})

    stubbed_session.activate_stubs()

    awsclient = TypedAWSClient(stubbed_session)
    awsclient.add_permission_for_cloudwatch_event(
        'arn:aws:events:us-east-1:123456789012:rule/MyScheduledRule',
        'function-arn')

    stubbed_session.verify_stubs()


def test_skip_if_permission_already_granted(stubbed_session):
    lambda_client = stubbed_session.stub('lambda')
    policy = {
        'Id': 'default',
        'Statement': [
            {'Action': 'lambda:InvokeFunction',
                'Condition': {
                    'ArnLike': {
                        'AWS:SourceArn': 'arn:aws:events:us-east-1'
                                         ':123456789012:rule/MyScheduledRule',
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
    awsclient.add_permission_for_cloudwatch_event(
        'arn:aws:events:us-east-1:123456789012:rule/MyScheduledRule',
        'function-arn')
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
        SourceArn='arn:aws:sns:us-west-2:12345:my-demo-topic',
    ).returns({})

    stubbed_session.activate_stubs()
    awsclient = TypedAWSClient(stubbed_session)
    awsclient.add_permission_for_sns_topic(
        'arn:aws:sns:us-west-2:12345:my-demo-topic', 'function-arn')
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
    topic_arn = 'arn:aws:sns:us-west-2:12345:my-demo-topic'
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


def test_can_create_kinesis_event_source(stubbed_session):
    kinesis_arn = 'arn:aws:kinesis:us-west-2:...:stream/MyStream'
    function_name = 'myfunction'
    batch_size = 100
    starting_position = 'TRIM_HORIZON'
    lambda_stub = stubbed_session.stub('lambda')
    lambda_stub.create_event_source_mapping(
        EventSourceArn=kinesis_arn,
        FunctionName=function_name,
        BatchSize=batch_size,
        StartingPosition=starting_position,
    ).returns({'UUID': 'my-uuid'})

    stubbed_session.activate_stubs()
    client = TypedAWSClient(stubbed_session)
    result = client.create_lambda_event_source(
        kinesis_arn, function_name, batch_size, starting_position
    )
    assert result == 'my-uuid'
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
    result = client.create_lambda_event_source(
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
    result = client.create_lambda_event_source(
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
    client.remove_lambda_event_source(
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
    client.remove_lambda_event_source(
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
        client.remove_lambda_event_source('my-uuid')
    stubbed_session.verify_stubs()


def test_can_retry_update_event_source(stubbed_session):
    lambda_stub = stubbed_session.stub('lambda')
    lambda_stub.update_event_source_mapping(
        UUID='my-uuid',
        BatchSize=5,
    ).returns({})

    stubbed_session.activate_stubs()
    client = TypedAWSClient(stubbed_session)
    client.update_lambda_event_source(
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


def test_verify_event_source_arn_current(stubbed_session):
    client = stubbed_session.stub('lambda')
    uuid = 'uuid-12345'
    client.get_event_source_mapping(
        UUID=uuid,
    ).returns({
        'UUID': uuid,
        'BatchSize': 10,
        'EventSourceArn': 'arn:aws:dynamodb:...:table/MyTable/stream/2020',
        'FunctionArn': 'arn:aws:lambda:function-arn',
        'LastModified': '2018-07-02T18:19:03.958000-07:00',
        'State': 'Enabled',
        'StateTransitionReason': 'USER_INITIATED'
    })
    stubbed_session.activate_stubs()

    awsclient = TypedAWSClient(stubbed_session)
    assert awsclient.verify_event_source_arn_current(
        uuid,
        event_source_arn='arn:aws:dynamodb:...:table/MyTable/stream/2020',
        function_arn='arn:aws:lambda:function-arn',
    )
    stubbed_session.verify_stubs()


def test_event_source_uuid_does_not_exist(stubbed_session):
    client = stubbed_session.stub('lambda')
    uuid = 'uuid-12345'
    client.get_event_source_mapping(
        UUID=uuid,
    ).raises_error(error_code='ResourceNotFoundException',
                   message='Does not exists.')

    stubbed_session.activate_stubs()

    awsclient = TypedAWSClient(stubbed_session)
    assert not awsclient.verify_event_source_arn_current(
        uuid, event_source_arn='arn:aws:dynamodb:...',
        function_arn='arn:aws:lambda:...',
    )
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


def test_can_update_lambda_event_source(stubbed_session):
    lambda_stub = stubbed_session.stub('lambda')
    lambda_stub.update_event_source_mapping(
        UUID='my-uuid',
        BatchSize=5,
    ).returns({})

    stubbed_session.activate_stubs()
    client = TypedAWSClient(stubbed_session)
    client.update_lambda_event_source(
        event_uuid='my-uuid', batch_size=5
    )
    stubbed_session.verify_stubs()
