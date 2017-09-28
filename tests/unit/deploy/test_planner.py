import mock

from chalice.deploy import models
from chalice.awsclient import TypedAWSClient, ResourceDoesNotExistError
from chalice.utils import OSUtils
from chalice.deploy.planner import PlanStage, Variable


class BasePlannerTests(object):
    def setup_method(self):
        self.client = mock.Mock(spec=TypedAWSClient)
        self.osutils = mock.Mock(spec=OSUtils)

    def create_function_resource(self, name, function_name=None,
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


class TestPlanStageCreate(BasePlannerTests):
    def test_can_plan_for_iam_role_creation(self):
        self.client.get_role_arn_for_name.side_effect = \
            ResourceDoesNotExistError()
        planner = PlanStage(self.client, self.osutils)
        resource = models.ManagedIAMRole(
            resource_name='default-role',
            role_arn=models.Placeholder.DEPLOY_STAGE,
            role_name='myrole',
            trust_policy={'trust': 'policy'},
            policy=models.AutoGenIAMPolicy(document={'iam': 'policy'}),
        )
        plan = planner.execute([resource])
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
        self.client.get_role_arn_for_name.side_effect = \
                ResourceDoesNotExistError
        resource = models.ManagedIAMRole(
            resource_name='default-role',
            role_arn=models.Placeholder.DEPLOY_STAGE,
            role_name='myrole',
            trust_policy={'trust': 'policy'},
            policy=models.FileBasedIAMPolicy(filename='foo.json'),
        )
        self.osutils.get_file_contents.return_value = '{"iam": "policy"}'
        planner = PlanStage(self.client, self.osutils)
        plan = planner.execute([resource])
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

    def test_can_create_function(self):
        self.client.lambda_function_exists.return_value = False
        function = self.create_function_resource('function_name')
        planner = PlanStage(self.client, self.osutils)
        plan = planner.execute([function])
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

    def test_can_create_plan_for_managed_role(self):
        self.client.lambda_function_exists.return_value = False
        self.client.get_role_arn_for_name.side_effect = \
            ResourceDoesNotExistError
        function = self.create_function_resource('function_name')
        function.role = models.ManagedIAMRole(
            resource_name='myrole',
            role_arn=models.Placeholder.DEPLOY_STAGE,
            role_name='myrole-dev',
            trust_policy={'trust': 'policy'},
            policy=models.FileBasedIAMPolicy(filename='foo.json'),
        )
        planner = PlanStage(self.client, self.osutils)
        plan = planner.execute([function])
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


class TestPlanStageUpdate(BasePlannerTests):
    def test_can_update_lambda_function_code(self):
        self.client.lambda_function_exists.return_value = True
        function = self.create_function_resource('function_name')
        # Now let's change the memory size and ensure we
        # get an update.
        function.memory_size = 256
        planner = PlanStage(self.client, self.osutils)
        plan = planner.execute([function])
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

    def test_can_update_managed_role(self):
        self.client.get_role_arn_for_name.return_value = 'myrole:arn'
        role = models.ManagedIAMRole(
            resource_name='resource_name',
            role_arn='myrole:arn',
            role_name='myrole',
            trust_policy={},
            policy=models.AutoGenIAMPolicy(document={'role': 'policy'}),
        )
        planner = PlanStage(self.client, self.osutils)
        plan = planner.execute([role])
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
        self.client.get_role_arn_for_name.return_value = 'myrole:arn'
        role = models.ManagedIAMRole(
            resource_name='resource_name',
            role_arn='myrole:arn',
            role_name='myrole',
            trust_policy={},
            policy=models.FileBasedIAMPolicy(filename='foo.json'),
        )
        self.osutils.get_file_contents.return_value = '{"iam": "policy"}'
        planner = PlanStage(self.client, self.osutils)
        plan = planner.execute([role])
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
        planner = PlanStage(self.client, self.osutils)
        plan = planner.execute([role])
        assert plan == []

    def test_can_update_with_placeholder_but_exists(self):
        self.client.get_role_arn_for_name.return_value = 'myrole:arn'
        role = models.ManagedIAMRole(
            resource_name='resource_name',
            role_arn=models.Placeholder.DEPLOY_STAGE,
            role_name='myrole',
            trust_policy={},
            policy=models.AutoGenIAMPolicy(document={'role': 'policy'}),
        )
        planner = PlanStage(self.client, self.osutils)
        plan = planner.execute([role])
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
