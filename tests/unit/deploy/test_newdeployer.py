import os
import unittest

from attr import attrs, attrib
import pytest
from pytest import fixture
import mock
import botocore.session

from chalice.awsclient import TypedAWSClient
from chalice.utils import OSUtils, UI, serialize_to_json
from chalice.deploy import models
from chalice.deploy import packager
from chalice.config import Config
from chalice.app import Chalice
from chalice.deploy.newdeployer import create_default_deployer
from chalice.deploy.newdeployer import create_deletion_deployer
from chalice.deploy.newdeployer import Deployer
from chalice.deploy.newdeployer import BaseDeployStep
from chalice.deploy.newdeployer import BuildStage
from chalice.deploy.newdeployer import DependencyBuilder
from chalice.deploy.newdeployer import ApplicationGraphBuilder
from chalice.deploy.newdeployer import InjectDefaults, DeploymentPackager
from chalice.deploy.newdeployer import PolicyGenerator, SwaggerBuilder
from chalice.deploy.newdeployer import VariableResolver
from chalice.deploy.newdeployer import TemplatedSwaggerGenerator
from chalice.deploy.newdeployer import ResultsRecorder
from chalice.deploy.swagger import SwaggerGenerator
from chalice.deploy.planner import PlanStage, Variable
from chalice.deploy.planner import UnreferencedResourcePlanner, StringFormat
from chalice.deploy.newdeployer import Executor
from chalice.deploy.newdeployer import UnresolvedValueError
from chalice.deploy.models import APICall, StoreValue, RecordResourceValue
from chalice.deploy.models import RecordResourceVariable
from chalice.deploy.models import JPSearch, BuiltinFunction
from chalice.policy import AppPolicyGenerator
from chalice.constants import LAMBDA_TRUST_POLICY


@attrs
class FooResource(models.Model):
    name = attrib()
    leaf = attrib()

    def dependencies(self):
        if not isinstance(self.leaf, list):
            return [self.leaf]
        return self.leaf


@attrs
class LeafResource(models.Model):
    name = attrib()


@fixture
def lambda_app():
    app = Chalice('lambda-only')

    @app.lambda_function()
    def foo(event, context):
        return {}

    return app


@fixture
def scheduled_event_app():
    app = Chalice('scheduled-event')

    @app.schedule('rate(5 minutes)')
    def foo(event):
        return {}

    return app


@fixture
def rest_api_app():
    app = Chalice('rest-api')

    @app.route('/')
    def index():
        return {}

    return app


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


class TestDependencyBuilder(object):
    def test_can_build_resource_with_single_dep(self):
        role = models.PreCreatedIAMRole(role_arn='foo')
        app = models.Application(stage='dev', resources=[role])

        dep_builder = DependencyBuilder()
        deps = dep_builder.build_dependencies(app)
        assert deps == [role]

    def test_can_build_resource_with_dag_deps(self):
        shared_leaf = LeafResource(name='leaf-resource')
        first_parent = FooResource(name='first', leaf=shared_leaf)
        second_parent = FooResource(name='second', leaf=shared_leaf)
        app = models.Application(
            stage='dev', resources=[first_parent, second_parent])

        dep_builder = DependencyBuilder()
        deps = dep_builder.build_dependencies(app)
        assert deps == [shared_leaf, first_parent, second_parent]

    def test_is_first_element_in_list(self):
        shared_leaf = LeafResource(name='leaf-resource')
        first_parent = FooResource(name='first', leaf=shared_leaf)
        app = models.Application(
            stage='dev', resources=[first_parent, shared_leaf],
        )
        dep_builder = DependencyBuilder()
        deps = dep_builder.build_dependencies(app)
        assert deps == [shared_leaf, first_parent]

    def test_can_compares_with_identity_not_equality(self):
        first_leaf = LeafResource(name='same-name')
        second_leaf = LeafResource(name='same-name')
        first_parent = FooResource(name='first', leaf=first_leaf)
        second_parent = FooResource(name='second', leaf=second_leaf)
        app = models.Application(
            stage='dev', resources=[first_parent, second_parent])

        dep_builder = DependencyBuilder()
        deps = dep_builder.build_dependencies(app)
        assert deps == [first_leaf, first_parent, second_leaf, second_parent]

    def test_no_duplicate_depedencies(self):
        leaf = LeafResource(name='leaf')
        second_parent = FooResource(name='second', leaf=leaf)
        first_parent = FooResource(name='first', leaf=[leaf, second_parent])
        app = models.Application(
            stage='dev', resources=[first_parent])

        dep_builder = DependencyBuilder()
        deps = dep_builder.build_dependencies(app)
        assert deps == [leaf, second_parent, first_parent]


