import mock

import attr
import pytest

from chalice.awsclient import TypedAWSClient, ResourceDoesNotExistError
from chalice.deploy import models
from chalice.config import DeployedResources
from chalice.utils import OSUtils
from chalice.deploy.planner import PlanStage, Variable, RemoteState
from chalice.deploy.planner import StringFormat
from chalice.deploy.planner import ResourceSweeper


def create_function_resource(name, function_name=None,
                             environment_variables=None,
                             runtime='python2.7', handler='app.app',
                             tags=None, timeout=60,
                             memory_size=128, deployment_package=None,
                             role=None, layers=None):
    if function_name is None:
        function_name = 'appname-dev-%s' % name
    if environment_variables is None:
        environment_variables = {}
    if tags is None:
        tags = {}
    if deployment_package is None:
        deployment_package = models.DeploymentPackage(filename='foo')
    if role is None:
        role = models.PreCreatedIAMRole(role_arn='role:arn')
    return models.LambdaFunction(
        resource_name=name,
        function_name=function_name,
        environment_variables=environment_variables,
        runtime=runtime,
        handler=handler,
        tags=tags,
        timeout=timeout,
        memory_size=memory_size,
        deployment_package=deployment_package,
        role=role,
        security_group_ids=[],
        subnet_ids=[],
        layers=layers,
        reserved_concurrency=None,
    )


@pytest.fixture
def no_deployed_values():
    return DeployedResources({'resources': [], 'schema_version': '2.0'})


class FakeConfig(object):
    def __init__(self, deployed_values):
        self._deployed_values = deployed_values
        self.chalice_stage = 'dev'

    def deployed_resources(self, chalice_stage_name):
        return DeployedResources(self._deployed_values)


class InMemoryRemoteState(object):
    def __init__(self, known_resources=None):
        if known_resources is None:
            known_resources = {}
        self.known_resources = known_resources
        self.deployed_values = {}

    def resource_exists(self, resource):
        return (
            (resource.resource_type, resource.resource_name)
            in self.known_resources)

    def get_remote_model(self, resource):
        key = (resource.resource_type, resource.resource_name)
        return self.known_resources.get(key)

    def declare_resource_exists(self, resource, **deployed_values):
        key = (resource.resource_type, resource.resource_name)
        self.known_resources[key] = resource
        if deployed_values:
            deployed_values['name'] = resource.resource_name
            self.deployed_values[resource.resource_name] = deployed_values

    def declare_no_resources_exists(self):
        self.known_resources = {}

    def resource_deployed_values(self, resource):
        return self.deployed_values[resource.resource_name]


class BasePlannerTests(object):
    def setup_method(self):
        self.osutils = mock.Mock(spec=OSUtils)
        self.remote_state = InMemoryRemoteState()
        self.last_plan = None

    def assert_apicall_equals(self, expected, actual_api_call):
        # models.APICall has its own __eq__ method from attrs,
        # but in practice the assertion errors are unreadable and
        # it's not always clear which part of the API call object is
        # wrong.  To get better error messages each field is individually
        # compared.
        assert isinstance(expected, models.APICall)
        assert isinstance(actual_api_call, models.APICall)
        assert expected.method_name == actual_api_call.method_name
        assert expected.params == actual_api_call.params

    def determine_plan(self, resource):
        planner = PlanStage(self.remote_state, self.osutils)
        self.last_plan = planner.execute([resource])
        return self.last_plan.instructions


class TestPlanManagedRole(BasePlannerTests):
    def test_can_plan_for_iam_role_creation(self):
        self.remote_state.declare_no_resources_exists()
        resource = models.ManagedIAMRole(
            resource_name='default-role',
            role_name='myrole',
            trust_policy={'trust': 'policy'},
            policy=models.AutoGenIAMPolicy(document={'iam': 'policy'}),
        )
        plan = self.determine_plan(resource)
        expected = models.APICall(
            method_name='create_role',
            params={'name': 'myrole',
                    'trust_policy': {'trust': 'policy'},
                    'policy': {'iam': 'policy'}},
        )
        self.assert_apicall_equals(plan[0], expected)
        assert list(self.last_plan.messages.values()) == [
            'Creating IAM role: myrole\n'
        ]

    def test_can_create_plan_for_filebased_role(self):
        self.remote_state.declare_no_resources_exists()
        resource = models.ManagedIAMRole(
            resource_name='default-role',
            role_name='myrole',
            trust_policy={'trust': 'policy'},
            policy=models.FileBasedIAMPolicy(
                filename='foo.json', document={'iam': 'policy'}),
        )
        plan = self.determine_plan(resource)
        expected = models.APICall(
            method_name='create_role',
            params={'name': 'myrole',
                    'trust_policy': {'trust': 'policy'},
                    'policy': {'iam': 'policy'}},
        )
        self.assert_apicall_equals(plan[0], expected)
        assert list(self.last_plan.messages.values()) == [
            'Creating IAM role: myrole\n'
        ]

    def test_can_update_managed_role(self):
        role = models.ManagedIAMRole(
            resource_name='resource_name',
            role_name='myrole',
            trust_policy={},
            policy=models.AutoGenIAMPolicy(document={'role': 'policy'}),
        )
        self.remote_state.declare_resource_exists(
            role, role_arn='myrole:arn')
        plan = self.determine_plan(role)
        assert plan[0] == models.StoreValue(
            name='myrole_role_arn', value='myrole:arn')
        self.assert_apicall_equals(
            plan[1],
            models.APICall(
                method_name='put_role_policy',
                params={'role_name': 'myrole',
                        'policy_name': 'myrole',
                        'policy_document': {'role': 'policy'}},
            )
        )
        assert plan[-2].variable_name == 'myrole_role_arn'
        assert plan[-1].value == 'myrole'
        assert list(self.last_plan.messages.values()) == [
            'Updating policy for IAM role: myrole\n'
        ]

    def test_can_update_file_based_policy(self):
        role = models.ManagedIAMRole(
            resource_name='resource_name',
            role_name='myrole',
            trust_policy={},
            policy=models.FileBasedIAMPolicy(
                filename='foo.json',
                document={'iam': 'policy'}),
        )
        self.remote_state.declare_resource_exists(role, role_arn='myrole:arn')
        plan = self.determine_plan(role)
        assert plan[0] == models.StoreValue(
            name='myrole_role_arn', value='myrole:arn')
        self.assert_apicall_equals(
            plan[1],
            models.APICall(
                method_name='put_role_policy',
                params={'role_name': 'myrole',
                        'policy_name': 'myrole',
                        'policy_document': {'iam': 'policy'}},
            )
        )

    def test_no_update_for_non_managed_role(self):
        role = models.PreCreatedIAMRole(role_arn='role:arn')
        plan = self.determine_plan(role)
        assert plan == []


