from chalice.policy import PolicyBuilder
from chalice.policy import diff_policies


def iam_policy(client_calls):
    builder = PolicyBuilder()
    policy = builder.build_policy_from_api_calls(client_calls)
    return policy


def assert_policy_is(actual, expected):
    # Prune out the autogen's stuff we don't
    # care about.
    statements = actual['Statement']
    for s in statements:
        del s['Sid']
    assert expected == statements


def test_single_call():
    assert_policy_is(iam_policy({'dynamodb': set(['list_tables'])}), [{
        'Effect': 'Allow',
        'Action': [
            'dynamodb:ListTables'
        ],
        'Resource': [
            '*',
        ]
    }])


def test_multiple_calls_in_same_service():
    assert_policy_is(iam_policy({'dynamodb': set(['list_tables',
                                                  'describe_table'])}), [{
        'Effect': 'Allow',
        'Action': [
            'dynamodb:DescribeTable',
            'dynamodb:ListTables',
        ],
        'Resource': [
            '*',
        ]
    }])


def test_multiple_services_used():
    client_calls = {
        'dynamodb': set(['list_tables']),
        'cloudformation': set(['create_stack']),
    }
    assert_policy_is(iam_policy(client_calls), [
        {
            'Effect': 'Allow',
            'Action': [
                'cloudformation:CreateStack',
            ],
            'Resource': [
                '*',
            ]
        },
        {
            'Effect': 'Allow',
            'Action': [
                'dynamodb:ListTables',
            ],
            'Resource': [
                '*',
            ]
        },
    ])


def test_not_one_to_one_mapping():
    client_calls = {
        's3': set(['list_buckets', 'list_objects',
                   'create_multipart_upload']),
    }
    assert_policy_is(iam_policy(client_calls), [
        {
            'Effect': 'Allow',
            'Action': [
                's3:ListAllMyBuckets',
                's3:ListBucket',
                's3:PutObject',
            ],
            'Resource': [
                '*',
            ]
        },
    ])


def test_can_diff_policy_removed():
    first = iam_policy({'s3': {'list_buckets', 'list_objects'}})
    second = iam_policy({'s3': {'list_buckets'}})
    assert diff_policies(first, second) == {'removed': {'s3:ListBucket'}}


def test_can_diff_policy_added():
    first = iam_policy({'s3': {'list_buckets'}})
    second = iam_policy({'s3': {'list_buckets', 'list_objects'}})
    assert diff_policies(first, second) == {'added': {'s3:ListBucket'}}


def test_can_diff_multiple_services():
    first = iam_policy({
        's3': {'list_buckets'},
        'dynamodb': {'create_table'},
        'cloudformation': {'create_stack', 'delete_stack'},
    })
    second = iam_policy({
        's3': {'list_buckets', 'list_objects'},
        'cloudformation': {'create_stack', 'update_stack'},
    })
    assert diff_policies(first, second) == {
        'added': {'s3:ListBucket', 'cloudformation:UpdateStack'},
        'removed': {'cloudformation:DeleteStack', 'dynamodb:CreateTable'},
    }


def test_no_changes():
    first = iam_policy({'s3': {'list_buckets', 'list_objects'}})
    second = iam_policy({'s3': {'list_buckets', 'list_objects'}})
    assert diff_policies(first, second) == {}