class TestApplicationGraphBuilder(object):

    def create_config(self, app, app_name='lambda-only',
                      iam_role_arn=None, policy_file=None,
                      api_gateway_stage='api',
                      autogen_policy=False):
        kwargs = {
            'chalice_app': app,
            'app_name': app_name,
            'project_dir': '.',
            'api_gateway_stage': api_gateway_stage,
        }
        if iam_role_arn is not None:
            # We want to use an existing role.
            # This will skip all the autogen-policy
            # and role creation.
            kwargs['manage_iam_role'] = False
            kwargs['iam_role_arn'] = 'role:arn'
        elif policy_file is not None:
            # Otherwise this setting is when a user wants us to
            # manage the role, but they've written a policy file
            # they'd like us to use.
            kwargs['autogen_policy'] = False
            kwargs['iam_policy_file'] = policy_file
        elif autogen_policy:
            kwargs['autogen_policy'] = True
        config = Config.create(**kwargs)
        return config

    def test_can_build_single_lambda_function_app(self, lambda_app):
        # This is the simplest configuration we can get.
        builder = ApplicationGraphBuilder()
        config = self.create_config(lambda_app, iam_role_arn='role:arn')
        application = builder.build(config, stage_name='dev')
        # The top level resource is always an Application.
        assert isinstance(application, models.Application)
        assert len(application.resources) == 1
        assert application.resources[0] == models.LambdaFunction(
            resource_name='foo',
            function_name='lambda-only-dev-foo',
            environment_variables={},
            runtime=config.lambda_python_version,
            handler='app.foo',
            tags=config.tags,
            timeout=None,
            memory_size=None,
            deployment_package=models.DeploymentPackage(
                models.Placeholder.BUILD_STAGE),
            role=models.PreCreatedIAMRole('role:arn'),
        )

    def test_multiple_lambda_functions_share_role_and_package(self,
                                                              lambda_app):
        # We're going to add another lambda_function to our app.
        @lambda_app.lambda_function()
        def bar(event, context):
            return {}

        builder = ApplicationGraphBuilder()
        config = self.create_config(lambda_app, iam_role_arn='role:arn')
        application = builder.build(config, stage_name='dev')
        assert len(application.resources) == 2
        # The lambda functions by default share the same role
        assert application.resources[0].role == application.resources[1].role
        # Not just in equality but the exact same role objects.
        assert application.resources[0].role is application.resources[1].role
        # And all lambda functions share the same deployment package.
        assert (application.resources[0].deployment_package ==
                application.resources[1].deployment_package)

    def test_autogen_policy_for_function(self, lambda_app):
        # This test is just a sanity test that verifies all the params
        # for an ManagedIAMRole.  The various combinations for role
        # configuration is all tested via RoleTestCase.
        config = self.create_config(lambda_app, autogen_policy=True)
        builder = ApplicationGraphBuilder()
        application = builder.build(config, stage_name='dev')
        function = application.resources[0]
        role = function.role
        # We should have linked a ManagedIAMRole
        assert isinstance(role, models.ManagedIAMRole)
        assert role == models.ManagedIAMRole(
            resource_name='default-role',
            role_name='lambda-only-dev',
            trust_policy=LAMBDA_TRUST_POLICY,
            policy=models.AutoGenIAMPolicy(models.Placeholder.BUILD_STAGE),
        )

    def test_scheduled_event_models(self, scheduled_event_app):
        config = self.create_config(scheduled_event_app,
                                    app_name='scheduled-event',
                                    autogen_policy=True)
        builder = ApplicationGraphBuilder()
        application = builder.build(config, stage_name='dev')
        assert len(application.resources) == 1
        event = application.resources[0]
        assert isinstance(event, models.ScheduledEvent)
        assert event.resource_name == 'foo-event'
        assert event.rule_name == 'scheduled-event-dev-foo-event'
        assert isinstance(event.lambda_function, models.LambdaFunction)
        assert event.lambda_function.resource_name == 'foo'

    def test_can_build_rest_api(self, rest_api_app):
        config = self.create_config(rest_api_app,
                                    app_name='rest-api-app',
                                    autogen_policy=True)
        builder = ApplicationGraphBuilder()
        application = builder.build(config, stage_name='dev')
        assert len(application.resources) == 1
        rest_api = application.resources[0]
        assert isinstance(rest_api, models.RestAPI)
        assert rest_api.resource_name == 'rest_api'
        assert rest_api.api_gateway_stage == 'api'
        assert rest_api.lambda_function.resource_name == 'api_handler'
        assert rest_api.lambda_function.function_name == 'rest-api-app-dev'
        # The swagger document is validated elsewhere so we just
        # make sure it looks right.
        assert rest_api.swagger_doc == models.Placeholder.BUILD_STAGE

    def test_can_build_rest_api_with_authorizer(self, rest_api_app):
        @rest_api_app.authorizer()
        def my_auth(auth_request):
            pass

        @rest_api_app.route('/auth', authorizer=my_auth)
        def needs_auth():
            return {'foo': 'bar'}

        config = self.create_config(rest_api_app,
                                    app_name='rest-api-app',
                                    autogen_policy=True)
        builder = ApplicationGraphBuilder()
        application = builder.build(config, stage_name='dev')
        rest_api = application.resources[0]
        assert len(rest_api.authorizers) == 1
        assert isinstance(rest_api.authorizers[0], models.LambdaFunction)