class TestPlanLambdaFunction(BasePlannerTests):
    def test_can_create_function(self):
        function = create_function_resource('function_name')
        self.remote_state.declare_no_resources_exists()
        plan = self.determine_plan(function)
        expected = [models.APICall(
            method_name='create_function',
            params={
                'function_name': 'appname-dev-function_name',
                'role_arn': 'role:arn',
                'zip_contents': mock.ANY,
                'runtime': 'python2.7',
                'handler': 'app.app',
                'environment_variables': {},
                'tags': {},
                'timeout': 60,
                'memory_size': 128,
                'security_group_ids': [],
                'subnet_ids': [],
                'layers': None
            },
        ),
            models.APICall(
            method_name='delete_function_concurrency',
            params={
                'function_name': 'appname-dev-function_name',
            },
            output_var='reserved_concurrency_result',
        )]

        # create_function
        self.assert_apicall_equals(plan[0], expected[0])
        # delete_function_concurrency
        self.assert_apicall_equals(plan[2], expected[1])

        assert list(self.last_plan.messages.values()) == [
            'Creating lambda function: appname-dev-function_name\n',
        ]

    def test_create_function_with_layers(self):
        layers = ['arn:aws:lambda:us-east-1:111:layer:test_layer:1']
        function = create_function_resource('function_name', layers=layers)
        self.remote_state.declare_no_resources_exists()
        plan = self.determine_plan(function)
        expected = [models.APICall(
            method_name='create_function',
            params={
                'function_name': 'appname-dev-function_name',
                'role_arn': 'role:arn',
                'zip_contents': mock.ANY,
                'runtime': 'python2.7',
                'handler': 'app.app',
                'environment_variables': {},
                'tags': {},
                'timeout': 60,
                'memory_size': 128,
                'security_group_ids': [],
                'subnet_ids': [],
                'layers': layers
            },
        ),
            models.APICall(
                method_name='delete_function_concurrency',
                params={
                    'function_name': 'appname-dev-function_name',
                },
                output_var='reserved_concurrency_result',
            )]

        # create_function
        self.assert_apicall_equals(plan[0], expected[0])
        # delete_function_concurrency
        self.assert_apicall_equals(plan[2], expected[1])

        assert list(self.last_plan.messages.values()) == [
            'Creating lambda function: appname-dev-function_name\n',
        ]

    def test_can_update_lambda_function_code(self):
        function = create_function_resource('function_name')
        copy_of_function = attr.evolve(function)
        self.remote_state.declare_resource_exists(copy_of_function)
        # Now let's change the memory size and ensure we
        # get an update.
        function.memory_size = 256
        plan = self.determine_plan(function)
        existing_params = {
            'function_name': 'appname-dev-function_name',
            'role_arn': 'role:arn',
            'zip_contents': mock.ANY,
            'runtime': 'python2.7',
            'environment_variables': {},
            'tags': {},
            'timeout': 60,
            'security_group_ids': [],
            'subnet_ids': [],
            'layers': None
        }
        expected_params = dict(memory_size=256, **existing_params)
        expected = [models.APICall(
            method_name='update_function',
            params=expected_params,
        ),
            models.APICall(
            method_name='delete_function_concurrency',
            params={
                'function_name': 'appname-dev-function_name',
            },
            output_var='reserved_concurrency_result',
        )]

        # update_function
        self.assert_apicall_equals(plan[0], expected[0])
        # delete_function_concurrency
        self.assert_apicall_equals(plan[3], expected[1])

        assert list(self.last_plan.messages.values()) == [
            'Updating lambda function: appname-dev-function_name\n',
        ]

    def test_can_create_function_with_reserved_concurrency(self):
        function = create_function_resource('function_name')
        function.reserved_concurrency = 5
        self.remote_state.declare_no_resources_exists()
        plan = self.determine_plan(function)
        expected = [models.APICall(
            method_name='create_function',
            params={
                'function_name': 'appname-dev-function_name',
                'role_arn': 'role:arn',
                'zip_contents': mock.ANY,
                'runtime': 'python2.7',
                'handler': 'app.app',
                'environment_variables': {},
                'tags': {},
                'timeout': 60,
                'memory_size': 128,
                'security_group_ids': [],
                'subnet_ids': [],
                'layers': None
            },
        ),
            models.APICall(
            method_name='put_function_concurrency',
            params={
                'function_name': 'appname-dev-function_name',
                'reserved_concurrent_executions': 5
            },
            output_var='reserved_concurrency_result',
        )]

        # create_function
        self.assert_apicall_equals(plan[0], expected[0])
        # put_function_concurrency
        self.assert_apicall_equals(plan[2], expected[1])

        assert list(self.last_plan.messages.values()) == [
            'Creating lambda function: appname-dev-function_name\n',
            'Updating lambda function concurrency limit:'
            ' appname-dev-function_name\n',
        ]

    def test_can_set_variables_when_needed(self):
        function = create_function_resource('function_name')
        self.remote_state.declare_no_resources_exists()
        function.role = models.ManagedIAMRole(
            resource_name='myrole',
            role_name='myrole-dev',
            trust_policy={'trust': 'policy'},
            policy=models.FileBasedIAMPolicy(
                filename='foo.json', document={'iam': 'role'}),
        )
        plan = self.determine_plan(function)
        call = plan[0]
        assert call.method_name == 'create_function'
        # The params are verified in test_can_create_function,
        # we just care about how the role_arn Variable is constructed.
        role_arn = call.params['role_arn']
        assert isinstance(role_arn, Variable)
        assert role_arn.name == 'myrole-dev_role_arn'


