import os

import socket
import botocore.session

import pytest
import mock
from botocore.stub import Stubber
from botocore.vendored.requests import ConnectionError as \
    RequestsConnectionError
from pytest import fixture

from chalice.app import Chalice
from chalice.awsclient import LambdaClientError, AWSClientError
from chalice.awsclient import DeploymentPackageTooLargeError
from chalice.awsclient import LambdaErrorContext
from chalice.config import Config
from chalice.policy import AppPolicyGenerator
from chalice.deploy.deployer import ChaliceDeploymentError
from chalice.utils import UI
import unittest

from attr import attrs, attrib

from chalice.awsclient import TypedAWSClient
from chalice.utils import OSUtils, serialize_to_json
from chalice.deploy import models
from chalice.deploy import packager
from chalice.deploy.deployer import create_default_deployer, \
    create_deletion_deployer, Deployer, BaseDeployStep, \
    InjectDefaults, DeploymentPackager, SwaggerBuilder, \
    PolicyGenerator, BuildStage, ResultsRecorder, DeploymentReporter, \
    ManagedLayerDeploymentPackager
from chalice.deploy.appgraph import ApplicationGraphBuilder, \
    DependencyBuilder
from chalice.deploy.executor import Executor
from chalice.deploy.swagger import SwaggerGenerator, TemplatedSwaggerGenerator
from chalice.deploy.planner import PlanStage
from chalice.deploy.planner import StringFormat
from chalice.deploy.sweeper import ResourceSweeper
from chalice.deploy.models import APICall
from chalice.constants import VPC_ATTACH_POLICY
from chalice.constants import SQS_EVENT_SOURCE_POLICY
from chalice.constants import KINESIS_EVENT_SOURCE_POLICY
from chalice.constants import DDB_EVENT_SOURCE_POLICY
from chalice.constants import POST_TO_WEBSOCKET_CONNECTION_POLICY
from chalice.deploy.deployer import LambdaEventSourcePolicyInjector
from chalice.deploy.deployer import WebsocketPolicyInjector


_SESSION = None


class InMemoryOSUtils(object):
    def __init__(self, filemap=None):
        if filemap is None:
            filemap = {}
        self.filemap = filemap

    def file_exists(self, filename):
        return filename in self.filemap

    def get_file_contents(self, filename, binary=True):
        return self.filemap[filename]

    def set_file_contents(self, filename, contents, binary=True):
        self.filemap[filename] = contents


@fixture
def in_memory_osutils():
    return InMemoryOSUtils()


def stubbed_client(service_name):
    global _SESSION
    if _SESSION is None:
        _SESSION = botocore.session.get_session()
    client = _SESSION.create_client(service_name,
                                    region_name='us-west-2')
    stubber = Stubber(client)
    return client, stubber


@fixture
def config_obj(sample_app):
    config = Config.create(
        chalice_app=sample_app,
        stage='dev',
        api_gateway_stage='api',
    )
    return config


@fixture
def ui():
    return mock.Mock(spec=UI)