class RoleTestCase(object):
    def __init__(self, given, roles, app_name='appname'):
        self.given = given
        self.roles = roles
        self.app_name = app_name

    def build(self):
        app = Chalice(self.app_name)

        for name in self.given:
            def foo(event, context):
                return {}
            foo.__name__ = name
            app.lambda_function(name)(foo)

        user_provided_params = {
            'chalice_app': app,
            'app_name': self.app_name,
            'project_dir': '.',
        }
        lambda_functions = {}
        for key, value in self.given.items():
            lambda_functions[key] = value
        config_from_disk = {
            'stages': {
                'dev': {
                    'lambda_functions': lambda_functions,
                }
            }
        }
        config = Config(chalice_stage='dev',
                        user_provided_params=user_provided_params,
                        config_from_disk=config_from_disk)
        return app, config

    def assert_required_roles_created(self, application):
        resources = application.resources
        assert len(resources) == len(self.given)
        functions_by_name = {f.function_name: f for f in resources}
        # Roles that have the same name/arn should be the same
        # object.  If we encounter a role that's already in
        # roles_by_identifier, we'll verify that it's the exact same object.
        roles_by_identifier = {}
        for function_name, expected in self.roles.items():
            full_name = 'appname-dev-%s' % function_name
            assert full_name in functions_by_name
            actual_role = functions_by_name[full_name].role
            expectations = self.roles[function_name]
            if not expectations.get('managed_role', True):
                actual_role_arn = actual_role.role_arn
                assert isinstance(actual_role, models.PreCreatedIAMRole)
                assert expectations['iam_role_arn'] == actual_role_arn
                if actual_role_arn in roles_by_identifier:
                    assert roles_by_identifier[actual_role_arn] is actual_role
                roles_by_identifier[actual_role_arn] = actual_role
                continue
            actual_name = actual_role.role_name
            assert expectations['name'] == actual_name
            if actual_name in roles_by_identifier:
                assert roles_by_identifier[actual_name] is actual_role
            roles_by_identifier[actual_name] = actual_role
            is_autogenerated = expectations.get('autogenerated', False)
            policy_file = expectations.get('policy_file')
            if is_autogenerated:
                assert isinstance(actual_role, models.ManagedIAMRole)
                assert isinstance(actual_role.policy, models.AutoGenIAMPolicy)
            if policy_file is not None and not is_autogenerated:
                assert isinstance(actual_role, models.ManagedIAMRole)
                assert isinstance(actual_role.policy,
                                  models.FileBasedIAMPolicy)
                assert actual_role.policy.filename == os.path.join(
                    '.', '.chalice', expectations['policy_file'])