class TestPlanS3Events(BasePlannerTests):
    def test_can_plan_s3_event(self):
        function = create_function_resource('function_name')
        bucket_event = models.S3BucketNotification(
            resource_name='function_name-s3event',
            bucket='mybucket',
            events=['s3:ObjectCreated:*'],
            prefix=None,
            suffix=None,
            lambda_function=function,
        )
        plan = self.determine_plan(bucket_event)
        self.assert_apicall_equals(
            plan[0],
            models.APICall(
                method_name='add_permission_for_s3_event',
                params={
                    'bucket': 'mybucket',
                    'function_arn': Variable('function_name_lambda_arn'),
                },
            )
        )
        self.assert_apicall_equals(
            plan[1],
            models.APICall(
                method_name='connect_s3_bucket_to_lambda',
                params={
                    'bucket': 'mybucket',
                    'function_arn': Variable('function_name_lambda_arn'),
                    'events': ['s3:ObjectCreated:*'],
                    'prefix': None,
                    'suffix': None,
                },
            )
        )
        assert plan[2] == models.RecordResourceValue(
            resource_type='s3_event',
            resource_name='function_name-s3event',
            name='bucket',
            value='mybucket',
        )
        assert plan[3] == models.RecordResourceVariable(
            resource_type='s3_event',
            resource_name='function_name-s3event',
            name='lambda_arn',
            variable_name='function_name_lambda_arn',
        )


class TestPlanScheduledEvent(BasePlannerTests):
    def test_can_plan_scheduled_event(self):
        function = create_function_resource('function_name')
        event = models.ScheduledEvent(
            resource_name='bar',
            rule_name='myrulename',
            schedule_expression='rate(5 minutes)',
            lambda_function=function,
        )
        plan = self.determine_plan(event)
        assert len(plan) == 4
        self.assert_apicall_equals(
            plan[0],
            models.APICall(
                method_name='get_or_create_rule_arn',
                params={
                    'rule_name': 'myrulename',
                    'schedule_expression': 'rate(5 minutes)',
                },
                output_var='rule-arn',
            )
        )
        self.assert_apicall_equals(
            plan[1],
            models.APICall(
                method_name='connect_rule_to_lambda',
                params={'rule_name': 'myrulename',
                        'function_arn': Variable('function_name_lambda_arn')}
            )
        )
        self.assert_apicall_equals(
            plan[2],
            models.APICall(
                method_name='add_permission_for_scheduled_event',
                params={
                    'rule_arn': Variable('rule-arn'),
                    'function_arn': Variable('function_name_lambda_arn'),
                },
            )
        )
        assert plan[3] == models.RecordResourceValue(
            resource_type='cloudwatch_event',
            resource_name='bar',
            name='rule_name',
            value='myrulename',
        )


class TestPlanRestAPI(BasePlannerTests):
    def assert_loads_needed_variables(self, plan):
        # Parse arn and store region/account id for future
        # API calls.
        assert plan[0:4] == [
            models.BuiltinFunction(
                'parse_arn', [Variable('function_name_lambda_arn')],
                output_var='parsed_lambda_arn',
            ),
            models.JPSearch('account_id',
                            input_var='parsed_lambda_arn',
                            output_var='account_id'),
            models.JPSearch('region',
                            input_var='parsed_lambda_arn',
                            output_var='region_name'),
            # Verify we copy the function arn as needed.
            models.CopyVariable(
                from_var='function_name_lambda_arn',
                to_var='api_handler_lambda_arn'),
        ]

    def test_can_plan_rest_api(self):
        function = create_function_resource('function_name')
        rest_api = models.RestAPI(
            resource_name='rest_api',
            swagger_doc={'swagger': '2.0'},
            api_gateway_stage='api',
            lambda_function=function,
        )
        plan = self.determine_plan(rest_api)
        self.assert_loads_needed_variables(plan)
        assert plan[4:] == [
            models.APICall(
                method_name='import_rest_api',
                params={'swagger_document': {'swagger': '2.0'}},
                output_var='rest_api_id',
            ),
            models.RecordResourceVariable(
                resource_type='rest_api',
                resource_name='rest_api',
                name='rest_api_id',
                variable_name='rest_api_id',
            ),
            models.APICall(method_name='deploy_rest_api',
                           params={'rest_api_id': Variable('rest_api_id'),
                                   'api_gateway_stage': 'api'}),
            models.APICall(
                method_name='add_permission_for_apigateway',
                params={
                    'function_name': 'appname-dev-function_name',
                    'region_name': Variable('region_name'),
                    'account_id': Variable('account_id'),
                    'rest_api_id': Variable('rest_api_id'),
                }
            ),
            models.StoreValue(
                name='rest_api_url',
                value=StringFormat(
                    'https://{rest_api_id}.execute-api.{region_name}'
                    '.amazonaws.com/api/',
                    ['rest_api_id', 'region_name'],
                ),
            ),
            models.RecordResourceVariable(
                resource_type='rest_api',
                resource_name='rest_api',
                name='rest_api_url',
                variable_name='rest_api_url'
            ),
        ]
        assert list(self.last_plan.messages.values()) == [
            'Creating Rest API\n'
        ]

    def test_can_update_rest_api(self):
        function = create_function_resource('function_name')
        rest_api = models.RestAPI(
            resource_name='rest_api',
            swagger_doc={'swagger': '2.0'},
            api_gateway_stage='api',
            lambda_function=function,
        )
        self.remote_state.declare_resource_exists(rest_api)
        self.remote_state.deployed_values['rest_api'] = {
            'rest_api_id': 'my_rest_api_id',
        }
        plan = self.determine_plan(rest_api)
        self.assert_loads_needed_variables(plan)
        assert plan[4:] == [
            models.StoreValue(name='rest_api_id', value='my_rest_api_id'),
            models.RecordResourceVariable(
                resource_type='rest_api',
                resource_name='rest_api',
                name='rest_api_id',
                variable_name='rest_api_id',
            ),
            models.APICall(
                method_name='update_api_from_swagger',
                params={
                    'rest_api_id': Variable('rest_api_id'),
                    'swagger_document': {'swagger': '2.0'},
                },
            ),
            models.APICall(
                method_name='deploy_rest_api',
                params={'rest_api_id': Variable('rest_api_id'),
                        'api_gateway_stage': 'api'},
            ),
            models.APICall(
                method_name='add_permission_for_apigateway',
                params={'function_name': 'appname-dev-function_name',
                        'region_name': Variable('region_name'),
                        'account_id': Variable('account_id'),
                        'rest_api_id': Variable('rest_api_id')},
            ),
            models.APICall(
                method_name='add_permission_for_apigateway',
                params={'rest_api_id': Variable("rest_api_id"),
                        'region_name': Variable("region_name"),
                        'account_id': Variable("account_id"),
                        'function_name': 'appname-dev-function_name'},
                output_var=None),
            models.StoreValue(
                name='rest_api_url',
                value=StringFormat(
                    'https://{rest_api_id}.execute-api.{region_name}'
                    '.amazonaws.com/api/',
                    ['rest_api_id', 'region_name'],
                ),
            ),
            models.RecordResourceVariable(
                resource_type='rest_api',
                resource_name='rest_api',
                name='rest_api_url',
                variable_name='rest_api_url'
            ),
        ]


