from chalice.config import Config
from chalice.policy import PolicyBuilder, AppPolicyGenerator
from chalice.policy import diff_policies
from chalice.utils import OSUtils  # noqa


class OsUtilsMock(OSUtils):
    def file_exists(self, *args, **kwargs):
        return True

    def get_file_contents(selfs, *args, **kwargs):
        return ''


def iam_policy(client_calls):
    builder = PolicyBuilder()
    policy = builder.build_policy_from_api_calls(client_calls)
    return policy


def test_app_policy_generator_vpc_policy():
    config = Config.create(
        subnet_ids=['sn1', 'sn2'],
        security_group_ids=['sg1', 'sg2'],
        project_dir='.'
    )
    generator = AppPolicyGenerator(OsUtilsMock())
    policy = generator.generate_policy(config)
    assert policy == {'Statement': [
        {'Action': ['logs:CreateLogGroup',
                    'logs:CreateLogStream',
                    'logs:PutLogEvents'],
         'Effect': 'Allow',
         'Resource': 'arn:*:logs:*:*:*'},
        {'Action': ['ec2:CreateNetworkInterface',
                    'ec2:DescribeNetworkInterfaces',
                    'ec2:DetachNetworkInterface',
                    'ec2:DeleteNetworkInterface'],
         'Effect': 'Allow',
         'Resource': '*'},
    ], 'Version': '2012-10-17'}


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
    expected_policy = [{
        'Effect': 'Allow',
        'Action': [
            'dynamodb:DescribeTable',
            'dynamodb:ListTables',
        ],
        'Resource': [
            '*',
        ]
    }]
    assert_policy_is(
        iam_policy({'dynamodb': set(['list_tables', 'describe_table'])}),
        expected_policy
    )


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


def test_can_handle_high_level_abstractions():
    policy = iam_policy({
        's3': set(['download_file', 'upload_file', 'copy'])
    })
    assert_policy_is(policy, [{
        'Effect': 'Allow',
        'Action': [
            's3:AbortMultipartUpload',
            's3:GetObject',
            's3:PutObject',
        ],
        'Resource': [
            '*',
        ]
    }])


def test_noop_for_unknown_methods():
    assert_policy_is(iam_policy({'s3': set(['unknown_method'])}), [])