class TestChaliceDeploymentError(object):
    def test_general_exception(self):
        general_exception = Exception('My Exception')
        deploy_error = ChaliceDeploymentError(general_exception)
        deploy_error_msg = str(deploy_error)
        assert (
            'ERROR - While deploying your chalice application'
            in deploy_error_msg
        )
        assert 'My Exception' in deploy_error_msg

    def test_lambda_client_error(self):
        lambda_error = LambdaClientError(
            Exception('My Exception'),
            context=LambdaErrorContext(
                function_name='foo',
                client_method_name='create_function',
                deployment_size=1024 ** 2
            )
        )
        deploy_error = ChaliceDeploymentError(lambda_error)
        deploy_error_msg = str(deploy_error)
        assert (
            'ERROR - While sending your chalice handler code to '
            'Lambda to create function \n"foo"' in deploy_error_msg
        )
        assert 'My Exception' in deploy_error_msg

    def test_lambda_client_error_wording_for_update(self):
        lambda_error = LambdaClientError(
            Exception('My Exception'),
            context=LambdaErrorContext(
                function_name='foo',
                client_method_name='update_function_code',
                deployment_size=1024 ** 2
            )
        )
        deploy_error = ChaliceDeploymentError(lambda_error)
        deploy_error_msg = str(deploy_error)
        assert (
            'sending your chalice handler code to '
            'Lambda to update function' in deploy_error_msg
        )

    def test_gives_where_and_suggestion_for_too_large_deployment_error(self):
        too_large_error = DeploymentPackageTooLargeError(
            Exception('Too large of deployment pacakge'),
            context=LambdaErrorContext(
                function_name='foo',
                client_method_name='create_function',
                deployment_size=1024 ** 2,
            )
        )
        deploy_error = ChaliceDeploymentError(too_large_error)
        deploy_error_msg = str(deploy_error)
        assert (
            'ERROR - While sending your chalice handler code to '
            'Lambda to create function \n"foo"' in deploy_error_msg
        )
        assert 'Too large of deployment pacakge' in deploy_error_msg
        assert (
            'To avoid this error, decrease the size of your chalice '
            'application ' in deploy_error_msg
        )

    def test_include_size_context_for_too_large_deployment_error(self):
        too_large_error = DeploymentPackageTooLargeError(
            Exception('Too large of deployment pacakge'),
            context=LambdaErrorContext(
                function_name='foo',
                client_method_name='create_function',
                deployment_size=58 * (1024 ** 2),
            )
        )
        deploy_error = ChaliceDeploymentError(
            too_large_error)
        deploy_error_msg = str(deploy_error)
        print(repr(deploy_error_msg))
        assert 'deployment package is 58.0 MB' in deploy_error_msg
        assert '50.0 MB or less' in deploy_error_msg
        assert 'To avoid this error' in deploy_error_msg

    def test_error_msg_for_general_connection(self):
        lambda_error = DeploymentPackageTooLargeError(
            RequestsConnectionError(
                Exception(
                    'Connection aborted.',
                    socket.error('Some vague reason')
                )
            ),
            context=LambdaErrorContext(
                function_name='foo',
                client_method_name='create_function',
                deployment_size=1024 ** 2
            )
        )
        deploy_error = ChaliceDeploymentError(lambda_error)
        deploy_error_msg = str(deploy_error)
        assert 'Connection aborted.' in deploy_error_msg
        assert 'Some vague reason' not in deploy_error_msg

    def test_simplifies_error_msg_for_broken_pipe(self):
        lambda_error = DeploymentPackageTooLargeError(
            RequestsConnectionError(
                Exception(
                    'Connection aborted.',
                    socket.error(32, 'Broken pipe')
                )
            ),
            context=LambdaErrorContext(
                function_name='foo',
                client_method_name='create_function',
                deployment_size=1024 ** 2
            )
        )
        deploy_error = ChaliceDeploymentError(lambda_error)
        deploy_error_msg = str(deploy_error)
        assert (
            'Connection aborted. Lambda closed the connection' in
            deploy_error_msg
        )

    def test_simplifies_error_msg_for_timeout(self):
        lambda_error = DeploymentPackageTooLargeError(
            RequestsConnectionError(
                Exception(
                    'Connection aborted.',
                    socket.timeout('The write operation timed out')
                )
            ),
            context=LambdaErrorContext(
                function_name='foo',
                client_method_name='create_function',
                deployment_size=1024 ** 2
            )
        )
        deploy_error = ChaliceDeploymentError(lambda_error)
        deploy_error_msg = str(deploy_error)
        assert (
            'Connection aborted. Timed out sending your app to Lambda.' in
            deploy_error_msg
        )


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
        deployment_package=models.DeploymentPackage(
            models.Placeholder.BUILD_STAGE
        ),
        xray=False,
        role=models.PreCreatedIAMRole(role_arn='role:arn'),
        security_group_ids=[],
        subnet_ids=[],
        layers=[],
        reserved_concurrency=None,
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
        functions_by_name = {
            f.function_name: f for f in resources
            if isinstance(f, models.LambdaFunction)}
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
            xray=None,
            deployment_package=None,
            role=None,
            security_group_ids=[],
            subnet_ids=[],
            layers=[],
            reserved_concurrency=None,
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
            xray=None,
            deployment_package=None,
            role=None,
            security_group_ids=[],
            subnet_ids=[],
            layers=[],
            reserved_concurrency=None,
        )
        config = Config.create()
        injector.handle(config, function)
        assert function.timeout == 1
        assert function.memory_size == 1

    def test_default_tls_version_on_domain_name(self):
        injector = InjectDefaults(tls_version='TLS_1_2')
        domain_name = models.DomainName(
            resource_name='my_domain_name',
            domain_name='example.com',
            protocol=models.APIType.HTTP,
            certificate_arn='myarn',
            api_mapping=models.APIMapping(resource_name='mymapping',
                                          mount_path='(none)',
                                          api_gateway_stage='api')
        )
        config = Config.create()
        injector.handle(config, domain_name)
        assert domain_name.tls_version == models.TLSVersion.TLS_1_2