class TestPlanSNSSubscription(BasePlannerTests):
    def test_can_plan_sns_subscription(self):
        function = create_function_resource('function_name')
        sns_subscription = models.SNSLambdaSubscription(
            resource_name='function_name-sns-subscription',
            topic='mytopic',
            lambda_function=function
        )
        plan = self.determine_plan(sns_subscription)
        plan_parse_arn = plan[:4]
        assert plan_parse_arn == [
            models.BuiltinFunction(
                function_name='parse_arn',
                args=[Variable("function_name_lambda_arn")],
                output_var='parsed_lambda_arn'),
            models.JPSearch(
                expression='account_id',
                input_var='parsed_lambda_arn',
                output_var='account_id'),
            models.JPSearch(
                expression='region',
                input_var='parsed_lambda_arn',
                output_var='region_name'),
            models.StoreValue(
                name='function_name-sns-subscription_topic_arn',
                value=StringFormat(
                    "arn:aws:sns:{region_name}:{account_id}:mytopic",
                    variables=['region_name', 'account_id'],
                )
            ),
        ]
        topic_arn_var = Variable("function_name-sns-subscription_topic_arn")
        assert plan[4:] == [
            models.APICall(
                method_name='add_permission_for_sns_topic',
                params={
                    'function_arn': Variable("function_name_lambda_arn"),
                    'topic_arn': topic_arn_var,
                },
                output_var=None
            ),
            models.APICall(
                method_name='subscribe_function_to_topic',
                params={
                    'function_arn': Variable("function_name_lambda_arn"),
                    'topic_arn': topic_arn_var,
                },
                output_var='function_name-sns-subscription_subscription_arn'
            ),
            models.RecordResourceValue(
                resource_type='sns_event',
                resource_name='function_name-sns-subscription',
                name='topic',
                value='mytopic'),
            models.RecordResourceVariable(
                resource_type='sns_event',
                resource_name='function_name-sns-subscription',
                name='lambda_arn',
                variable_name='function_name_lambda_arn'
            ),
            models.RecordResourceVariable(
                resource_type='sns_event',
                resource_name='function_name-sns-subscription',
                name='subscription_arn',
                variable_name='function_name-sns-subscription_subscription_arn'
            ),
            models.RecordResourceVariable(
                resource_type='sns_event',
                resource_name='function_name-sns-subscription',
                name='topic_arn',
                variable_name='function_name-sns-subscription_topic_arn',
            ),
        ]

    def test_can_plan_sns_arn_subscription(self):
        function = create_function_resource('function_name')
        topic_arn = 'arn:aws:sns:mars-west-2:123456789:mytopic'
        sns_subscription = models.SNSLambdaSubscription(
            resource_name='function_name-sns-subscription',
            topic=topic_arn,
            lambda_function=function
        )
        plan = self.determine_plan(sns_subscription)
        plan_parse_arn = plan[0]
        assert plan_parse_arn == models.StoreValue(
            name='function_name-sns-subscription_topic_arn',
            value=topic_arn,
        )
        topic_arn_var = Variable("function_name-sns-subscription_topic_arn")
        assert plan[1:] == [
            models.APICall(
                method_name='add_permission_for_sns_topic',
                params={
                    'function_arn': Variable("function_name_lambda_arn"),
                    'topic_arn': topic_arn_var,
                },
                output_var=None
            ),
            models.APICall(
                method_name='subscribe_function_to_topic',
                params={
                    'function_arn': Variable("function_name_lambda_arn"),
                    'topic_arn': topic_arn_var,
                },
                output_var='function_name-sns-subscription_subscription_arn'
            ),
            models.RecordResourceValue(
                resource_type='sns_event',
                resource_name='function_name-sns-subscription',
                name='topic',
                value=topic_arn),
            models.RecordResourceVariable(
                resource_type='sns_event',
                resource_name='function_name-sns-subscription',
                name='lambda_arn',
                variable_name='function_name_lambda_arn'
            ),
            models.RecordResourceVariable(
                resource_type='sns_event',
                resource_name='function_name-sns-subscription',
                name='subscription_arn',
                variable_name='function_name-sns-subscription_subscription_arn'
            ),
            models.RecordResourceVariable(
                resource_type='sns_event',
                resource_name='function_name-sns-subscription',
                name='topic_arn',
                variable_name='function_name-sns-subscription_topic_arn',
            ),
        ]

    def test_sns_subscription_exists_is_noop_for_planner(self):
        function = create_function_resource('function_name')
        sns_subscription = models.SNSLambdaSubscription(
            resource_name='function_name-sns-subscription',
            topic='mytopic',
            lambda_function=function
        )
        self.remote_state.declare_resource_exists(
            sns_subscription,
            topic='mytopic',
            resource_type='sns_event',
            lambda_arn='arn:lambda',
            subscription_arn='arn:aws:subscribe',
        )
        plan = self.determine_plan(sns_subscription)
        plan_parse_arn = plan[:4]
        assert plan_parse_arn == [
            models.BuiltinFunction(
                function_name='parse_arn',
                args=[Variable("function_name_lambda_arn")],
                output_var='parsed_lambda_arn'),
            models.JPSearch(
                expression='account_id',
                input_var='parsed_lambda_arn',
                output_var='account_id'),
            models.JPSearch(
                expression='region',
                input_var='parsed_lambda_arn',
                output_var='region_name'),
            models.StoreValue(
                name='function_name-sns-subscription_topic_arn',
                value=StringFormat(
                    "arn:aws:sns:{region_name}:{account_id}:mytopic",
                    variables=['region_name', 'account_id'],
                )
            ),
        ]
        assert plan[4:] == [
            models.RecordResourceValue(
                resource_type='sns_event',
                resource_name='function_name-sns-subscription',
                name='topic',
                value='mytopic'),
            models.RecordResourceVariable(
                resource_type='sns_event',
                resource_name='function_name-sns-subscription',
                name='lambda_arn',
                variable_name='function_name_lambda_arn'
            ),
            models.RecordResourceValue(
                resource_type='sns_event',
                resource_name='function_name-sns-subscription',
                name='subscription_arn',
                value='arn:aws:subscribe',
            ),
            models.RecordResourceVariable(
                resource_type='sns_event',
                resource_name='function_name-sns-subscription',
                name='topic_arn',
                variable_name='function_name-sns-subscription_topic_arn',
            ),
        ]