# How to read these tests:
# 'given' is a mapping of lambda function name to config values.
# 'roles' is a mapping of lambda function to expected attributes
# of the role associated with the given function.
# The first test case is explained in more detail as an example.
ROLE_TEST_CASES = [
    # Default case, we use the shared 'appname-dev' role.
    RoleTestCase(
        # Given we have a lambda function in our app.py named 'a',
        # and we have our config file state that the 'a' function
        # should have an autogen'd policy,
        given={'a': {'autogen_policy': True}},
        # then we expect the IAM role associated with the lambda
        # function 'a' should be named 'appname-dev', and it should
        # be an autogenerated role/policy.
        roles={'a': {'name': 'appname-dev', 'autogenerated': True}}),
    # If you specify an explicit policy, we generate a function
    # specific role.
    RoleTestCase(
        given={'a': {'autogen_policy': False,
                     'iam_policy_file': 'mypolicy.json'}},
        roles={'a': {'name': 'appname-dev-a',
                     'autogenerated': False,
                     'policy_file': 'mypolicy.json'}}),
    # Multiple lambda functions that use autogen policies share
    # the same 'appname-dev' role.
    RoleTestCase(
        given={'a': {'autogen_policy': True},
               'b': {'autogen_policy': True}},
        roles={'a': {'name': 'appname-dev'},
               'b': {'name': 'appname-dev'}}),
    # Multiple lambda functions with separate policies result
    # in separate roles.
    RoleTestCase(
        given={'a': {'autogen_policy': False,
                     'iam_policy_file': 'a.json'},
               'b': {'autogen_policy': False,
                     'iam_policy_file': 'b.json'}},
        roles={'a': {'name': 'appname-dev-a',
                     'autogenerated': False,
                     'policy_file': 'a.json'},
               'b': {'name': 'appname-dev-b',
                     'autogenerated': False,
                     'policy_file': 'b.json'}}),
    # You can mix autogen and explicit policy files.  Autogen will
    # always use the '{app}-{stage}' role.
    RoleTestCase(
        given={'a': {'autogen_policy': True},
               'b': {'autogen_policy': False,
                     'iam_policy_file': 'b.json'}},
        roles={'a': {'name': 'appname-dev',
                     'autogenerated': True},
               'b': {'name': 'appname-dev-b',
                     'autogenerated': False,
                     'policy_file': 'b.json'}}),
    # Default location if no policy file is given is
    # policy-dev.json
    RoleTestCase(
        given={'a': {'autogen_policy': False}},
        roles={'a': {'name': 'appname-dev-a',
                     'autogenerated': False,
                     'policy_file': 'policy-dev.json'}}),
    # As soon as autogen_policy is false, we will *always*
    # create a function specific role.
    RoleTestCase(
        given={'a': {'autogen_policy': False},
               'b': {'autogen_policy': True}},
        roles={'a': {'name': 'appname-dev-a',
                     'autogenerated': False,
                     'policy_file': 'policy-dev.json'},
               'b': {'name': 'appname-dev'}}),
    RoleTestCase(
        given={'a': {'manage_iam_role': False, 'iam_role_arn': 'role:arn'}},
        # 'managed_role' will verify the associated role is a
        # models.PreCreatedIAMRoleType with the provided iam_role_arn.
        roles={'a': {'managed_role': False, 'iam_role_arn': 'role:arn'}}),
    # Verify that we can use the same non-managed role for multiple
    # lambda functions.
    RoleTestCase(
        given={'a': {'manage_iam_role': False, 'iam_role_arn': 'role:arn'},
               'b': {'manage_iam_role': False, 'iam_role_arn': 'role:arn'}},
        roles={'a': {'managed_role': False, 'iam_role_arn': 'role:arn'},
               'b': {'managed_role': False, 'iam_role_arn': 'role:arn'}}),
    RoleTestCase(
        given={'a': {'manage_iam_role': False, 'iam_role_arn': 'role:arn'},
               'b': {'autogen_policy': True}},
        roles={'a': {'managed_role': False, 'iam_role_arn': 'role:arn'},
               'b': {'name': 'appname-dev', 'autogenerated': True}}),

    # Functions that mix all four options:
    RoleTestCase(
        # 2 functions with autogen'd policies.
        given={
            'a': {'autogen_policy': True},
            'b': {'autogen_policy': True},
            # 2 functions with various iam role arns.
            'c': {'manage_iam_role': False, 'iam_role_arn': 'role:arn'},
            'd': {'manage_iam_role': False, 'iam_role_arn': 'role:arn2'},
            # A function with a default filename for a policy.
            'e': {'autogen_policy': False},
            # Even though this uses the same policy as 'e', we will
            # still create a new role.  This could be optimized in the
            # future.
            'f': {'autogen_policy': False},
            # And finally 2 functions that have their own policy files.
            'g': {'autogen_policy': False, 'iam_policy_file': 'g.json'},
            'h': {'autogen_policy': False, 'iam_policy_file': 'h.json'}
        },
        roles={
            'a': {'name': 'appname-dev', 'autogenerated': True},
            'b': {'name': 'appname-dev', 'autogenerated': True},
            'c': {'managed_role': False, 'iam_role_arn': 'role:arn'},
            'd': {'managed_role': False, 'iam_role_arn': 'role:arn2'},
            'e': {'name': 'appname-dev-e',
                  'autogenerated': False,
                  'policy_file': 'policy-dev.json'},
            'f': {'name': 'appname-dev-f',
                  'autogenerated': False,
                  'policy_file': 'policy-dev.json'},
            'g': {'name': 'appname-dev-g',
                  'autogenerated': False,
                  'policy_file': 'g.json'},
            'h': {'name': 'appname-dev-h',
                  'autogenerated': False,
                  'policy_file': 'h.json'},
        }),
]