class TestPolicyGeneratorStage(object):
    def setup_method(self):
        self.osutils = mock.Mock(spec=OSUtils)

    def create_policy_generator(self, generator=None):
        if generator is None:
            generator = mock.Mock(spec=AppPolicyGenerator)
        p = PolicyGenerator(generator, self.osutils)
        return p

    def test_invokes_policy_generator(self):
        generator = mock.Mock(spec=AppPolicyGenerator)
        generator.generate_policy.return_value = {'policy': 'doc'}
        policy = models.AutoGenIAMPolicy(models.Placeholder.BUILD_STAGE)
        config = Config.create()

        p = self.create_policy_generator(generator)
        p.handle(config, policy)

        assert policy.document == {'policy': 'doc'}

    def test_no_policy_generated_if_exists(self):
        generator = mock.Mock(spec=AppPolicyGenerator)
        generator.generate_policy.return_value = {'policy': 'new'}
        policy = models.AutoGenIAMPolicy(document={'policy': 'original'})
        config = Config.create()

        p = self.create_policy_generator(generator)
        p.handle(config, policy)

        assert policy.document == {'policy': 'original'}
        assert not generator.generate_policy.called

    def test_policy_loaded_from_file_if_needed(self):
        p = self.create_policy_generator()
        policy = models.FileBasedIAMPolicy(
            filename='foo.json', document=models.Placeholder.BUILD_STAGE)
        self.osutils.get_file_contents.return_value = '{"iam": "policy"}'

        p.handle(Config.create(), policy)

        assert policy.document == {'iam': 'policy'}
        self.osutils.get_file_contents.assert_called_with('foo.json')

    def test_error_raised_if_file_policy_not_exists(self):
        p = self.create_policy_generator()
        policy = models.FileBasedIAMPolicy(
            filename='foo.json', document=models.Placeholder.BUILD_STAGE)
        self.osutils.get_file_contents.side_effect = IOError()

        with pytest.raises(RuntimeError):
            p.handle(Config.create(), policy)

    def test_vpc_policy_inject_if_needed(self):
        generator = mock.Mock(spec=AppPolicyGenerator)
        generator.generate_policy.return_value = {'Statement': []}
        policy = models.AutoGenIAMPolicy(
            document=models.Placeholder.BUILD_STAGE,
            traits=set([models.RoleTraits.VPC_NEEDED]),
        )
        config = Config.create()

        p = self.create_policy_generator(generator)
        p.handle(config, policy)

        assert policy.document['Statement'][0] == VPC_ATTACH_POLICY


class TestSwaggerBuilder(object):
    def test_can_generate_swagger_builder(self):
        generator = mock.Mock(spec=SwaggerGenerator)
        generator.generate_swagger.return_value = {'swagger': '2.0'}

        rest_api = models.RestAPI(
            resource_name='foo',
            swagger_doc=models.Placeholder.BUILD_STAGE,
            minimum_compression='',
            endpoint_type='EDGE',
            api_gateway_stage='api',
            lambda_function=None,
            xray=False,
        )
        app = Chalice(app_name='foo')
        config = Config.create(chalice_app=app)
        p = SwaggerBuilder(generator)
        p.handle(config, rest_api)
        assert rest_api.swagger_doc == {'swagger': '2.0'}
        generator.generate_swagger.assert_called_with(app, rest_api)