class TestPlanSQSSubscription(BasePlannerTests):
    def test_can_plan_sqs_event_source(self):
        function = create_function_resource('function_name')
        sqs_event_source = models.SQSEventSource(
            resource_name='function_name-sqs-event-source',
            queue='myqueue',
            batch_size=10,
            lambda_function=function
        )
        plan = self.determine_plan(sqs_event_source)
        plan_parse_arn = plan[:4]
        assert plan_parse_arn == [
            models.BuiltinFunction(
                function_name='parse_arn',
                args=[Variable("function_name_lambda_arn")],
                output_var='parsed_lambda_arn'
            ),
            models.JPSearch(
                expression='account_id',
                input_var='parsed_lambda_arn',
                output_var='account_id'
            ),
            models.JPSearch(
                expression='region',
                input_var='parsed_lambda_arn',
                output_var='region_name'
            ),
            models.StoreValue(
                name='function_name-sqs-event-source_queue_arn',
                value=StringFormat(
                    "arn:aws:sqs:{region_name}:{account_id}:myqueue",
                    variables=['region_name', 'account_id'],
                ),
            )
        ]
        assert plan[4:] == [
            models.APICall(
                method_name='create_sqs_event_source',
                params={
                    'queue_arn': Variable(
                        "function_name-sqs-event-source_queue_arn"
                    ),
                    'batch_size': 10,
                    'function_name': Variable("function_name_lambda_arn")
                },
                output_var='function_name-sqs-event-source_uuid'
            ),
            models.RecordResourceVariable(
                resource_type='sqs_event',
                resource_name='function_name-sqs-event-source',
                name='queue_arn',
                variable_name='function_name-sqs-event-source_queue_arn'
            ),
            models.RecordResourceVariable(
                resource_type='sqs_event',
                resource_name='function_name-sqs-event-source',
                name='event_uuid',
                variable_name='function_name-sqs-event-source_uuid'
            ),
            models.RecordResourceValue(
                resource_type='sqs_event',
                resource_name='function_name-sqs-event-source',
                name='queue',
                value='myqueue'
            ),
            models.RecordResourceVariable(
                resource_type='sqs_event',
                resource_name='function_name-sqs-event-source',
                name='lambda_arn',
                variable_name='function_name_lambda_arn'
            )
        ]

    def test_sqs_event_source_exists_updates_batch_size(self):
        function = create_function_resource('function_name')
        sqs_event_source = models.SQSEventSource(
            resource_name='function_name-sqs-event-source',
            queue='myqueue',
            batch_size=10,
            lambda_function=function
        )
        self.remote_state.declare_resource_exists(
            sqs_event_source,
            queue='myqueue',
            queue_arn='arn:sqs:myqueue',
            resource_type='sqs_event',
            lambda_arn='arn:lambda',
            event_uuid='my-uuid',
        )
        plan = self.determine_plan(sqs_event_source)
        plan_parse_arn = plan[:4]
        assert plan_parse_arn == [
            models.BuiltinFunction(
                function_name='parse_arn',
                args=[Variable("function_name_lambda_arn")],
                output_var='parsed_lambda_arn'),
            models.JPSearch(
                expression='account_id',
                input_var='parsed_lambda_arn',
                output_var='account_id'),
            models.JPSearch(
                expression='region',
                input_var='parsed_lambda_arn',
                output_var='region_name'),
            models.StoreValue(
                name='function_name-sqs-event-source_queue_arn',
                value=StringFormat(
                    "arn:aws:sqs:{region_name}:{account_id}:myqueue",
                    variables=['region_name', 'account_id'],
                ),
            )
        ]
        assert plan[4:] == [
            models.APICall(
                method_name='update_sqs_event_source',
                params={
                    'event_uuid': 'my-uuid',
                    'batch_size': 10,
                },
            ),
            models.RecordResourceValue(
                resource_type='sqs_event',
                resource_name='function_name-sqs-event-source',
                name='queue_arn',
                value='arn:sqs:myqueue',
            ),
            models.RecordResourceValue(
                resource_type='sqs_event',
                resource_name='function_name-sqs-event-source',
                name='event_uuid',
                value='my-uuid'
            ),
            models.RecordResourceValue(
                resource_type='sqs_event',
                resource_name='function_name-sqs-event-source',
                name='queue',
                value='myqueue'
            ),
            models.RecordResourceValue(
                resource_type='sqs_event',
                resource_name='function_name-sqs-event-source',
                name='lambda_arn',
                value='arn:lambda'
            )
        ]


