# Copyright 2015 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"). You
# may not use this file except in compliance with the License. A copy of
# the License is located at
#
# http://aws.amazon.com/apache2.0/
#
# or in the "license" file accompanying this file. This file is
# distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF
# ANY KIND, either express or implied. See the License for the specific
# language governing permissions and limitations under the License.

"""
This file was 'vendored' from botocore core
botocore/tests/unit/test_regions.py from commit
0c55d6c3f900fc856e818f06b31c22c6dbc56788.

The vendoring/duplication was due to the concern of utilizing a unexposed class
internal to the botocore library for functionality necessary to implicitly
support partitions within the chalice microframework. More specifically the
determination of the dns suffix for service endpoints based on service and
region.
"""

import pytest
from botocore.exceptions import NoRegionError

from chalice.vendored.botocore import regions


@pytest.fixture
def endpoints_template():
    return {
        'partitions': [
            {
                'partition': 'aws',
                'dnsSuffix': 'amazonaws.com',
                'regionRegex': r'^(us|eu)\-\w+$',
                'defaults': {
                    'hostname': '{service}.{region}.{dnsSuffix}'
                },
                'regions': {
                    'us-foo': {'regionName': 'a'},
                    'us-bar': {'regionName': 'b'},
                    'eu-baz': {'regionName': 'd'}
                },
                'services': {
                    'ec2': {
                        'endpoints': {
                            'us-foo': {},
                            'us-bar': {},
                            'eu-baz': {},
                            'd': {}
                        }
                    },
                    's3': {
                        'defaults': {
                            'sslCommonName': '{service}.{region}.{dnsSuffix}'
                        },
                        'endpoints': {
                            'us-foo': {
                                'sslCommonName':
                                    '{region}.{service}.{dnsSuffix}'
                            },
                            'us-bar': {},
                            'eu-baz': {'hostname': 'foo'}
                        }
                    },
                    'not-regionalized': {
                        'isRegionalized': False,
                        'partitionEndpoint': 'aws',
                        'endpoints': {
                            'aws': {'hostname': 'not-regionalized'},
                            'us-foo': {},
                            'eu-baz': {}
                        }
                    },
                    'non-partition': {
                        'partitionEndpoint': 'aws',
                        'endpoints': {
                            'aws': {'hostname': 'host'},
                            'us-foo': {}
                        }
                    },
                    'merge': {
                        'defaults': {
                            'signatureVersions': ['v2'],
                            'protocols': ['http']
                        },
                        'endpoints': {
                            'us-foo': {'signatureVersions': ['v4']},
                            'us-bar': {'protocols': ['https']}
                        }
                    }
                }
            },
            {
                'partition': 'foo',
                'dnsSuffix': 'foo.com',
                'regionRegex': r'^(foo)\-\w+$',
                'defaults': {
                    'hostname': '{service}.{region}.{dnsSuffix}',
                    'protocols': ['http'],
                    'foo': 'bar'
                },
                'regions': {
                    'foo-1': {'regionName': '1'},
                    'foo-2': {'regionName': '2'},
                    'foo-3': {'regionName': '3'}
                },
                'services': {
                    'ec2': {
                        'endpoints': {
                            'foo-1': {
                                'foo': 'baz'
                            },
                            'foo-2': {},
                            'foo-3': {}
                        }
                    }
                }
            }
        ]
    }


def test_ensures_region_is_not_none(endpoints_template):
    with pytest.raises(NoRegionError):
        resolver = regions.EndpointResolver(endpoints_template)
        resolver.construct_endpoint('foo', None)


def test_ensures_required_keys_present(endpoints_template):
    with pytest.raises(ValueError):
        regions.EndpointResolver({})


def test_returns_empty_list_when_listing_for_different_partition(
        endpoints_template):
    resolver = regions.EndpointResolver(endpoints_template)
    assert resolver.get_available_endpoints('ec2', 'bar') == []


def test_returns_empty_list_when_no_service_found(endpoints_template):
    resolver = regions.EndpointResolver(endpoints_template)
    assert resolver.get_available_endpoints('what?') == []


def test_gets_endpoint_names(endpoints_template):
    resolver = regions.EndpointResolver(endpoints_template)
    result = resolver.get_available_endpoints('ec2', allow_non_regional=True)
    assert sorted(result) == ['d', 'eu-baz', 'us-bar', 'us-foo']