@pytest.mark.parametrize('case', ROLE_TEST_CASES)
def test_role_creation(case):
    _, config = case.build()
    builder = ApplicationGraphBuilder()
    application = builder.build(config, stage_name='dev')
    case.assert_required_roles_created(application)


class TestDefaultsInjector(object):
    def test_inject_when_values_are_none(self):
        injector = InjectDefaults(
            lambda_timeout=100,
            lambda_memory_size=512,
        )
        function = models.LambdaFunction(
            # The timeout/memory_size are set to
            # None, so the injector should fill them
            # in the with the default values above.
            timeout=None,
            memory_size=None,
            resource_name='foo',
            function_name='app-dev-foo',
            environment_variables={},
            runtime='python2.7',
            handler='app.app',
            tags={},
            deployment_package=None,
            role=None,
        )
        config = Config.create()
        injector.handle(config, function)
        assert function.timeout == 100
        assert function.memory_size == 512

    def test_no_injection_when_values_are_set(self):
        injector = InjectDefaults(
            lambda_timeout=100,
            lambda_memory_size=512,
        )
        function = models.LambdaFunction(
            # The timeout/memory_size are set to
            # None, so the injector should fill them
            # in the with the default values above.
            timeout=1,
            memory_size=1,
            resource_name='foo',
            function_name='app-stage-foo',
            environment_variables={},
            runtime='python2.7',
            handler='app.app',
            tags={},
            deployment_package=None,
            role=None,
        )
        config = Config.create()
        injector.handle(config, function)
        assert function.timeout == 1
        assert function.memory_size == 1


class TestPolicyGeneratorStage(object):
    def test_invokes_policy_generator(self):
        generator = mock.Mock(spec=AppPolicyGenerator)
        generator.generate_policy.return_value = {'policy': 'doc'}
        policy = models.AutoGenIAMPolicy(models.Placeholder.BUILD_STAGE)
        config = Config.create()

        p = PolicyGenerator(generator)
        p.handle(config, policy)

        assert policy.document == {'policy': 'doc'}

    def test_no_policy_generated_if_exists(self):
        generator = mock.Mock(spec=AppPolicyGenerator)
        generator.generate_policy.return_value = {'policy': 'new'}
        policy = models.AutoGenIAMPolicy(document={'policy': 'original'})
        config = Config.create()

        p = PolicyGenerator(generator)
        p.handle(config, policy)

        assert policy.document == {'policy': 'original'}
        assert not generator.generate_policy.called


class TestSwaggerBuilder(object):
    def test_can_generate_swagger_builder(self):
        generator = mock.Mock(spec=SwaggerGenerator)
        generator.generate_swagger.return_value = {'swagger': '2.0'}

        rest_api = models.RestAPI(
            resource_name='foo',
            swagger_doc=models.Placeholder.BUILD_STAGE,
            api_gateway_stage='api',
            lambda_function=None,
        )
        config = Config.create(chalice_app=mock.sentinel.chalice_app)
        p = SwaggerBuilder(generator)
        p.handle(config, rest_api)
        assert rest_api.swagger_doc == {'swagger': '2.0'}
        generator.generate_swagger.assert_called_with(
            mock.sentinel.chalice_app
        )


class TestDeploymentPackager(object):
    def test_can_generate_package(self):
        generator = mock.Mock(spec=packager.LambdaDeploymentPackager)
        generator.create_deployment_package.return_value = 'package.zip'

        package = models.DeploymentPackage(models.Placeholder.BUILD_STAGE)
        config = Config.create()

        p = DeploymentPackager(generator)
        p.handle(config, package)

        assert package.filename == 'package.zip'

    def test_package_not_generated_if_filename_populated(self):
        generator = mock.Mock(spec=packager.LambdaDeploymentPackager)
        generator.create_deployment_package.return_value = 'NEWPACKAGE.zip'

        package = models.DeploymentPackage(filename='original-name.zip')
        config = Config.create()

        p = DeploymentPackager(generator)
        p.handle(config, package)

        assert package.filename == 'original-name.zip'
        assert not generator.create_deployment_package.called