class TestRemoteState(object):
    def setup_method(self):
        self.client = mock.Mock(spec=TypedAWSClient)
        self.config = FakeConfig({'resources': []})
        self.remote_state = RemoteState(
            self.client, self.config.deployed_resources('dev'),
        )

    def create_rest_api_model(self):
        rest_api = models.RestAPI(
            resource_name='rest_api',
            swagger_doc={'swagger': '2.0'},
            api_gateway_stage='api',
            lambda_function=None,
        )
        return rest_api

    def test_role_exists(self):
        self.client.get_role_arn_for_name.return_value = 'role:arn'
        role = models.ManagedIAMRole('my_role',
                                     role_name='app-dev', trust_policy={},
                                     policy=None)
        assert self.remote_state.resource_exists(role)
        self.client.get_role_arn_for_name.assert_called_with('app-dev')

    def test_role_does_not_exist(self):
        client = self.client
        client.get_role_arn_for_name.side_effect = ResourceDoesNotExistError()
        role = models.ManagedIAMRole('my_role',
                                     role_name='app-dev', trust_policy={},
                                     policy=None)
        assert not self.remote_state.resource_exists(role)
        self.client.get_role_arn_for_name.assert_called_with('app-dev')

    def test_lambda_function_exists(self):
        function = create_function_resource('function-name')
        self.client.lambda_function_exists.return_value = True
        assert self.remote_state.resource_exists(function)
        self.client.lambda_function_exists.assert_called_with(
            function.function_name)

    def test_lambda_function_does_not_exist(self):
        function = create_function_resource('function-name')
        self.client.lambda_function_exists.return_value = False
        assert not self.remote_state.resource_exists(function)
        self.client.lambda_function_exists.assert_called_with(
            function.function_name)

    def test_exists_check_is_cached(self):
        function = create_function_resource('function-name')
        self.client.lambda_function_exists.return_value = True
        assert self.remote_state.resource_exists(function)
        # Now if we call this method repeatedly we should only invoke
        # the underlying client method once.  Subsequent calls are cached.
        assert self.remote_state.resource_exists(function)
        assert self.remote_state.resource_exists(function)

        assert self.client.lambda_function_exists.call_count == 1

    def test_rest_api_exists_no_deploy(self, no_deployed_values):
        rest_api = self.create_rest_api_model()
        remote_state = RemoteState(
            self.client, no_deployed_values)
        assert not remote_state.resource_exists(rest_api)
        assert not self.client.rest_api_exists.called

    def test_api_exists_with_existing_deploy(self):
        rest_api = self.create_rest_api_model()
        deployed_resources = {
            'resources': [{
                'name': 'rest_api',
                'resource_type': 'rest_api',
                'rest_api_id': 'my_rest_api_id',
            }]
        }
        self.client.rest_api_exists.return_value = True
        remote_state = RemoteState(
            self.client, DeployedResources(deployed_resources))
        assert remote_state.resource_exists(rest_api)
        self.client.rest_api_exists.assert_called_with('my_rest_api_id')

    def test_rest_api_not_exists_with_preexisting_deploy(self):
        rest_api = self.create_rest_api_model()
        deployed_resources = {
            'resources': [{
                'name': 'rest_api',
                'resource_type': 'rest_api',
                'rest_api_id': 'my_rest_api_id',
            }]
        }
        self.client.rest_api_exists.return_value = False
        remote_state = RemoteState(
            self.client, DeployedResources(deployed_resources))
        assert not remote_state.resource_exists(rest_api)
        self.client.rest_api_exists.assert_called_with('my_rest_api_id')

    def test_can_get_deployed_values(self):
        remote_state = RemoteState(
            self.client, DeployedResources({'resources': [
                {'name': 'rest_api', 'rest_api_id': 'foo'}]})
        )
        rest_api = self.create_rest_api_model()
        values = remote_state.resource_deployed_values(rest_api)
        assert values == {'name': 'rest_api', 'rest_api_id': 'foo'}

    def test_value_error_raised_on_no_deployed_values(self,
                                                      no_deployed_values):
        remote_state = RemoteState(self.client,
                                   deployed_resources=no_deployed_values)
        rest_api = self.create_rest_api_model()
        with pytest.raises(ValueError):
            remote_state.resource_deployed_values(rest_api)

    def test_value_error_raised_for_unknown_resource_name(self):
        remote_state = RemoteState(
            self.client, DeployedResources({'resources': [
                {'name': 'not_rest_api', 'rest_api_id': 'foo'}]})
        )
        rest_api = self.create_rest_api_model()
        with pytest.raises(ValueError):
            remote_state.resource_deployed_values(rest_api)

    def test_dynamically_lookup_iam_role(self):
        remote_state = RemoteState(
            self.client, DeployedResources({'resources': [
                {'name': 'rest_api', 'rest_api_id': 'foo'}]})
        )
        resource = models.ManagedIAMRole(
            resource_name='default-role',
            role_name='myrole',
            trust_policy={'trust': 'policy'},
            policy=models.AutoGenIAMPolicy(document={'iam': 'policy'}),
        )
        self.client.get_role_arn_for_name.return_value = 'my-role-arn'
        values = remote_state.resource_deployed_values(resource)
        assert values == {
            'name': 'default-role',
            'resource_type': 'iam_role',
            'role_arn': 'my-role-arn',
            'role_name': 'myrole'
        }

    def test_unknown_model_type_raises_error(self):

        @attr.attrs
        class Foo(models.ManagedModel):
            resource_type = 'foo'

        foo = Foo(resource_name='myfoo')
        with pytest.raises(ValueError):
            self.remote_state.resource_exists(foo)

    @pytest.mark.parametrize(
        'resource_topic,deployed_topic,is_current,expected_result', [
            ('mytopic', 'mytopic', True, True),
            ('mytopic-new', 'mytopic-old', False, False),
        ]
    )
    def test_sns_subscription_exists(self, resource_topic, deployed_topic,
                                     is_current, expected_result):
        sns_subscription = models.SNSLambdaSubscription(
            topic=resource_topic, resource_name='handler-sns-subscription',
            lambda_function=None
        )
        deployed_resources = {
            'resources': [{
                'name': 'handler-sns-subscription',
                'topic': deployed_topic,
                'resource_type': 'sns_event',
                'lambda_arn': 'arn:lambda',
                'subscription_arn': 'arn:aws:subscribe',
            }]
        }
        self.client.verify_sns_subscription_current.return_value = \
            is_current
        remote_state = RemoteState(
            self.client, DeployedResources(deployed_resources))
        assert (
            remote_state.resource_exists(sns_subscription) == expected_result
        )
        self.client.verify_sns_subscription_current.assert_called_with(
            'arn:aws:subscribe',
            topic_name=resource_topic,
            function_arn='arn:lambda',
        )

    def test_sns_subscription_not_in_deployed_values(self):
        sns_subscription = models.SNSLambdaSubscription(
            topic='mytopic', resource_name='handler-sns-subscription',
            lambda_function=None
        )
        deployed_resources = {'resources': []}
        remote_state = RemoteState(
            self.client, DeployedResources(deployed_resources))
        assert not remote_state.resource_exists(sns_subscription)
        assert not self.client.verify_sns_subscription_current.called

    @pytest.mark.parametrize(
        'new_queue,deployed_queue,expected_result', [
            ('queue', 'queue', True),
            ('new-queue', 'queue', False),
            ('new-queue', None, False),
        ]
    )
    def test_sqs_event_source_exists(self, new_queue, deployed_queue,
                                     expected_result):
        event_source = models.SQSEventSource(
            resource_name='handler-sqs-event-source',
            queue=new_queue, batch_size=100, lambda_function=None
        )
        if deployed_queue is not None:
            deployed_resources = {
                'resources': [{
                    'queue': deployed_queue,
                    'queue_arn': 'arn:aws:sqs:us-west-2:123:myqueue',
                    'name': 'handler-sqs-event-source',
                    'lambda_arn': 'arn:aws:lambda:handler',
                    'event_uuid': 'event-uid-123',
                    'resource_type': 'sqs_event'
                }]
            }
        else:
            deployed_resources = {'resources': []}
        self.client.verify_event_source_current.return_value = \
            new_queue == deployed_queue
        remote_state = RemoteState(
            self.client, DeployedResources(deployed_resources),
        )
        assert remote_state.resource_exists(event_source) == expected_result
        if deployed_queue is not None:
            self.client.verify_event_source_current.assert_called_with(
                event_uuid='event-uid-123',
                resource_name=new_queue,
                service_name='sqs',
                function_arn='arn:aws:lambda:handler',
            )