def test_gets_endpoint_names_for_partition(endpoints_template):
    resolver = regions.EndpointResolver(endpoints_template)
    result = resolver.get_available_endpoints(
        'ec2', allow_non_regional=True, partition_name='foo')
    assert sorted(result) == ['foo-1', 'foo-2', 'foo-3']


def test_list_regional_endpoints_only(endpoints_template):
    resolver = regions.EndpointResolver(endpoints_template)
    result = resolver.get_available_endpoints(
        'ec2', allow_non_regional=False)
    assert sorted(result) == ['eu-baz', 'us-bar', 'us-foo']


def test_returns_none_when_no_match(endpoints_template):
    resolver = regions.EndpointResolver(endpoints_template)
    assert resolver.construct_endpoint('foo', 'baz') is None


def test_constructs_regionalized_endpoints_for_exact_matches(
        endpoints_template):
    resolver = regions.EndpointResolver(endpoints_template)
    result = resolver.construct_endpoint('not-regionalized', 'eu-baz')
    assert result['hostname'] == 'not-regionalized.eu-baz.amazonaws.com'
    assert result['partition'] == 'aws'
    assert result['endpointName'] == 'eu-baz'


def test_constructs_partition_endpoints_for_real_partition_region(
        endpoints_template):
    resolver = regions.EndpointResolver(endpoints_template)
    result = resolver.construct_endpoint('not-regionalized', 'us-bar')
    assert result['hostname'] == 'not-regionalized'
    assert result['partition'] == 'aws'
    assert result['endpointName'] == 'aws'


def test_constructs_partition_endpoints_for_regex_match(endpoints_template):
    resolver = regions.EndpointResolver(endpoints_template)
    result = resolver.construct_endpoint('not-regionalized', 'us-abc')
    assert result['hostname'] == 'not-regionalized'


def test_constructs_endpoints_for_regionalized_regex_match(endpoints_template):
    resolver = regions.EndpointResolver(endpoints_template)
    result = resolver.construct_endpoint('s3', 'us-abc')
    assert result['hostname'] == 's3.us-abc.amazonaws.com'


def test_constructs_endpoints_for_unknown_service_but_known_region(
        endpoints_template):
    resolver = regions.EndpointResolver(endpoints_template)
    result = resolver.construct_endpoint('unknown', 'us-foo')
    assert result['hostname'] == 'unknown.us-foo.amazonaws.com'


def test_merges_service_keys(endpoints_template):
    resolver = regions.EndpointResolver(endpoints_template)
    us_foo = resolver.construct_endpoint('merge', 'us-foo')
    us_bar = resolver.construct_endpoint('merge', 'us-bar')
    assert us_foo['protocols'] == ['http']
    assert us_foo['signatureVersions'] == ['v4']
    assert us_bar['protocols'] == ['https']
    assert us_bar['signatureVersions'] == ['v2']


def test_merges_partition_default_keys_with_no_overwrite(endpoints_template):
    resolver = regions.EndpointResolver(endpoints_template)
    resolved = resolver.construct_endpoint('ec2', 'foo-1')
    assert resolved['foo'] == 'baz'
    assert resolved['protocols'] == ['http']


def test_merges_partition_default_keys_with_overwrite(endpoints_template):
    resolver = regions.EndpointResolver(endpoints_template)
    resolved = resolver.construct_endpoint('ec2', 'foo-2')
    assert resolved['foo'] == 'bar'
    assert resolved['protocols'] == ['http']


def test_gives_hostname_and_common_name_unaltered(endpoints_template):
    resolver = regions.EndpointResolver(endpoints_template)
    result = resolver.construct_endpoint('s3', 'eu-baz')
    assert result['sslCommonName'] == 's3.eu-baz.amazonaws.com'
    assert result['hostname'] == 'foo'


def tests_uses_partition_endpoint_when_no_region_provided(endpoints_template):
    resolver = regions.EndpointResolver(endpoints_template)
    result = resolver.construct_endpoint('not-regionalized')
    assert result['hostname'] == 'not-regionalized'
    assert result['endpointName'] == 'aws'


def test_returns_dns_suffix_if_available(endpoints_template):
    resolver = regions.EndpointResolver(endpoints_template)
    result = resolver.construct_endpoint('not-regionalized')
    assert result['dnsSuffix'] == 'amazonaws.com'