class TestDeploymentPackager(object):
    def test_can_generate_layer_package(self):
        function = create_function_resource('myfunction')
        function.managed_layer = models.LambdaLayer(
            resource_name='managed-layer',
            layer_name='appname-dev-managed-layer',
            runtime='python2.7',
            deployment_package=models.DeploymentPackage(
                models.Placeholder.BUILD_STAGE
            )
        )
        lambda_packager = mock.Mock(spec=packager.BaseLambdaDeploymentPackager)
        layer_packager = mock.Mock(spec=packager.BaseLambdaDeploymentPackager)
        lambda_packager.create_deployment_package.return_value = 'package.zip'
        layer_packager.create_deployment_package.return_value = (
            'package-layer.zip')

        config = Config.create(project_dir='.')

        p = ManagedLayerDeploymentPackager(lambda_packager, layer_packager)
        p.handle(config, function.managed_layer)
        p.handle(config, function)
        assert function.deployment_package.filename == 'package.zip'
        lambda_packager.create_deployment_package.assert_called_with(
            '.', config.lambda_python_version
        )
        assert function.managed_layer.deployment_package.filename == (
            'package-layer.zip'
        )
        layer_packager.create_deployment_package.assert_called_with(
            '.', config.lambda_python_version
        )

    def test_layer_package_not_generated_if_filename_populated(self):
        generator = mock.Mock(spec=packager.BaseLambdaDeploymentPackager)

        function = create_function_resource('myfunction')
        layer = models.LambdaLayer(
            resource_name='layer',
            layer_name='name',
            runtime='python2.7',
            deployment_package=models.DeploymentPackage(
                filename='original.zip')
        )
        function.managed_layer = layer
        config = Config.create(project_dir='.')

        p = ManagedLayerDeploymentPackager(None, generator)
        p.handle(config, layer)

        assert layer.deployment_package.filename == 'original.zip'
        assert not generator.create_deployment_package.called

    def test_managed_layer_removed_if_no_deps(self):
        function = create_function_resource('myfunction')
        function.managed_layer = models.LambdaLayer(
            resource_name='managed-layer',
            layer_name='appname-dev-managed-layer',
            runtime='python2.7',
            deployment_package=models.DeploymentPackage(
                models.Placeholder.BUILD_STAGE
            )
        )
        lambda_packager = mock.Mock(spec=packager.BaseLambdaDeploymentPackager)
        layer_packager = mock.Mock(spec=packager.BaseLambdaDeploymentPackager)
        lambda_packager.create_deployment_package.return_value = 'package.zip'
        layer_packager.create_deployment_package.side_effect = \
            packager.EmptyPackageError()

        config = Config.create(project_dir='.')

        p = ManagedLayerDeploymentPackager(lambda_packager, layer_packager)
        p.handle(config, function.managed_layer)
        p.handle(config, function)
        # If the deployment package for layers would result in an empty
        # deployment package, we expect that resource to be removed, it can't
        # be created on the service.
        assert function.managed_layer is None

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
        self.sweeper = mock.Mock(spec=ResourceSweeper)
        self.executor = mock.Mock(spec=Executor)
        self.recorder = mock.Mock(spec=ResultsRecorder)
        self.chalice_app = Chalice(app_name='foo')

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
        config = Config.create(project_dir='.', chalice_app=self.chalice_app)
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
            'backend': 'api',
        }

        self.recorder.record_results.assert_called_with(
            expected_result, 'dev', '.')
        assert result == expected_result

    def test_deploy_errors_raises_chalice_error(self):
        self.resource_builder.build.side_effect = AWSClientError()

        deployer = self.create_deployer()
        config = Config.create(project_dir='.', chalice_app=self.chalice_app)
        with pytest.raises(ChaliceDeploymentError):
            deployer.deploy(config, 'dev')

    def test_validation_errors_raise_failure(self):

        @self.chalice_app.route('')
        def bad_route_empty_string():
            return {}

        deployer = self.create_deployer()
        config = Config.create(project_dir='.', chalice_app=self.chalice_app)
        with pytest.raises(ChaliceDeploymentError):
            deployer.deploy(config, 'dev')


def test_can_create_default_deployer():
    session = botocore.session.get_session()
    deployer = create_default_deployer(session, Config.create(
        project_dir='.',
        chalice_stage='dev',
    ), UI())
    assert isinstance(deployer, Deployer)


