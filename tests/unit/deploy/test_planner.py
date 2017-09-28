import mock

import attr

from chalice.awsclient import TypedAWSClient, ResourceDoesNotExistError
from chalice.deploy import models
from chalice.utils import OSUtils
from chalice.deploy.planner import PlanStage, Variable, RemoteState


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


class InMemoryRemoteState(object):
    def __init__(self, known_resources=None):
        if known_resources is None:
            known_resources = {}
        self.known_resources = known_resources

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
        assert expected.target_variable == actual_api_call.target_variable
        assert expected.resource == actual_api_call.resource

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
        assert len(plan) == 1
        expected = models.APICall(
            method_name='create_role',
            params={'name': 'myrole',
                    'trust_policy': {'trust': 'policy'},
                    'policy': {'iam': 'policy'}},
            target_variable='myrole_role_arn',
            resource=resource
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
        assert len(plan) == 1
        expected = models.APICall(
            method_name='create_role',
            params={'name': 'myrole',
                    'trust_policy': {'trust': 'policy'},
                    'policy': {'iam': 'policy'}},
            target_variable='myrole_role_arn',
            resource=resource,
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
        assert len(plan) == 1
        self.assert_apicall_equals(
            plan[0],
            models.APICall(
                method_name='put_role_policy',
                params={'role_name': 'myrole',
                        'policy_name': 'myrole',
                        'policy_document': {'role': 'policy'}},
                resource=role,
            )
        )

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
        assert len(plan) == 1
        self.assert_apicall_equals(
            plan[0],
            models.APICall(
                method_name='put_role_policy',
                params={'role_name': 'myrole',
                        'policy_name': 'myrole',
                        'policy_document': {'iam': 'policy'}},
                resource=role,
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
        assert len(plan) == 1
        # We've filled in the role arn.
        assert role.role_arn == 'myrole:arn'
        self.assert_apicall_equals(
            plan[0],
            models.APICall(
                method_name='put_role_policy',
                params={'role_name': 'myrole',
                        'policy_name': 'myrole',
                        'policy_document': {'role': 'policy'}},
                resource=role,
            )
        )


class TestPlanLambdaFunction(BasePlannerTests):
    def test_can_create_function(self):
        function = create_function_resource('function_name')
        self.remote_state.declare_no_resources_exists()
        plan = self.determine_plan(function)
        assert len(plan) == 1
        expected = models.APICall(
            method_name='create_function',
            target_variable='function_name_lambda_arn',
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
            resource=function,
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
        assert len(plan) == 1
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
            # We don't need to set a target variable because the
            # function already exists and we know the arn.
            target_variable=None,
            resource=function,
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
        assert len(plan) == 1
        call = plan[0]
        assert call.method_name == 'create_function'
        assert call.target_variable == 'function_name_lambda_arn'
        assert call.resource == function
        # The params are verified in test_can_create_function,
        # we just care about how the role_arn Variable is constructed.
        role_arn = call.params['role_arn']
        assert isinstance(role_arn, Variable)
        assert role_arn.name == 'myrole-dev_role_arn'


class TestRemoteState(object):
    def setup_method(self):
        self.client = mock.Mock(spec=TypedAWSClient)
        self.remote_state = RemoteState(self.client)

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
