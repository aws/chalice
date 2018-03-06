import mock

import attr
import pytest

from chalice.awsclient import TypedAWSClient, ResourceDoesNotExistError
from chalice.deploy import models
from chalice.config import DeployedResources2
from chalice.utils import OSUtils
from chalice.deploy.planner import PlanStage, Variable, RemoteState
from chalice.deploy.planner import UnreferencedResourcePlanner


def create_function_resource(name, function_name=None,
                             environment_variables=None,
                             runtime='python2.7', handler='app.app',
                             tags=None, timeout=60,
                             memory_size=128, deployment_package=None,
                             role=None):
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
    )


class FakeConfig(object):
    def __init__(self, deployed_values):
        self._deployed_values = deployed_values
        self.chalice_stage = 'dev'

    def deployed_resources(self, chalice_stage_name):
        return DeployedResources2(self._deployed_values)


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

    def declare_resource_exists(self, resource):
        key = (resource.resource_type, resource.resource_name)
        self.known_resources[key] = resource

    def declare_no_resources_exists(self):
        self.known_resources = {}

    def resource_deployed_values(self, resource):
        return self.deployed_values[resource.resource_name]


class BasePlannerTests(object):
    def setup_method(self):
        self.osutils = mock.Mock(spec=OSUtils)
        self.remote_state = InMemoryRemoteState()

    def assert_apicall_equals(self, expected, actual_api_call):
        # models.APICall has its own __eq__ method from attrs,
        # but in practice the assertion errors are unreadable and
        # it's not always clear which part of the API call object is
        # wrong.  To get better error messages each field is individually
        # compared.
        assert expected.method_name == actual_api_call.method_name
        assert expected.params == actual_api_call.params

    def determine_plan(self, resource):
        planner = PlanStage(self.remote_state, self.osutils)
        plan = planner.execute([resource])
        return plan


class TestPlanManagedRole(BasePlannerTests):
    def test_can_plan_for_iam_role_creation(self):
        self.remote_state.declare_no_resources_exists()
        resource = models.ManagedIAMRole(
            resource_name='default-role',
            role_arn=models.Placeholder.DEPLOY_STAGE,
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

    def test_can_create_plan_for_filebased_role(self):
        self.remote_state.declare_no_resources_exists()
        resource = models.ManagedIAMRole(
            resource_name='default-role',
            role_arn=models.Placeholder.DEPLOY_STAGE,
            role_name='myrole',
            trust_policy={'trust': 'policy'},
            policy=models.FileBasedIAMPolicy(filename='foo.json'),
        )
        self.osutils.get_file_contents.return_value = '{"iam": "policy"}'
        plan = self.determine_plan(resource)
        expected = models.APICall(
            method_name='create_role',
            params={'name': 'myrole',
                    'trust_policy': {'trust': 'policy'},
                    'policy': {'iam': 'policy'}},
        )
        self.assert_apicall_equals(plan[0], expected)

    def test_can_update_managed_role(self):
        role = models.ManagedIAMRole(
            resource_name='resource_name',
            role_arn='myrole:arn',
            role_name='myrole',
            trust_policy={},
            policy=models.AutoGenIAMPolicy(document={'role': 'policy'}),
        )
        self.remote_state.declare_resource_exists(role)
        plan = self.determine_plan(role)
        self.assert_apicall_equals(
            plan[0],
            models.APICall(
                method_name='put_role_policy',
                params={'role_name': 'myrole',
                        'policy_name': 'myrole',
                        'policy_document': {'role': 'policy'}},
            )
        )
        assert plan[-1].value == 'myrole:arn'

    def test_can_update_file_based_policy(self):
        role = models.ManagedIAMRole(
            resource_name='resource_name',
            role_arn='myrole:arn',
            role_name='myrole',
            trust_policy={},
            policy=models.FileBasedIAMPolicy(filename='foo.json'),
        )
        self.remote_state.declare_resource_exists(role)
        self.osutils.get_file_contents.return_value = '{"iam": "policy"}'
        plan = self.determine_plan(role)
        self.assert_apicall_equals(
            plan[0],
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

    def test_can_update_with_placeholder_but_exists(self):
        role = models.ManagedIAMRole(
            resource_name='resource_name',
            role_arn=models.Placeholder.DEPLOY_STAGE,
            role_name='myrole',
            trust_policy={},
            policy=models.AutoGenIAMPolicy(document={'role': 'policy'}),
        )
        remote_role = attr.evolve(role, role_arn='myrole:arn')
        self.remote_state.declare_resource_exists(remote_role)
        plan = self.determine_plan(role)
        # We've filled in the role arn.
        assert role.role_arn == 'myrole:arn'
        self.assert_apicall_equals(
            plan[0],
            models.APICall(
                method_name='put_role_policy',
                params={'role_name': 'myrole',
                        'policy_name': 'myrole',
                        'policy_document': {'role': 'policy'}},
            )
        )


class TestPlanLambdaFunction(BasePlannerTests):
    def test_can_create_function(self):
        function = create_function_resource('function_name')
        self.remote_state.declare_no_resources_exists()
        plan = self.determine_plan(function)
        expected = models.APICall(
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
            },
        )
        self.assert_apicall_equals(plan[0], expected)

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
        }
        expected_params = dict(memory_size=256, **existing_params)
        expected = models.APICall(
            method_name='update_function',
            params=expected_params,
        )
        self.assert_apicall_equals(plan[0], expected)

    def test_can_set_variables_when_needed(self):
        function = create_function_resource('function_name')
        self.remote_state.declare_no_resources_exists()
        function.role = models.ManagedIAMRole(
            resource_name='myrole',
            role_arn=models.Placeholder.DEPLOY_STAGE,
            role_name='myrole-dev',
            trust_policy={'trust': 'policy'},
            policy=models.FileBasedIAMPolicy(filename='foo.json'),
        )
        plan = self.determine_plan(function)
        call = plan[0]
        assert call.method_name == 'create_function'
        # The params are verified in test_can_create_function,
        # we just care about how the role_arn Variable is constructed.
        role_arn = call.params['role_arn']
        assert isinstance(role_arn, Variable)
        assert role_arn.name == 'myrole-dev_role_arn'


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
        assert len(plan) == 5
        self.assert_apicall_equals(
            plan[0],
            models.APICall(
                method_name='get_or_create_rule_arn',
                params={
                    'rule_name': 'myrulename',
                    'schedule_expression': 'rate(5 minutes)',
                }
            )
        )
        assert plan[1] == models.StoreValue('rule-arn')
        self.assert_apicall_equals(
            plan[2],
            models.APICall(
                method_name='connect_rule_to_lambda',
                params={'rule_name': 'myrulename',
                        'function_arn': Variable('function_name_lambda_arn')}
            )
        )
        self.assert_apicall_equals(
            plan[3],
            models.APICall(
                method_name='add_permission_for_scheduled_event',
                params={
                    'rule_arn': Variable('rule-arn'),
                    'function_arn': Variable('function_name_lambda_arn'),
                },
            )
        )
        assert plan[4] == models.RecordResourceValue(
            resource_type='cloudwatch_event',
            resource_name='bar',
            name='rule_name',
            value='myrulename',
        )