def test_can_create_deployer_with_layer_builds():
    session = botocore.session.get_session()
    deployer = create_default_deployer(session, Config.create(
        project_dir='.',
        chalice_stage='dev',
        automatic_layer=True,
    ), UI())
    assert isinstance(deployer, Deployer)


def test_can_create_deletion_deployer():
    session = botocore.session.get_session()
    deployer = create_deletion_deployer(TypedAWSClient(session), UI())
    assert isinstance(deployer, Deployer)


def test_templated_swagger_generator(sample_app):
    doc = TemplatedSwaggerGenerator().generate_swagger(sample_app)
    uri = doc['paths']['/']['get']['x-amazon-apigateway-integration']['uri']
    assert isinstance(uri, StringFormat)
    assert uri.template == (
        'arn:{partition}:apigateway:{region_name}:lambda:path'
        '/2015-03-31/functions/{api_handler_lambda_arn}/invocations'
    )
    assert uri.variables == ['partition', 'region_name',
                             'api_handler_lambda_arn']


def test_templated_swagger_with_auth_uri(sample_app_with_auth):
    doc = TemplatedSwaggerGenerator().generate_swagger(sample_app_with_auth)
    uri = doc['securityDefinitions']['myauth'][
        'x-amazon-apigateway-authorizer']['authorizerUri']
    assert isinstance(uri, StringFormat)
    assert uri.template == (
        'arn:{partition}:apigateway:{region_name}:lambda:path'
        '/2015-03-31/functions/{myauth_lambda_arn}/invocations'
    )
    assert uri.variables == ['partition', 'region_name', 'myauth_lambda_arn']


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


class TestDeploymentReporter(object):
    def setup_method(self):
        self.ui = mock.Mock(spec=UI)
        self.reporter = DeploymentReporter(ui=self.ui)

    def test_can_generate_report(self):
        certificate_arn = "arn:aws:acm:us-east-1:account_id:" \
                         "certificate/e2600f49-f6b7-4105-aaf6-63b2f018a030"
        deployed_values = {
            "resources": [
                {"role_name": "james2-dev",
                 "role_arn": "my-role-arn",
                 "name": "default-role",
                 "resource_type": "iam_role"},
                {"resource_type": "lambda_layer",
                 "name": "layer",
                 "layer_version_arn": "arn:layer:4"},
                {"lambda_arn": "lambda-arn-foo",
                 "name": "foo",
                 "resource_type": "lambda_function"},
                {"lambda_arn": "lambda-arn-dev",
                 "name": "api_handler",
                 "resource_type": "lambda_function"},
                {"name": "rest_api",
                 "rest_api_id": "rest_api_id",
                 "rest_api_url": "https://host/api",
                 "resource_type": "rest_api"},
                {"name": "websocket_api",
                 "websocket_api_id": "websocket_api_id",
                 "websocket_api_url": "wss://host/api",
                 "resource_type": "websocket_api"},
                {"name": "api_gateway_custom_domain",
                 "resource_type": "domain_name",
                 "hosted_zone_id": "A1FDTDATADATA0",
                 "certificate_arn": certificate_arn,
                 "alias_domain_name": "alias.domain.com",
                 "security_policy": "TLS_1_0",
                 "domain_name": "api.domain",
                 "api_mapping": [
                     {
                         "key": "/test1"
                     }
                 ]}
            ],
        }
        report = self.reporter.generate_report(deployed_values)
        assert report == (
            "Resources deployed:\n"
            "  - Lambda Layer ARN: arn:layer:4\n"
            "  - Lambda ARN: lambda-arn-foo\n"
            "  - Lambda ARN: lambda-arn-dev\n"
            "  - Rest API URL: https://host/api\n"
            "  - Websocket API URL: wss://host/api\n"
            "  - Custom domain name:\n"
            "      HostedZoneId: A1FDTDATADATA0\n"
            "      AliasDomainName: alias.domain.com\n"
        )

    def test_can_display_report(self):
        deployed_values = {
            'resources': []
        }
        self.reporter.display_report(deployed_values)
        self.ui.write.assert_called_with('Resources deployed:\n')


