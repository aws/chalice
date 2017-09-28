from pytest import fixture
import mock

from chalice.deploy import models
from chalice.config import Config
from chalice.awsclient import TypedAWSClient, ResourceDoesNotExistError
from chalice.utils import OSUtils
from chalice.deploy.planner import PlanStage, Variable


@fixture
def mock_client():
    return mock.Mock(spec=TypedAWSClient)


@fixture
def mock_osutils():
    return mock.Mock(spec=OSUtils)


def create_function_resource(name):
    return models.LambdaFunction(
        resource_name=name,
        function_name='appname-dev-%s' % name,
        environment_variables={},
        runtime='python2.7',
        handler='app.app',
        tags={},
        timeout=60,
        memory_size=128,
        deployment_package=models.DeploymentPackage(filename='foo'),
        role=models.PreCreatedIAMRole(role_arn='role:arn')
    )


class TestPlanStageCreate(object):
    def test_can_plan_for_iam_role_creation(self, mock_client, mock_osutils):
        mock_client.get_role_arn_for_name.side_effect = \
            ResourceDoesNotExistError()
        planner = PlanStage(mock_client, mock_osutils)
        resource = models.ManagedIAMRole(
            resource_name='default-role',
            role_arn=models.Placeholder.DEPLOY_STAGE,
            role_name='myrole',
            trust_policy={'trust': 'policy'},
            policy=models.AutoGenIAMPolicy(document={'iam': 'policy'}),
        )
        plan = planner.execute(Config.create(), [resource])
        assert len(plan) == 1
        api_call = plan[0]
        assert api_call.method_name == 'create_role'
        assert api_call.params == {'name': 'myrole',
                                   'trust_policy': {'trust': 'policy'},
                                   'policy': {'iam': 'policy'}}
        assert api_call.target_variable == 'myrole_role_arn'
        assert api_call.resource == resource

    def test_can_create_plan_for_filebased_role(self, mock_client,
                                                mock_osutils):
        mock_client.get_role_arn_for_name.side_effect = \
                ResourceDoesNotExistError
        resource = models.ManagedIAMRole(
            resource_name='default-role',
            role_arn=models.Placeholder.DEPLOY_STAGE,
            role_name='myrole',
            trust_policy={'trust': 'policy'},
            policy=models.FileBasedIAMPolicy(filename='foo.json'),
        )
        mock_osutils.get_file_contents.return_value = '{"iam": "policy"}'
        planner = PlanStage(mock_client, mock_osutils)
        plan = planner.execute(Config.create(project_dir='.'), [resource])
        assert len(plan) == 1
        api_call = plan[0]
        assert api_call.method_name == 'create_role'
        assert api_call.params == {'name': 'myrole',
                                   'trust_policy': {'trust': 'policy'},
                                   'policy': {'iam': 'policy'}}
        assert api_call.target_variable == 'myrole_role_arn'
        assert api_call.resource == resource

    def test_can_create_function(self, mock_client, mock_osutils):
        mock_client.lambda_function_exists.return_value = False
        function = create_function_resource('function_name')
        planner = PlanStage(mock_client, mock_osutils)
        plan = planner.execute(Config.create(), [function])
        assert len(plan) == 1
        call = plan[0]
        assert call.method_name == 'create_function'
        assert call.target_variable == 'function_name_lambda_arn'
        assert call.params == {
            'function_name': 'appname-dev-function_name',
            'role_arn': 'role:arn',
            'zip_contents': mock.ANY,
            'runtime': 'python2.7',
            'handler': 'app.app',
            'environment_variables': {},
            'tags': {},
            'timeout': 60,
            'memory_size': 128,
        }
        assert call.resource == function

    def test_can_create_plan_for_managed_role(self, mock_client, mock_osutils):
        mock_client.lambda_function_exists.return_value = False
        mock_client.get_role_arn_for_name.side_effect = \
            ResourceDoesNotExistError
        function = create_function_resource('function_name')
        function.role = models.ManagedIAMRole(
            resource_name='myrole',
            role_arn=models.Placeholder.DEPLOY_STAGE,
            role_name='myrole-dev',
            trust_policy={'trust': 'policy'},
            policy=models.FileBasedIAMPolicy(filename='foo.json'),
        )
        planner = PlanStage(mock_client, mock_osutils)
        plan = planner.execute(Config.create(), [function])
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