class TestPlanRestAPI(BasePlannerTests):
    def assert_loads_needed_variables(self, plan):
        # Parse arn and store region/account id for future
        # API calls.
        assert plan[0:9] == [
            models.BuiltinFunction(
                'parse_arn', [Variable('function_name_lambda_arn')]),
            models.StoreValue('parsed_lambda_arn'),
            models.JPSearch('account_id'),
            models.StoreValue('account_id'),
            models.LoadValue('parsed_lambda_arn'),
            models.JPSearch('region'),
            models.StoreValue('region_name'),

            # Verify we copy the function arn as needed.
            models.LoadValue('function_name_lambda_arn'),
            models.StoreValue('api_handler_lambda_arn'),
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
        assert plan[9:] == [
            models.APICall(
                method_name='import_rest_api',
                params={'swagger_document': {'swagger': '2.0'}},
            ),
            models.StoreValue(name='rest_api_id'),
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
                method_name='add_permission_for_apigateway_if_needed',
                params={
                    'function_name': 'appname-dev-function_name',
                    'region_name': Variable('region_name'),
                    'account_id': Variable('account_id'),
                    'rest_api_id': Variable('rest_api_id'),
                }
            )
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
        assert plan[9:] == [
            models.Push('my_rest_api_id'),
            models.StoreValue(name='rest_api_id'),
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
                method_name='add_permission_for_apigateway_if_needed',
                params={'function_name': 'appname-dev-function_name',
                        'region_name': Variable('region_name'),
                        'account_id': Variable('account_id'),
                        'rest_api_id': Variable('rest_api_id')},
            ),
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
        role = models.ManagedIAMRole('my_role', role_arn=None,
                                     role_name='app-dev', trust_policy={},
                                     policy=None)
        assert self.remote_state.resource_exists(role)
        self.client.get_role_arn_for_name.assert_called_with('app-dev')

    def test_role_does_not_exist(self):
        client = self.client
        client.get_role_arn_for_name.side_effect = ResourceDoesNotExistError()
        role = models.ManagedIAMRole('my_role', role_arn=None,
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

    def test_remote_model_exists(self):
        role = models.ManagedIAMRole(
            resource_name='my_role',
            role_arn=None,
            role_name='app-dev',
            trust_policy={},
            policy=None
        )
        self.client.get_role.return_value = {
            'AssumeRolePolicyDocument': {'trust': 'policy'},
            'RoleId': 'roleid',
            'RoleName': 'app-dev',
            'Arn': 'my_role_arn'
        }
        # We don't fill in the policy document because that's an extra
        # API call and we don't do any smart diffing with it.
        remote_model = self.remote_state.get_remote_model(role)
        remote_model.role_arn = 'my_role_arn'
        remote_model.trust_policy = {'trust': 'policy'}
        self.client.get_role.assert_called_with('app-dev')

    def test_remote_model_does_not_exist(self):
        client = self.client
        client.get_role_arn_for_name.side_effect = ResourceDoesNotExistError()
        role = models.ManagedIAMRole(resource_name='my_role', role_arn=None,
                                     role_name='app-dev', trust_policy={},
                                     policy=None)
        assert self.remote_state.get_remote_model(role) is None

    def test_exists_check_is_cached(self):
        function = create_function_resource('function-name')
        self.client.lambda_function_exists.return_value = True
        assert self.remote_state.resource_exists(function)
        # Now if we call this method repeatedly we should only invoke
        # the underlying client method once.  Subsequent calls are cached.
        assert self.remote_state.resource_exists(function)
        assert self.remote_state.resource_exists(function)

        assert self.client.lambda_function_exists.call_count == 1

    def test_rest_api_exists_no_deploy(self):
        rest_api = self.create_rest_api_model()
        remote_state = RemoteState(
            self.client, None)
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
            self.client, DeployedResources2(deployed_resources))
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
            self.client, DeployedResources2(deployed_resources))
        assert not remote_state.resource_exists(rest_api)
        self.client.rest_api_exists.assert_called_with('my_rest_api_id')

    def test_can_get_deployed_values(self):
        remote_state = RemoteState(
            self.client, DeployedResources2({'resources': [
                {'name': 'rest_api', 'rest_api_id': 'foo'}]})
        )
        rest_api = self.create_rest_api_model()
        values = remote_state.resource_deployed_values(rest_api)
        assert values == {'name': 'rest_api', 'rest_api_id': 'foo'}

    def test_value_error_raised_on_no_deployed_values(self):
        remote_state = RemoteState(self.client, deployed_resources=None)
        rest_api = self.create_rest_api_model()
        with pytest.raises(ValueError):
            remote_state.resource_deployed_values(rest_api)