class TestLambdaEventSourcePolicyInjector(object):
    def create_model_from_app(self, app, config):
        builder = ApplicationGraphBuilder()
        application = builder.build(config, stage_name='dev')
        return application.resources[0]

    def test_can_inject_policy(self, sample_sqs_event_app):
        config = Config.create(chalice_app=sample_sqs_event_app,
                               autogen_policy=True,
                               project_dir='.')
        event_source = self.create_model_from_app(sample_sqs_event_app, config)
        role = event_source.lambda_function.role
        role.policy.document = {'Statement': []}
        injector = LambdaEventSourcePolicyInjector()
        injector.handle(config, event_source)
        assert role.policy.document == {
            'Statement': [SQS_EVENT_SOURCE_POLICY.copy()],
        }

    def test_no_inject_if_not_autogen_policy(self, sample_sqs_event_app):
        config = Config.create(chalice_app=sample_sqs_event_app,
                               autogen_policy=False,
                               project_dir='.')
        event_source = self.create_model_from_app(sample_sqs_event_app, config)
        role = event_source.lambda_function.role
        role.policy.document = {'Statement': []}
        injector = LambdaEventSourcePolicyInjector()
        injector.handle(config, event_source)
        assert role.policy.document == {'Statement': []}

    def test_no_inject_is_already_injected(self, sample_sqs_event_app):
        @sample_sqs_event_app.on_sqs_message(queue='second-queue')
        def second_handler(event):
            pass

        config = Config.create(chalice_app=sample_sqs_event_app,
                               autogen_policy=True,
                               project_dir='.')
        builder = ApplicationGraphBuilder()
        application = builder.build(config, stage_name='dev')
        event_sources = application.resources
        role = event_sources[1].lambda_function.role
        role.policy.document = {'Statement': []}
        injector = LambdaEventSourcePolicyInjector()
        injector.handle(config, event_sources[0])
        injector.handle(config, event_sources[1])
        # Even though we have two queue handlers, we only need to
        # inject the policy once.
        assert role.policy.document == {
            'Statement': [SQS_EVENT_SOURCE_POLICY.copy()],
        }

    def test_can_inject_policy_for_kinesis(self, sample_kinesis_event_app):
        config = Config.create(chalice_app=sample_kinesis_event_app,
                               autogen_policy=True,
                               project_dir='.')
        event_source = self.create_model_from_app(sample_kinesis_event_app,
                                                  config)
        role = event_source.lambda_function.role
        role.policy.document = {'Statement': []}
        injector = LambdaEventSourcePolicyInjector()
        injector.handle(config, event_source)
        assert role.policy.document == {
            'Statement': [KINESIS_EVENT_SOURCE_POLICY],
        }

    def test_can_inject_policy_for_ddb(self, sample_ddb_event_app):
        config = Config.create(chalice_app=sample_ddb_event_app,
                               autogen_policy=True,
                               project_dir='.')
        event_source = self.create_model_from_app(sample_ddb_event_app, config)
        role = event_source.lambda_function.role
        role.policy.document = {'Statement': []}
        injector = LambdaEventSourcePolicyInjector()
        injector.handle(config, event_source)
        assert role.policy.document == {
            'Statement': [DDB_EVENT_SOURCE_POLICY],
        }


class TestWebsocketPolicyInjector(object):
    def create_model_from_app(self, app, config):
        builder = ApplicationGraphBuilder()
        application = builder.build(config, stage_name='dev')
        return application.resources[0]

    def test_can_inject_policy(self, sample_websocket_app):
        config = Config.create(chalice_app=sample_websocket_app,
                               autogen_policy=True,
                               project_dir='.')
        event_source = self.create_model_from_app(
            sample_websocket_app, config)
        role = event_source.connect_function.role
        role.policy.document = {'Statement': []}
        injector = WebsocketPolicyInjector()
        injector.handle(config, event_source)
        assert role.policy.document == {
            'Statement': [POST_TO_WEBSOCKET_CONNECTION_POLICY.copy()],
        }

    def test_no_inject_if_not_autogen_policy(self, sample_websocket_app):
        config = Config.create(chalice_app=sample_websocket_app,
                               autogen_policy=False,
                               project_dir='.')
        event_source = self.create_model_from_app(sample_websocket_app, config)
        role = event_source.connect_function.role
        role.policy.document = {'Statement': []}
        injector = LambdaEventSourcePolicyInjector()
        injector.handle(config, event_source)
        assert role.policy.document == {'Statement': []}
