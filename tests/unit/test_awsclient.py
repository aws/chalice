from collections import OrderedDict

import pytest

from chalice.awsclient import TypedAWSClient


@pytest.mark.parametrize('service,region,endpoint', [
    ('sns', 'us-east-1',
     OrderedDict([('partition', 'aws'),
                  ('endpointName', 'us-east-1'),
                  ('protocols', ['http', 'https']),
                  ('hostname', 'sns.us-east-1.amazonaws.com'),
                  ('signatureVersions', ['v4']),
                  ('dnsSuffix', 'amazonaws.com')])),
    ('sqs', 'cn-north-1',
     OrderedDict([('partition', 'aws-cn'),
                  ('endpointName', 'cn-north-1'),
                  ('protocols', ['http', 'https']),
                  ('sslCommonName', 'cn-north-1.queue.amazonaws.com.cn'),
                  ('hostname', 'sqs.cn-north-1.amazonaws.com.cn'),
                  ('signatureVersions', ['v4']),
                  ('dnsSuffix', 'amazonaws.com.cn')])),
    ('dynamodb', 'mars-west-1', None)
])
def test_resolve_endpoint(stubbed_session, service, region, endpoint):
    awsclient = TypedAWSClient(stubbed_session)
    assert endpoint == awsclient.resolve_endpoint(service, region)


@pytest.mark.parametrize('arn,endpoint', [
    ('arn:aws:sns:us-east-1:123456:MyTopic',
     OrderedDict([('partition', 'aws'),
                  ('endpointName', 'us-east-1'),
                  ('protocols', ['http', 'https']),
                  ('hostname', 'sns.us-east-1.amazonaws.com'),
                  ('signatureVersions', ['v4']),
                  ('dnsSuffix', 'amazonaws.com')])),
    ('arn:aws-cn:sqs:cn-north-1:444455556666:queue1',
     OrderedDict([('partition', 'aws-cn'),
                  ('endpointName', 'cn-north-1'),
                  ('protocols', ['http', 'https']),
                  ('sslCommonName', 'cn-north-1.queue.amazonaws.com.cn'),
                  ('hostname', 'sqs.cn-north-1.amazonaws.com.cn'),
                  ('signatureVersions', ['v4']),
                  ('dnsSuffix', 'amazonaws.com.cn')])),
    ('arn:aws:dynamodb:mars-west-1:123456:table/MyTable', None)
])
def test_endpoint_from_arn(stubbed_session, arn, endpoint):
    awsclient = TypedAWSClient(stubbed_session)
    assert endpoint == awsclient.endpoint_from_arn(arn)


@pytest.mark.parametrize('service,region,dns_suffix', [
    ('sns', 'us-east-1', 'amazonaws.com'),
    ('sns', 'cn-north-1', 'amazonaws.com.cn'),
    ('dynamodb', 'mars-west-1', 'amazonaws.com')
])
def test_endpoint_dns_suffix(stubbed_session, service, region, dns_suffix):
    awsclient = TypedAWSClient(stubbed_session)
    assert dns_suffix == awsclient.endpoint_dns_suffix(service, region)


@pytest.mark.parametrize('arn,dns_suffix', [
    ('arn:aws:sns:us-east-1:123456:MyTopic', 'amazonaws.com'),
    ('arn:aws-cn:sqs:cn-north-1:444455556666:queue1', 'amazonaws.com.cn'),
    ('arn:aws:dynamodb:mars-west-1:123456:table/MyTable', 'amazonaws.com')
])
def test_endpoint_dns_suffix_from_arn(stubbed_session, arn, dns_suffix):
    awsclient = TypedAWSClient(stubbed_session)
    assert dns_suffix == awsclient.endpoint_dns_suffix_from_arn(arn)


class TestServicePrincipal(object):

    @pytest.fixture
    def region(self):
        return 'bermuda-triangle-42'

    @pytest.fixture
    def url_suffix(self):
        return '.nowhere.null'

    @pytest.fixture
    def non_iso_suffixes(self):
        return ['', '.amazonaws.com', '.amazonaws.com.cn']

    @pytest.fixture
    def awsclient(self, stubbed_session):
        return TypedAWSClient(stubbed_session)

    def test_unmatched_service(self, awsclient):
        assert awsclient.service_principal('taco.magic.food.com',
                                           'us-east-1',
                                           'amazonaws.com') == \
               'taco.magic.food.com'

    def test_defaults(self, awsclient):
        assert awsclient.service_principal('lambda') == 'lambda.amazonaws.com'

    def test_states(self, awsclient, region, url_suffix, non_iso_suffixes):
        services = ['states']
        for suffix in non_iso_suffixes:
            for service in services:
                assert awsclient.service_principal('{}{}'.format(service,
                                                                 suffix),
                                                   region, url_suffix) == \
                       '{}.{}.amazonaws.com'.format(service, region)

    def test_codedeploy_and_logs(self, awsclient, region, url_suffix,
                                 non_iso_suffixes):
        services = ['codedeploy', 'logs']
        for suffix in non_iso_suffixes:
            for service in services:
                assert awsclient.service_principal('{}{}'.format(service,
                                                                 suffix),
                                                   region, url_suffix) == \
                       '{}.{}.{}'.format(service, region, url_suffix)

    def test_ec2(self, awsclient, region, url_suffix, non_iso_suffixes):
        services = ['ec2']
        for suffix in non_iso_suffixes:
            for service in services:
                assert awsclient.service_principal('{}{}'.format(service,
                                                                 suffix),
                                                   region, url_suffix) == \
                       '{}.{}'.format(service, url_suffix)

    def test_others(self, awsclient, region, url_suffix, non_iso_suffixes):
        services = ['autoscaling', 'lambda', 'events', 'sns', 'sqs',
                    'foo-service']
        for suffix in non_iso_suffixes:
            for service in services:
                assert awsclient.service_principal('{}{}'.format(service,
                                                                 suffix),
                                                   region, url_suffix) == \
                       '{}.amazonaws.com'.format(service)

    def test_local_suffix(self, awsclient, region, url_suffix):
        assert awsclient.service_principal('foo-service.local',
                                           region,
                                           url_suffix) == 'foo-service.local'

    def test_states_iso(self, awsclient):
        assert awsclient.service_principal('states.amazonaws.com',
                                           'us-iso-east-1',
                                           'c2s.ic.gov') == \
               'states.amazonaws.com'

    def test_states_isob(self, awsclient):
        assert awsclient.service_principal('states.amazonaws.com',
                                           'us-isob-east-1',
                                           'sc2s.sgov.gov') == \
               'states.amazonaws.com'

    def test_iso_exceptions(self, awsclient):
        services = ['cloudhsm', 'config', 'workspaces']
        for service in services:
            assert awsclient.service_principal(
                '{}.amazonaws.com'.format(service),
                'us-iso-east-1',
                'c2s.ic.gov') == '{}.c2s.ic.gov'.format(service)