class TestPlanStageUpdate(object):
    def test_can_update_lambda_function_code(self, mock_client, mock_osutils):
        mock_client.lambda_function_exists.return_value = True
        function = create_function_resource('function_name')
        # Now let's change the memory size and ensure we
        # get an update.
        function.memory_size = 256
        planner = PlanStage(mock_client, mock_osutils)
        plan = planner.execute(Config.create(), [function])
        assert len(plan) == 1
        call = plan[0]
        assert call.method_name == 'update_function'
        assert call.resource == function
        # We don't need to set a target variable because the
        # function already exists and we know the arn.
        assert call.target_variable is None
        existing_params = {
            'function_name': 'appname-dev-function_name',
            'role_arn': 'role:arn',
            'zip_contents': mock.ANY,
            'runtime': 'python2.7',
            'environment_variables': {},
            'tags': {},
            'timeout': 60,
        }
        expected = dict(memory_size=256, **existing_params)
        assert call.params == expected

    def test_can_update_managed_role(self, mock_client, mock_osutils):
        mock_client.get_role_arn_for_name.return_value = 'myrole:arn'
        role = models.ManagedIAMRole(
            resource_name='resource_name',
            role_arn='myrole:arn',
            role_name='myrole',
            trust_policy={},
            policy=models.AutoGenIAMPolicy(document={'role': 'policy'}),
        )
        planner = PlanStage(mock_client, mock_osutils)
        plan = planner.execute(Config.create(), [role])
        assert len(plan) == 2
        delete_call = plan[0]
        assert delete_call.method_name == 'delete_role_policy'
        assert delete_call.params == {'role_name': 'myrole',
                                      'policy_name': 'myrole'}
        assert delete_call.resource == role

        update_call = plan[1]
        assert update_call.method_name == 'put_role_policy'
        assert update_call.params == {'role_name': 'myrole',
                                      'policy_name': 'myrole',
                                      'policy_document': {'role': 'policy'}}
        assert update_call.resource == role

    def test_can_update_file_based_policy(self, mock_client, mock_osutils):
        mock_client.get_role_arn_for_name.return_value = 'myrole:arn'
        role = models.ManagedIAMRole(
            resource_name='resource_name',
            role_arn='myrole:arn',
            role_name='myrole',
            trust_policy={},
            policy=models.FileBasedIAMPolicy(filename='foo.json'),
        )
        mock_osutils.get_file_contents.return_value = '{"iam": "policy"}'
        planner = PlanStage(mock_client, mock_osutils)
        plan = planner.execute(Config.create(), [role])
        assert len(plan) == 2
        delete_call = plan[0]
        assert delete_call.method_name == 'delete_role_policy'
        assert delete_call.params == {'role_name': 'myrole',
                                      'policy_name': 'myrole'}
        assert delete_call.resource == role

        update_call = plan[1]
        assert update_call.method_name == 'put_role_policy'
        assert update_call.params == {'role_name': 'myrole',
                                      'policy_name': 'myrole',
                                      'policy_document': {'iam': 'policy'}}
        assert update_call.resource == role

    def test_no_update_for_non_managed_role(self):
        role = models.PreCreatedIAMRole(role_arn='role:arn')
        planner = PlanStage(mock_client, mock_osutils)
        plan = planner.execute(Config.create(), [role])
        assert plan == []

    def test_can_update_with_placeholder_but_exists(self, mock_client,
                                                    mock_osutils):
        mock_client.get_role_arn_for_name.return_value = 'myrole:arn'
        role = models.ManagedIAMRole(
            resource_name='resource_name',
            role_arn=models.Placeholder.DEPLOY_STAGE,
            role_name='myrole',
            trust_policy={},
            policy=models.AutoGenIAMPolicy(document={'role': 'policy'}),
        )
        planner = PlanStage(mock_client, mock_osutils)
        plan = planner.execute(Config.create(), [role])
        assert len(plan) == 2
        delete_call = plan[0]
        assert delete_call.method_name == 'delete_role_policy'
        assert delete_call.params == {'role_name': 'myrole',
                                      'policy_name': 'myrole'}
        assert delete_call.resource == role

        update_call = plan[1]
        assert update_call.method_name == 'put_role_policy'
        assert update_call.params == {'role_name': 'myrole',
                                      'policy_name': 'myrole',
                                      'policy_document': {'role': 'policy'}}
        assert update_call.resource == role

        assert role.role_arn == 'myrole:arn'