class TestExecutor(object):
    def setup_method(self):
        self.mock_client = mock.Mock(spec=TypedAWSClient)
        self.ui = mock.Mock(spec=UI)
        self.executor = Executor(self.mock_client, self.ui)

    def execute(self, instructions, messages=None):
        if messages is None:
            messages = {}
        self.executor.execute(models.Plan(instructions, messages))

    def test_can_invoke_api_call_with_no_output(self):
        params = {'name': 'foo', 'trust_policy': {'trust': 'policy'},
                  'policy': {'iam': 'policy'}}
        call = APICall('create_role', params)

        self.execute([call])

        self.mock_client.create_role.assert_called_with(**params)

    def test_can_store_api_result(self):
        params = {'name': 'foo', 'trust_policy': {'trust': 'policy'},
                  'policy': {'iam': 'policy'}}
        apicall = APICall('create_role', params, output_var='my_variable_name')
        self.mock_client.create_role.return_value = 'myrole:arn'

        self.execute([apicall])

        assert self.executor.variables['my_variable_name'] == 'myrole:arn'

    def test_can_reference_stored_results_in_api_calls(self):
        params = {
            'name': Variable('role_name'),
            'trust_policy': {'trust': 'policy'},
            'policy': {'iam': 'policy'}
        }
        call = APICall('create_role', params)
        self.mock_client.create_role.return_value = 'myrole:arn'

        self.executor.variables['role_name'] = 'myrole-name'
        self.execute([call])

        self.mock_client.create_role.assert_called_with(
            name='myrole-name',
            trust_policy={'trust': 'policy'},
            policy={'iam': 'policy'},
        )

    def test_can_return_created_resources(self):
        params = {}
        call = APICall('create_function', params,
                       output_var='myfunction_arn')
        self.mock_client.create_function.return_value = 'function:arn'
        record_instruction = RecordResourceVariable(
            resource_type='lambda_function',
            resource_name='myfunction',
            name='myfunction_arn',
            variable_name='myfunction_arn',
        )
        self.execute([call, record_instruction])
        assert self.executor.resource_values == [{
            'name': 'myfunction',
            'myfunction_arn': 'function:arn',
            'resource_type': 'lambda_function',
        }]

    def test_can_reference_varname(self):
        self.mock_client.create_function.return_value = 'function:arn'
        self.execute([
            APICall('create_function', {}, output_var='myvarname'),
            RecordResourceVariable(
                resource_type='lambda_function',
                resource_name='myfunction',
                name='myfunction_arn',
                variable_name='myvarname',
            ),
        ])
        assert self.executor.resource_values == [{
            'name': 'myfunction',
            'resource_type': 'lambda_function',
            'myfunction_arn': 'function:arn',
        }]

    def test_can_record_value_directly(self):
        self.execute([
            RecordResourceValue(
                resource_type='lambda_function',
                resource_name='myfunction',
                name='myfunction_arn',
                value='arn:foo',
            )
        ])
        assert self.executor.resource_values == [{
            'name': 'myfunction',
            'resource_type': 'lambda_function',
            'myfunction_arn': 'arn:foo',
        }]

    def test_can_aggregate_multiple_resource_values(self):
        self.execute([
            RecordResourceValue(
                resource_type='lambda_function',
                resource_name='myfunction',
                name='key1',
                value='value1',
            ),
            RecordResourceValue(
                resource_type='lambda_function',
                resource_name='myfunction',
                name='key2',
                value='value2',
            )
        ])
        assert self.executor.resource_values == [{
            'name': 'myfunction',
            'resource_type': 'lambda_function',
            'key1': 'value1',
            'key2': 'value2',
        }]

    def test_new_keys_override_old_keys(self):
        self.execute([
            RecordResourceValue(
                resource_type='lambda_function',
                resource_name='myfunction',
                name='key1',
                value='OLD',
            ),
            RecordResourceValue(
                resource_type='lambda_function',
                resource_name='myfunction',
                name='key1',
                value='NEW',
            )
        ])
        assert self.executor.resource_values == [{
            'name': 'myfunction',
            'resource_type': 'lambda_function',
            'key1': 'NEW',
        }]

    def test_validates_no_unresolved_deploy_vars(self):
        params = {'zip_contents': models.Placeholder.BUILD_STAGE}
        call = APICall('create_function', params)
        self.mock_client.create_function.return_value = 'function:arn'
        # We should raise an exception because a param has
        # a models.Placeholder.BUILD_STAGE value which should have
        # been handled in an earlier stage.
        with pytest.raises(UnresolvedValueError):
            self.execute([call])

    def test_can_jp_search(self):
        self.execute([
            StoreValue(name='searchval', value={'foo': {'bar': 'baz'}}),
            JPSearch('foo.bar', input_var='searchval', output_var='result'),
        ])
        assert self.executor.variables['result'] == 'baz'

    def test_can_call_builtin_function(self):
        self.execute([
            StoreValue(
                name='my_arn',
                value='arn:aws:lambda:us-west-2:123:function:name'),
            BuiltinFunction(
                function_name='parse_arn',
                args=[Variable('my_arn')],
                output_var='result',
            )
        ])
        assert self.executor.variables['result'] == {
            'account_id': '123',
            'region': 'us-west-2',
            'service': 'lambda'
        }

    def test_errors_out_on_unknown_function(self):
        with pytest.raises(ValueError):
            self.execute([
                BuiltinFunction(
                    function_name='unknown_foo',
                    args=[],
                    output_var=None,
                )
            ])

    def test_can_print_ui_messages(self):
        params = {'name': 'foo', 'trust_policy': {'trust': 'policy'},
                  'policy': {'iam': 'policy'}}
        call = APICall('create_role', params)
        messages = {id(call): 'Creating role'}
        self.execute([call], messages)
        self.mock_client.create_role.assert_called_with(**params)
        self.ui.write.assert_called_with('Creating role')