class TestUnreferencedResourcePlanner(object):
    def setup_method(self):
        pass

    @pytest.fixture
    def sweeper(self):
        return UnreferencedResourcePlanner()

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

    def test_noop_when_all_resources_accounted_for(self, sweeper,
                                                   function_resource):
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
        sweeper.execute(plan, config)
        # We shouldn't add anything to the list.
        assert plan == original_plan

    def test_will_delete_unreferenced_resource(self, sweeper):
        plan = []
        deployed = self.one_deployed_lambda_function()
        config = FakeConfig(deployed)
        sweeper.execute(plan, config)
        assert len(plan) == 1
        assert plan[0].method_name == 'delete_function'
        assert plan[0].params == {'function_name': 'arn'}

    def test_supports_multiple_unreferenced_and_unchanged(self, sweeper):
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
        sweeper.execute(plan, config)
        assert len(plan) == 3
        assert plan[2].method_name == 'delete_function'
        assert plan[2].params == {'function_name': 'third_arn'}

    def test_can_delete_iam_role(self, sweeper):
        plan = []
        deployed = {
            'resources': [{
                'name': 'myrole',
                'resource_type': 'iam_role',
                'role_arn': 'arn:role/myrole',
            }]
        }
        config = FakeConfig(deployed)
        sweeper.execute(plan, config)
        assert len(plan) == 1
        assert plan[0].method_name == 'delete_role'
        assert plan[0].params == {'name': 'myrole'}

    def test_correct_deletion_order_for_dependencies(self, sweeper):
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
                    'role_arn': 'arn:role/myrole',
                },
                {
                    'name': 'myrole2',
                    'resource_type': 'iam_role',
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
        sweeper.execute(plan, config)
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

    def test_can_delete_scheduled_event(self, sweeper):
        plan = []
        deployed = {
            'resources': [{
                'name': 'index-event',
                'resource_type': 'cloudwatch_event',
                'rule_name': 'app-dev-index-event',
            }]
        }
        config = FakeConfig(deployed)
        sweeper.execute(plan, config)
        assert plan == [
            models.APICall(
                method_name='delete_rule',
                params={'rule_name': 'app-dev-index-event'},
            )
        ]

    def test_can_delete_rest_api(self, sweeper):
        plan = []
        deployed = {
            'resources': [{
                'name': 'rest_api',
                'rest_api_id': 'my_rest_api_id',
                'resource_type': 'rest_api',
            }]
        }
        config = FakeConfig(deployed)
        sweeper.execute(plan, config)
        assert plan == [
            models.APICall(
                method_name='delete_rest_api',
                params={'rest_api_id': 'my_rest_api_id'},
            )
        ]