class TestUnreferencedResourcePlanner(BasePlannerTests):
    def setup_method(self):
        super(TestUnreferencedResourcePlanner, self).setup_method()
        self.sweeper = ResourceSweeper()

    def execute(self, plan, config):
        self.sweeper.execute(models.Plan(plan, messages={}), config)

    @pytest.fixture
    def function_resource(self):
        return create_function_resource('myfunction')

    def one_deployed_lambda_function(self, name='myfunction', arn='arn'):
        return {
            'resources': [{
                'name': name,
                'resource_type': 'lambda_function',
                'lambda_arn': arn,
            }]
        }

    def test_noop_when_all_resources_accounted_for(self, function_resource):
        plan = [
            models.RecordResource(
                resource_type='lambda_function',
                resource_name='myfunction',
                name='foo',
            )
        ]
        original_plan = plan[:]
        deployed = self.one_deployed_lambda_function(name='myfunction')
        config = FakeConfig(deployed)
        self.execute(plan, config)
        # We shouldn't add anything to the list.
        assert plan == original_plan

    def test_will_delete_unreferenced_resource(self):
        plan = []
        deployed = self.one_deployed_lambda_function()
        config = FakeConfig(deployed)
        self.execute(plan, config)
        assert len(plan) == 1
        assert plan[0].method_name == 'delete_function'
        assert plan[0].params == {'function_name': 'arn'}

    def test_supports_multiple_unreferenced_and_unchanged(self):
        first = create_function_resource('first')
        second = create_function_resource('second')
        third = create_function_resource('third')
        plan = [
            models.RecordResource(
                resource_type='lambda_function',
                resource_name=first.resource_name,
                name='foo',
            ),
            models.RecordResource(
                resource_type='asdf',
                resource_name=second.resource_name,
                name='foo',
            )
        ]
        deployed = {
            'resources': [{
                'name': second.resource_name,
                'resource_type': 'lambda_function',
                'lambda_arn': 'second_arn',
            }, {
                'name': third.resource_name,
                'resource_type': 'lambda_function',
                'lambda_arn': 'third_arn',
            }]
        }
        config = FakeConfig(deployed)
        self.execute(plan, config)
        assert len(plan) == 3
        assert plan[2].method_name == 'delete_function'
        assert plan[2].params == {'function_name': 'third_arn'}

    def test_can_delete_iam_role(self):
        plan = []
        deployed = {
            'resources': [{
                'name': 'myrole',
                'resource_type': 'iam_role',
                'role_name': 'myrole',
                'role_arn': 'arn:role/myrole',
            }]
        }
        config = FakeConfig(deployed)
        self.execute(plan, config)
        assert len(plan) == 1
        assert plan[0].method_name == 'delete_role'
        assert plan[0].params == {'name': 'myrole'}

    def test_correct_deletion_order_for_dependencies(self):
        plan = []
        deployed = {
            # This is the order they were deployed.  While not
            # strictly required for IAM Roles, we typically
            # want to delete resources in the reverse order they
            # were created.
            'resources': [
                {
                    'name': 'myrole',
                    'resource_type': 'iam_role',
                    'role_name': 'myrole',
                    'role_arn': 'arn:role/myrole',
                },
                {
                    'name': 'myrole2',
                    'resource_type': 'iam_role',
                    'role_name': 'myrole2',
                    'role_arn': 'arn:role/myrole2',
                },
                {
                    'name': 'myfunction',
                    'resource_type': 'lambda_function',
                    'lambda_arn': 'my:arn',
                }
            ]
        }
        config = FakeConfig(deployed)
        self.execute(plan, config)
        assert len(plan) == 3
        expected_api_calls = [p.method_name for p in plan]
        assert expected_api_calls == ['delete_function',
                                      'delete_role',
                                      'delete_role']

        expected_api_args = [p.params for p in plan]
        assert expected_api_args == [
            {'function_name': 'my:arn'},
            {'name': 'myrole2'},
            {'name': 'myrole'},
        ]

    def test_can_delete_scheduled_event(self):
        plan = []
        deployed = {
            'resources': [{
                'name': 'index-event',
                'resource_type': 'cloudwatch_event',
                'rule_name': 'app-dev-index-event',
            }]
        }
        config = FakeConfig(deployed)
        self.execute(plan, config)
        assert plan == [
            models.APICall(
                method_name='delete_rule',
                params={'rule_name': 'app-dev-index-event'},
            )
        ]

    def test_can_delete_s3_event(self):
        plan = []
        deployed = {
            'resources': [{
                'name': 'test-s3-event',
                'resource_type': 's3_event',
                'bucket': 'mybucket',
                'lambda_arn': 'lambda_arn',
            }]
        }
        config = FakeConfig(deployed)
        self.execute(plan, config)
        assert plan == [
            models.APICall(
                method_name='disconnect_s3_bucket_from_lambda',
                params={'bucket': 'mybucket', 'function_arn': 'lambda_arn'},
            ),
            models.APICall(
                method_name='remove_permission_for_s3_event',
                params={'bucket': 'mybucket', 'function_arn': 'lambda_arn'},
            )
        ]

    def test_can_delete_rest_api(self):
        plan = []
        deployed = {
            'resources': [{
                'name': 'rest_api',
                'rest_api_id': 'my_rest_api_id',
                'resource_type': 'rest_api',
            }]
        }
        config = FakeConfig(deployed)
        self.execute(plan, config)
        assert plan == [
            models.APICall(
                method_name='delete_rest_api',
                params={'rest_api_id': 'my_rest_api_id'},
            )
        ]

    def test_can_handle_when_resource_changes_values(self):
        plan = self.determine_plan(
            models.S3BucketNotification(
                resource_name='test-s3-event',
                bucket='NEWBUCKET',
                events=['s3:ObjectCreated:*'],
                prefix=None,
                suffix=None,
                lambda_function=create_function_resource('function_name'),
            )
        )
        deployed = {
            'resources': [{
                'name': 'test-s3-event',
                'resource_type': 's3_event',
                'bucket': 'OLDBUCKET',
                'lambda_arn': 'lambda_arn',
            }]
        }
        config = FakeConfig(deployed)
        self.execute(plan, config)
        assert plan[-2:] == [
            models.APICall(
                method_name='disconnect_s3_bucket_from_lambda',
                params={'bucket': 'OLDBUCKET', 'function_arn': 'lambda_arn'},
            ),
            models.APICall(
                method_name='remove_permission_for_s3_event',
                params={'bucket': 'OLDBUCKET', 'function_arn': 'lambda_arn'},
            ),
        ]

    def test_no_sweeping_when_resource_value_unchanged(self):
        plan = self.determine_plan(
            models.S3BucketNotification(
                resource_name='test-s3-event',
                bucket='EXISTING-BUCKET',
                events=['s3:ObjectCreated:*'],
                prefix=None,
                suffix=None,
                lambda_function=create_function_resource('function_name'),
            )
        )
        deployed = {
            'resources': [{
                'name': 'test-s3-event',
                'resource_type': 's3_event',
                'bucket': 'EXISTING-BUCKET',
                'lambda_arn': 'lambda_arn',
            }]
        }
        config = FakeConfig(deployed)
        original_plan = plan[:]
        self.execute(plan, config)
        assert plan == original_plan

    def test_can_delete_sns_subscription(self):
        plan = []
        deployed = {
            'resources': [{
                'name': 'handler-sns-subscription',
                'topic': 'mytopic',
                'topic_arn': 'arn:mytopic',
                'resource_type': 'sns_event',
                'lambda_arn': 'arn:lambda',
                'subscription_arn': 'arn:aws:subscribe',
            }]
        }
        config = FakeConfig(deployed)
        self.execute(plan, config)
        assert plan == [
            models.APICall(
                method_name='unsubscribe_from_topic',
                params={'subscription_arn': 'arn:aws:subscribe'},
            ),
            models.APICall(
                method_name='remove_permission_for_sns_topic',
                params={
                    'topic_arn': 'arn:mytopic',
                    'function_arn': 'arn:lambda',
                },
            )
        ]

    def test_no_deletion_when_no_changes(self):
        plan = self.determine_plan(
            models.SNSLambdaSubscription(
                resource_name='handler-sns-subscription',
                topic='mytopic',
                lambda_function=create_function_resource('function_name')
            )
        )
        deployed = {
            'resources': [{
                'name': 'handler-sns-subscription',
                'topic': 'mytopic',
                'resource_type': 'sns_event',
                'lambda_arn': 'arn:lambda',
                'subscription_arn': 'arn:aws:subscribe',
            }]
        }
        config = FakeConfig(deployed)
        original_plan = plan[:]
        self.execute(plan, config)
        # We shouldn't have added anything to the plan.
        assert plan == original_plan

    def test_handles_when_topic_name_change(self):
        # So let's say we subscribed to a topic 'old-topic'
        # and deployed our app:
        deployed = {
            'resources': [{
                'name': 'handler-sns-subscription',
                'topic': 'old-topic',
                'topic_arn': 'arn:old-topic',
                'resource_type': 'sns_event',
                'lambda_arn': 'arn:lambda',
                'subscription_arn': 'arn:aws:subscribe',
            }]
        }
        # Now we update our app and change the topic param
        # to 'new-topic'
        plan = self.determine_plan(
            models.SNSLambdaSubscription(
                resource_name='handler-sns-subscription',
                topic='new-topic',
                lambda_function=create_function_resource('function_name')
            )
        )
        config = FakeConfig(deployed)
        self.execute(plan, config)
        # Then we should unsubscribe from the old-topic because it's
        # no longer referenced in our app.
        assert plan[-2:] == [
            models.APICall(
                method_name='unsubscribe_from_topic',
                params={'subscription_arn': 'arn:aws:subscribe'},
            ),
            models.APICall(
                method_name='remove_permission_for_sns_topic',
                params={
                    'topic_arn': 'arn:old-topic',
                    'function_arn': 'arn:lambda',
                },
            ),
        ]

    def test_no_sqs_deletion_when_no_changes(self):
        plan = self.determine_plan(
            models.SQSEventSource(
                resource_name='handler-sqs-event-source',
                queue='my-queue',
                batch_size=10,
                lambda_function=create_function_resource('function_name')
            )
        )
        deployed = {
            'resources': [{
                'name': 'handler-sqs-event-source',
                'queue': 'my-queue',
                'resource_type': 'sqs_event',
                'lambda_arn': 'arn:lambda',
                'event_uuid': 'event-uuid',
            }]
        }
        config = FakeConfig(deployed)
        original_plan = plan[:]
        self.execute(plan, config)
        assert plan == original_plan

    def test_can_delete_sqs_subscription(self):
        plan = []
        deployed = {
            'resources': [{
                'name': 'handler-sqs-event-source',
                'queue': 'my-queue',
                'resource_type': 'sqs_event',
                'lambda_arn': 'arn:lambda',
                'event_uuid': 'event-uuid',
            }]
        }
        config = FakeConfig(deployed)
        self.execute(plan, config)
        assert plan == [
            models.APICall(
                method_name='remove_sqs_event_source',
                params={'event_uuid': 'event-uuid'},
            ),
        ]

    def test_handles_when_queue_name_change(self):
        deployed = {
            'resources': [{
                'name': 'handler-sqs-event-source',
                'queue': 'my-queue',
                'resource_type': 'sqs_event',
                'lambda_arn': 'arn:lambda',
                'event_uuid': 'event-uuid',
            }]
        }
        plan = self.determine_plan(
            models.SQSEventSource(
                resource_name='handler-sqs-event-source',
                queue='my-new-queue',
                batch_size=10,
                lambda_function=create_function_resource('function_name')
            )
        )
        config = FakeConfig(deployed)
        self.execute(plan, config)
        assert plan[-1:] == [
            models.APICall(
                method_name='remove_sqs_event_source',
                params={'event_uuid': 'event-uuid'},
            ),
        ]