def test_build_stage():
    first = mock.Mock(spec=BaseDeployStep)
    second = mock.Mock(spec=BaseDeployStep)
    build = BuildStage([first, second])

    foo_resource = mock.sentinel.foo_resource
    bar_resource = mock.sentinel.bar_resource
    config = Config.create()
    build.execute(config, [foo_resource, bar_resource])

    assert first.handle.call_args_list == [
        mock.call(config, foo_resource),
        mock.call(config, bar_resource),
    ]
    assert second.handle.call_args_list == [
        mock.call(config, foo_resource),
        mock.call(config, bar_resource),
    ]


class TestDeployer(unittest.TestCase):
    def setUp(self):
        self.resource_builder = mock.Mock(spec=ApplicationGraphBuilder)
        self.deps_builder = mock.Mock(spec=DependencyBuilder)
        self.build_stage = mock.Mock(spec=BuildStage)
        self.plan_stage = mock.Mock(spec=PlanStage)
        self.sweeper = mock.Mock(spec=UnreferencedResourcePlanner)
        self.executor = mock.Mock(spec=Executor)
        self.recorder = mock.Mock(spec=ResultsRecorder)

    def create_deployer(self):
        return Deployer(
            self.resource_builder,
            self.deps_builder,
            self.build_stage,
            self.plan_stage,
            self.sweeper,
            self.executor,
            self.recorder,
        )

    def test_deploy_delegates_properly(self):
        app = mock.Mock(spec=models.Application)
        resources = [mock.Mock(spec=models.Model)]
        api_calls = [mock.Mock(spec=APICall)]

        self.resource_builder.build.return_value = app
        self.deps_builder.build_dependencies.return_value = resources
        self.plan_stage.execute.return_value = api_calls
        self.executor.resource_values = {'foo': {'name': 'bar'}}

        deployer = self.create_deployer()
        config = Config.create(project_dir='.')
        result = deployer.deploy(config, 'dev')

        self.resource_builder.build.assert_called_with(config, 'dev')
        self.deps_builder.build_dependencies.assert_called_with(app)
        self.build_stage.execute.assert_called_with(config, resources)
        self.plan_stage.execute.assert_called_with(resources)
        self.sweeper.execute.assert_called_with(api_calls, config)
        self.executor.execute.assert_called_with(api_calls)

        expected_result = {
            'resources': {'foo': {'name': 'bar'}},
            'schema_version': '2.0',
        }

        self.recorder.record_results.assert_called_with(
            expected_result, 'dev', '.')
        assert result == expected_result


def test_can_create_default_deployer():
    session = botocore.session.get_session()
    deployer = create_default_deployer(session, Config.create(
        project_dir='.',
        chalice_stage='dev',
    ), UI())
    assert isinstance(deployer, Deployer)


def test_can_create_deletion_deployer():
    session = botocore.session.get_session()
    deployer = create_deletion_deployer(TypedAWSClient(session), UI())
    assert isinstance(deployer, Deployer)


class TestResolveVariables(object):

    def resolve_vars(self, params, variables):
        return VariableResolver().resolve_variables(
            params, variables
        )

    def test_resolve_top_level_vars(self):
        assert self.resolve_vars(
            {'foo': Variable('myvar')},
            {'myvar': 'value'}
        ) == {'foo': 'value'}

    def test_can_resolve_multiple_vars(self):
        assert self.resolve_vars(
            {'foo': Variable('myvar'),
             'bar': Variable('myvar')},
            {'myvar': 'value'}
        ) == {'foo': 'value', 'bar': 'value'}

    def test_unsolved_error_raises_error(self):
        with pytest.raises(UnresolvedValueError):
            self.resolve_vars({'foo': models.Placeholder.BUILD_STAGE}, {})

    def test_can_resolve_nested_variable_refs(self):
        assert self.resolve_vars(
            {'foo': {'bar': Variable('myvar')}},
            {'myvar': 'value'}
        ) == {'foo': {'bar': 'value'}}

    def test_can_resolve_vars_in_list(self):
        assert self.resolve_vars(
            {'foo': [0, 1, Variable('myvar')]},
            {'myvar': 2}
        ) == {'foo': [0, 1, 2]}

    def test_deeply_nested(self):
        nested = {
            'a': {
                'b': {
                    'c': {
                        'd': [{'e': {'f': Variable('foo')}}],
                    }
                }
            }
        }
        variables = {'foo': 'value'}
        assert self.resolve_vars(nested, variables) == {
            'a': {
                'b': {
                    'c': {
                        'd': [{'e': {'f': 'value'}}],
                    }
                }
            }
        }

    def test_can_handle_format_string(self):
        params = {'bar': StringFormat('value: {my_var}', ['my_var'])}
        variables = {'my_var': 'foo'}
        assert self.resolve_vars(params, variables) == {
            'bar': 'value: foo',
        }

    def test_can_handle_deeply_nested_format_string(self):
        nested = {
            'a': {
                'b': {
                    'c': {
                        'd': [{'e': {'f': StringFormat(
                            'foo: {myvar}', ['myvar'])}}],
                    }
                }
            }
        }
        variables = {'myvar': 'value'}
        assert self.resolve_vars(nested, variables) == {
            'a': {
                'b': {
                    'c': {
                        'd': [{'e': {'f': 'foo: value'}}],
                    }
                }
            }
        }


def test_templated_swagger_generator(rest_api_app):
    doc = TemplatedSwaggerGenerator().generate_swagger(rest_api_app)
    uri = doc['paths']['/']['get']['x-amazon-apigateway-integration']['uri']
    assert isinstance(uri, StringFormat)
    assert uri.template == (
        'arn:aws:apigateway:{region_name}:lambda:path'
        '/2015-03-31/functions/{api_handler_lambda_arn}/invocations'
    )
    assert uri.variables == ['region_name', 'api_handler_lambda_arn']


def test_templated_swagger_with_auth_uri(rest_api_app):
    @rest_api_app.authorizer()
    def myauth(auth_request):
        pass

    @rest_api_app.route('/auth', authorizer=myauth)
    def needsauth():
        return {}

    doc = TemplatedSwaggerGenerator().generate_swagger(rest_api_app)
    uri = doc['securityDefinitions']['myauth'][
        'x-amazon-apigateway-authorizer']['authorizerUri']
    assert isinstance(uri, StringFormat)
    assert uri.template == (
        'arn:aws:apigateway:{region_name}:lambda:path'
        '/2015-03-31/functions/{myauth_lambda_arn}/invocations'
    )
    assert uri.variables == ['region_name', 'myauth_lambda_arn']


class TestRecordResults(object):
    def setup_method(self):
        self.osutils = mock.Mock(spec=OSUtils)
        self.recorder = ResultsRecorder(self.osutils)
        self.deployed_values = {
            'stages': {
                'dev': {'resources': []},
            },
            'schema_version': '2.0',
        }
        self.osutils.joinpath = os.path.join
        self.deployed_dir = os.path.join('.', '.chalice', 'deployed')

    def test_can_record_results_initial_deploy(self):
        expected_filename = os.path.join(self.deployed_dir, 'dev.json')
        self.osutils.file_exists.return_value = False
        self.osutils.directory_exists.return_value = False
        self.recorder.record_results(
            self.deployed_values, 'dev', '.',
        )
        expected_contents = serialize_to_json(self.deployed_values)
        # Verify we created the deployed dir on an initial deploy.
        self.osutils.makedirs.assert_called_with(self.deployed_dir)
        self.osutils.set_file_contents.assert_called_with(
            filename=expected_filename,
            contents=expected_contents,
            binary=False
        )
