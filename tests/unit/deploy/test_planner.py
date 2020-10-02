import mock

import attr
import pytest
from typing import Tuple

from chalice.awsclient import TypedAWSClient, ResourceDoesNotExistError
from chalice.deploy import models
from chalice.config import DeployedResources
from chalice.utils import OSUtils
from chalice.deploy.planner import PlanStage, Variable, RemoteState, \
    KeyDataVariable
from chalice.deploy.planner import StringFormat
from chalice.deploy.models import APICall
from chalice.deploy.sweeper import ResourceSweeper


def create_function_resource(name, function_name=None,
                             environment_variables=None,
                             runtime='python2.7', handler='app.app',
                             tags=None, timeout=60,
                             memory_size=128, deployment_package=None,
                             role=None, layers=None, managed_layer=None):
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
        xray=None,
        deployment_package=deployment_package,
        role=role,
        security_group_ids=[],
        subnet_ids=[],
        layers=layers,
        reserved_concurrency=None,
        managed_layer=managed_layer,
    )


def create_managed_layer():
    layer = models.LambdaLayer(
        resource_name='layer',
        layer_name='bar',
        runtime='python2.7',
        deployment_package=models.DeploymentPackage(
            filename='foo')
    )
    return layer


def create_api_mapping():
    return models.APIMapping(
        resource_name='api_mapping',
        mount_path='(none)',
        api_gateway_stage='dev'
    )


def create_http_domain_name():
    return models.DomainName(
        protocol=models.APIType.HTTP,
        resource_name='api_gateway_custom_domain',
        domain_name='example.com',
        tls_version=models.TLSVersion.TLS_1_0,
        api_mapping=create_api_mapping(),
        certificate_arn='certificate_arn',
    )


def create_websocket_domain_name():
    return models.DomainName(
        protocol=models.APIType.WEBSOCKET,
        resource_name='websocket_api_custom_domain',
        domain_name='example.com',
        tls_version=models.TLSVersion.TLS_1_0,
        api_mapping=create_api_mapping(),
        certificate_arn='certificate_arn',
    )


@pytest.fixture
def no_deployed_values():
    return DeployedResources({'resources': [], 'schema_version': '2.0'})


class FakeConfig(object):
    def __init__(self, deployed_values):
        self._deployed_values = deployed_values
        self.chalice_stage = 'dev'
        self.api_gateway_stage = 'dev'

    def deployed_resources(self, chalice_stage_name):
        return DeployedResources(self._deployed_values)


class InMemoryRemoteState(object):
    def __init__(self, known_resources=None):
        if known_resources is None:
            known_resources = {}
        self.known_resources = known_resources
        self.deployed_values = {}

    def resource_exists(self, resource, *args):
        if resource.resource_type == 'api_mapping':
            return (
                (resource.resource_type, resource.mount_path)
                in self.known_resources
            )
        return (
            (resource.resource_type, resource.resource_name)
            in self.known_resources
        )

    def get_remote_model(self, resource):
        key = (resource.resource_type, resource.resource_name)
        return self.known_resources.get(key)

    def declare_resource_exists(self, resource, **deployed_values):
        key = (resource.resource_type, resource.resource_name)
        self.known_resources[key] = resource
        if deployed_values:
            deployed_values['name'] = resource.resource_name
            self.deployed_values[resource.resource_name] = deployed_values
            if resource.resource_type == 'domain_name':
                key = (resource.api_mapping.resource_type,
                       resource.api_mapping.mount_path)
                self.known_resources[key] = resource

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

    def filter_api_calls(self, plan):
        api_calls = []
        for instruction in plan:
            if isinstance(instruction, models.APICall):
                api_calls.append(instruction)
        return api_calls

    def assert_recorded_values(self, plan, resource_type, resource_name,
                               expected_mapping):
        actual = {}
        for step in plan:
            if isinstance(step, models.RecordResourceValue):
                actual[step.name] = step.value
            elif isinstance(step, models.RecordResourceVariable):
                actual[step.name] = Variable(step.variable_name)
        assert actual == expected_mapping


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
                    'trust_policy': Variable('lambda_trust_policy'),
                    'policy': {'iam': 'policy'}},
        )
        self.assert_apicall_equals(plan[4], expected)
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
                    'trust_policy': Variable('lambda_trust_policy'),
                    'policy': {'iam': 'policy'}},
        )
        self.assert_apicall_equals(plan[4], expected)
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


class TestPlanCreateUpdateAPIMapping(BasePlannerTests):
    def test_can_create_api_mapping(self, lambda_function):
        rest_api = models.RestAPI(
            resource_name='rest_api',
            swagger_doc={'swagger': '2.0'},
            minimum_compression='',
            api_gateway_stage='api',
            endpoint_type='EDGE',
            lambda_function=lambda_function,
            domain_name=create_http_domain_name()
        )

        self.remote_state.declare_no_resources_exists()
        plan = self.determine_plan(rest_api)
        params = {
            'domain_name': rest_api.domain_name.domain_name,
            'path_key': '(none)',
            'stage': 'dev',
            'api_id': Variable('rest_api_id')
        }
        expected = [
            models.APICall(
                method_name='create_base_path_mapping',
                params=params,
                output_var='base_path_mapping'
            ),
        ]
        # Create api mapping.
        self.assert_apicall_equals(plan[-3], expected[0])
        msg = 'Creating api mapping: /\n'
        assert list(self.last_plan.messages.values())[-1] == msg

    def test_can_create_websocket_api_mapping_with_path(self):
        domain_name = create_websocket_domain_name()
        domain_name.api_mapping.mount_path = 'path-key'

        connect_function = create_function_resource(
            'function_name_connect')
        message_function = create_function_resource(
            'function_name_message')
        disconnect_function = create_function_resource(
            'function_name_disconnect')

        websocket_api = models.WebsocketAPI(
            resource_name='websocket_api',
            name='app-dev-websocket-api',
            api_gateway_stage='api',
            routes=['$connect', '$default', '$disconnect'],
            connect_function=connect_function,
            message_function=message_function,
            disconnect_function=disconnect_function,
            domain_name=domain_name
        )

        self.remote_state.declare_no_resources_exists()
        plan = self.determine_plan(websocket_api)
        params = {
            'domain_name': domain_name.domain_name,
            'path_key': 'path-key',
            'stage': 'dev',
            'api_id': Variable('websocket_api_id')
        }
        expected = [
            models.APICall(
                method_name='create_api_mapping',
                params=params,
                output_var='api_mapping'
            ),
        ]
        # create api mapping
        self.assert_apicall_equals(plan[-3], expected[0])
        msg = 'Creating api mapping: /path-key\n'
        assert list(self.last_plan.messages.values())[-1] == msg

    def test_store_api_mapping_if_already_exists(self, lambda_function):
        domain_name = create_http_domain_name()
        domain_name.api_mapping.mount_path = 'test-path'
        rest_api = models.RestAPI(
            resource_name='rest_api',
            swagger_doc={'swagger': '2.0'},
            minimum_compression='',
            api_gateway_stage='api',
            endpoint_type='EDGE',
            lambda_function=lambda_function,
            domain_name=domain_name
        )

        deployed_value = {
            'name': 'api_gateway_custom_domain',
            'resource_type': 'domain_name',
            'hosted_zone_id': 'hosted_zone_id',
            'certificate_arn': 'certificate_arn',
            'security_policy': 'TLS_1_0',
            'domain_name': 'example.com',
            'api_mapping': [
                {
                    'key': '/test-path'
                },
                {
                    'key': '/test-path-2'
                }
            ]
        }

        self.remote_state.declare_resource_exists(domain_name,
                                                  **deployed_value)
        plan = self.determine_plan(rest_api)
        expected = [
            models.StoreMultipleValue(
                name='rest_api_mapping',
                value=[{
                    'key': '/test-path'
                }]
            )
        ]
        assert plan[-2].name == expected[0].name
        assert plan[-2].value == expected[0].value
        assert isinstance(expected[0], models.StoreMultipleValue)
        assert isinstance(plan[-2], models.StoreMultipleValue)

    def test_store_api_mapping_none_if_already_exists(self, lambda_function):
        domain_name = create_http_domain_name()
        domain_name.api_mapping.mount_path = '(none)'
        rest_api = models.RestAPI(
            resource_name='rest_api',
            swagger_doc={'swagger': '2.0'},
            minimum_compression='',
            api_gateway_stage='api',
            endpoint_type='EDGE',
            lambda_function=lambda_function,
            domain_name=domain_name
        )

        deployed_value = {
            'name': 'api_gateway_custom_domain',
            'resource_type': 'domain_name',
            'hosted_zone_id': 'hosted_zone_id',
            'certificate_arn': 'certificate_arn',
            'security_policy': 'TLS_1_0',
            'domain_name': 'example.com',
            'api_mapping': [
                {
                    'key': '/'
                },
            ]
        }

        self.remote_state.declare_resource_exists(domain_name,
                                                  **deployed_value)
        plan = self.determine_plan(rest_api)
        expected = [
            models.StoreMultipleValue(
                name='rest_api_mapping',
                value=[{
                    'key': '/'
                }]
            )
        ]
        assert plan[-2].name == expected[0].name
        assert plan[-2].value == expected[0].value
        assert isinstance(expected[0], models.StoreMultipleValue)
        assert isinstance(plan[-2], models.StoreMultipleValue)


class TestPlanCreateUpdateDomainName(BasePlannerTests):
    def test_can_create_domain_name(self, lambda_function):
        domain_name = create_http_domain_name()
        rest_api = models.RestAPI(
            resource_name='rest_api',
            swagger_doc={'swagger': '2.0'},
            minimum_compression='',
            api_gateway_stage='api',
            endpoint_type='EDGE',
            lambda_function=lambda_function,
            domain_name=domain_name
        )

        params = {
            'protocol': domain_name.protocol.value,
            'domain_name': domain_name.domain_name,
            'security_policy': domain_name.tls_version.value,
            'certificate_arn': domain_name.certificate_arn,
            'endpoint_type': 'EDGE',
            'tags': None
        }
        self.remote_state.declare_no_resources_exists()
        plan = self.determine_plan(rest_api)
        expected = [
            models.APICall(
                method_name='create_domain_name',
                params=params,
                output_var=domain_name.resource_name
            )
        ]
        # create domain name
        self.assert_apicall_equals(plan[13], expected[0])
        msg = 'Creating custom domain name: example.com\n'
        assert list(self.last_plan.messages.values())[-2] == msg

    def test_can_update_domain_name(self):
        deployed_value = {
            'name': 'rest_api_domain_name',
            'resource_type': 'domain_name',
            'hosted_zone_id': 'hosted_zone_id',
            'certificate_arn': 'certificate_arn',
            'security_policy': 'TLS_1_0',
            'domain_name': 'example.com',
        }
        domain_name = create_http_domain_name()
        domain_name.security_policy = 'TLS_1_2'
        domain_name.certificate_arn = 'certificate_arn_1'
        domain_name.hosted_zone_id = ' hosted_zone_1'

        params = {
            'protocol': domain_name.protocol.value,
            'domain_name': domain_name.domain_name,
            'security_policy': domain_name.tls_version.value,
            'certificate_arn': domain_name.certificate_arn,
            'endpoint_type': 'EDGE',
            'tags': None
        }
        self.remote_state.declare_resource_exists(
            domain_name, **deployed_value
        )
        planner = PlanStage(self.remote_state, self.osutils)

        plan = planner._add_domainname_plan(domain_name, 'EDGE')
        expected = [
            models.APICall(
                method_name='update_domain_name',
                params=params,
                output_var=domain_name.resource_name
            )
        ]
        # update domain name
        self.assert_apicall_equals(plan[0][0], expected[0])
        assert plan[0][1] == 'Updating custom domain name: example.com\n'


class TestPlanLambdaFunction(BasePlannerTests):

    def test_can_create_layer(self):
        layer = models.LambdaLayer(
            resource_name='layer',
            layer_name='bar',
            runtime='python2.7',
            deployment_package=models.DeploymentPackage(
                filename='foo')
        )
        plan = self.determine_plan(layer)
        expected = [models.APICall(
            method_name='publish_layer',
            params={
                'layer_name': 'bar',
                'zip_contents': mock.ANY,
                'runtime': 'python2.7'})
        ]
        self.assert_apicall_equals(plan[0], expected[0])
        assert list(self.last_plan.messages.values()) == [
            'Creating lambda layer: bar\n',
        ]

    def test_can_update_layer(self):
        layer = models.LambdaLayer(
            resource_name='layer',
            layer_name='bar',
            runtime='python2.7',
            deployment_package=models.DeploymentPackage(
                filename='foo')
        )
        copy_of_layer = attr.evolve(layer)
        self.remote_state.declare_resource_exists(
            copy_of_layer,
            layer_version_arn='arn:bar:4'
        )

        plan = self.determine_plan(layer)
        expected = [
            models.APICall(
                method_name='delete_layer_version',
                params={'layer_version_arn': 'arn:bar:4'}),
            models.APICall(
                method_name='publish_layer',
                params={
                    'layer_name': 'bar',
                    'zip_contents': mock.ANY,
                    'runtime': 'python2.7'}),
            models.RecordResourceVariable(
                resource_type='lambda_layer',
                resource_name='layer',
                name='layer_version_arn',
                variable_name='layer_version_arn')
        ]
        assert len(plan) == 3
        assert plan[0] == expected[0]
        assert plan[2] == expected[2]
        self.assert_apicall_equals(plan[1], expected[1])
        assert list(self.last_plan.messages.values()) == [
            'Updating lambda layer: bar\n',
        ]

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
                'xray': None,
                'timeout': 60,
                'memory_size': 128,
                'security_group_ids': [],
                'subnet_ids': [],
                'layers': [],
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
        function = create_function_resource(
            'function_name', layers=layers,
            managed_layer=create_managed_layer()
        )
        self.remote_state.declare_no_resources_exists()
        plan = self.filter_api_calls(
            self.determine_plan(function.managed_layer))
        plan.extend(self.filter_api_calls(self.determine_plan(function)))
        expected = [models.APICall(
            method_name='publish_layer',
            params={
                'layer_name': 'bar',
                'zip_contents': mock.ANY,
                'runtime': 'python2.7'}
        ),
            models.APICall(
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
                'xray': None,
                'memory_size': 128,
                'security_group_ids': [],
                'subnet_ids': [],
                'layers': [Variable('layer_version_arn')] + layers
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
        self.assert_apicall_equals(plan[1], expected[1])

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
            'xray': None,
            'tags': {},
            'timeout': 60,
            'security_group_ids': [],
            'subnet_ids': [],
            'layers': [],
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

    def test_can_update_lambda_function_with_managed_layer(self):
        function = create_function_resource(
            'function_name',
            managed_layer=create_managed_layer(),
        )
        copy_of_function = attr.evolve(function)
        self.remote_state.declare_resource_exists(copy_of_function)
        copy_of_layer = attr.evolve(function.managed_layer)
        self.remote_state.declare_resource_exists(
            copy_of_layer,
            layer_version_arn='arn:bar:4'
        )
        plan = self.determine_plan(function.managed_layer)
        plan.extend(self.determine_plan(function))
        self.assert_apicall_equals(plan[0], models.APICall(
            method_name='delete_layer_version',
            params={'layer_version_arn': 'arn:bar:4'},
        ))
        assert plan[3].method_name == 'update_function'
        assert plan[3].params['layers'] == [Variable('layer_version_arn')]

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
                'xray': None,
                'timeout': 60,
                'memory_size': 128,
                'security_group_ids': [],
                'subnet_ids': [],
                'layers': [],
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


class TestPlanCloudWatchEvent(BasePlannerTests):

    def test_can_plan_cloudwatch_event(self):
        function = create_function_resource('function_name')
        event = models.CloudWatchEvent(
            resource_name='bar',
            rule_name='myrulename',
            event_pattern='"source": ["aws.ec2"]',
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
                    'event_pattern': '"source": ["aws.ec2"]'
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
                method_name='add_permission_for_cloudwatch_event',
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


class TestPlanScheduledEvent(BasePlannerTests):
    def test_can_plan_scheduled_event(self):
        function = create_function_resource('function_name')
        event = models.ScheduledEvent(
            resource_name='bar',
            rule_name='myrulename',
            rule_description="my rule description",
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
                    'rule_description': 'my rule description',
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
                method_name='add_permission_for_cloudwatch_event',
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

    def test_can_plan_scheduled_event_can_omit_description(self):
        function = create_function_resource('function_name')
        event = models.ScheduledEvent(
            resource_name='bar',
            rule_name='myrulename',
            schedule_expression='rate(5 minutes)',
            lambda_function=function,
        )
        plan = self.determine_plan(event)
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


class TestPlanWebsocketAPI(BasePlannerTests):
    def assert_loads_needed_variables(self, plan):
        # Parse arn and store region/account id for future
        # API calls.
        assert plan[0:5] == [
            models.BuiltinFunction(
                'parse_arn', [Variable('function_name_connect_lambda_arn')],
                output_var='parsed_lambda_arn',
            ),
            models.JPSearch('account_id',
                            input_var='parsed_lambda_arn',
                            output_var='account_id'),
            models.JPSearch('region',
                            input_var='parsed_lambda_arn',
                            output_var='region_name'),
            models.JPSearch('partition',
                            input_var='parsed_lambda_arn',
                            output_var='partition'),
            models.JPSearch('dns_suffix',
                            input_var='parsed_lambda_arn',
                            output_var='dns_suffix'),
        ]

    def test_can_plan_websocket_api(self):
        connect_function = create_function_resource(
            'function_name_connect')
        message_function = create_function_resource(
            'function_name_message')
        disconnect_function = create_function_resource(
            'function_name_disconnect')
        websocket_api = models.WebsocketAPI(
            resource_name='websocket_api',
            name='app-dev-websocket-api',
            api_gateway_stage='api',
            routes=['$connect', '$default', '$disconnect'],
            connect_function=connect_function,
            message_function=message_function,
            disconnect_function=disconnect_function,
        )
        plan = self.determine_plan(websocket_api)
        self.assert_loads_needed_variables(plan)
        assert plan[5:] == [
            models.APICall(
                method_name='create_websocket_api',
                params={'name': 'app-dev-websocket-api'},
                output_var='websocket_api_id',
            ),
            models.StoreValue(
                name='routes',
                value=[],
            ),
            models.StoreValue(
                name='websocket-connect-integration-lambda-path',
                value=StringFormat(
                    'arn:{partition}:apigateway:{region_name}:lambda:path/'
                    '2015-03-31/functions/arn:{partition}:lambda'
                    ':{region_name}:{account_id}:function:%s/'
                    'invocations' % 'appname-dev-function_name_connect',
                    ['partition', 'region_name', 'account_id'],
                ),
            ),
            models.APICall(
                method_name='create_websocket_integration',
                params={
                    'api_id': Variable('websocket_api_id'),
                    'lambda_function': Variable(
                        'websocket-connect-integration-lambda-path'),
                    'handler_type': 'connect',
                },
                output_var='connect-integration-id',
            ),
            models.StoreValue(
                name='websocket-message-integration-lambda-path',
                value=StringFormat(
                    'arn:{partition}:apigateway:{region_name}:lambda:path/'
                    '2015-03-31/functions/arn:{partition}:lambda'
                    ':{region_name}:{account_id}:function:%s/'
                    'invocations' % 'appname-dev-function_name_message',
                    ['partition', 'region_name', 'account_id'],
                ),
            ),
            models.APICall(
                method_name='create_websocket_integration',
                params={
                    'api_id': Variable('websocket_api_id'),
                    'lambda_function': Variable(
                        'websocket-message-integration-lambda-path'),
                    'handler_type': 'message',
                },
                output_var='message-integration-id',
            ),
            models.StoreValue(
                name='websocket-disconnect-integration-lambda-path',
                value=StringFormat(
                    'arn:{partition}:apigateway:{region_name}:lambda:path/'
                    '2015-03-31/functions/arn:{partition}:lambda'
                    ':{region_name}:{account_id}:function:%s/'
                    'invocations' % 'appname-dev-function_name_disconnect',
                    ['partition', 'region_name', 'account_id'],
                ),
            ),
            models.APICall(
                method_name='create_websocket_integration',
                params={
                    'api_id': Variable('websocket_api_id'),
                    'lambda_function': Variable(
                        'websocket-disconnect-integration-lambda-path'),
                    'handler_type': 'disconnect',
                },
                output_var='disconnect-integration-id',
            ),
            models.APICall(
                method_name='create_websocket_route',
                params={
                    'api_id': Variable('websocket_api_id'),
                    'route_key': '$connect',
                    'integration_id': Variable('connect-integration-id'),
                },
            ),
            models.APICall(
                method_name='create_websocket_route',
                params={
                    'api_id': Variable('websocket_api_id'),
                    'route_key': '$default',
                    'integration_id': Variable('message-integration-id'),
                },
            ),
            models.APICall(
                method_name='create_websocket_route',
                params={
                    'api_id': Variable('websocket_api_id'),
                    'route_key': '$disconnect',
                    'integration_id': Variable('disconnect-integration-id'),
                },
            ),
            models.APICall(
                method_name='deploy_websocket_api',
                params={
                    'api_id': Variable('websocket_api_id'),
                },
                output_var='deployment-id',
            ),
            models.APICall(
                method_name='create_stage',
                params={
                    'api_id': Variable('websocket_api_id'),
                    'stage_name': 'api',
                    'deployment_id': Variable('deployment-id'),
                }
            ),
            models.StoreValue(
                name='websocket_api_url',
                value=StringFormat(
                    'wss://{websocket_api_id}.execute-api.{region_name}'
                    '.{dns_suffix}/%s/' % 'api',
                    ['websocket_api_id', 'region_name', 'dns_suffix'],
                ),
            ),
            models.RecordResourceVariable(
                resource_type='websocket_api',
                resource_name='websocket_api',
                name='websocket_api_url',
                variable_name='websocket_api_url',
            ),
            models.RecordResourceVariable(
                resource_type='websocket_api',
                resource_name='websocket_api',
                name='websocket_api_id',
                variable_name='websocket_api_id',
            ),
            models.APICall(
                method_name='add_permission_for_apigateway_v2',
                params={'function_name': 'appname-dev-function_name_connect',
                        'region_name': Variable('region_name'),
                        'account_id': Variable('account_id'),
                        'api_id': Variable('websocket_api_id')},
            ),
            models.APICall(
                method_name='add_permission_for_apigateway_v2',
                params={'function_name': 'appname-dev-function_name_message',
                        'region_name': Variable('region_name'),
                        'account_id': Variable('account_id'),
                        'api_id': Variable('websocket_api_id')},
            ),
            models.APICall(
                method_name='add_permission_for_apigateway_v2',
                params={
                    'function_name': 'appname-dev-function_name_disconnect',
                    'region_name': Variable('region_name'),
                    'account_id': Variable('account_id'),
                    'api_id': Variable('websocket_api_id')},
            ),
        ]

    def test_can_update_websocket_api(self):
        connect_function = create_function_resource(
            'function_name_connect')
        message_function = create_function_resource(
            'function_name_message')
        disconnect_function = create_function_resource(
            'function_name_disconnect')
        websocket_api = models.WebsocketAPI(
            resource_name='websocket_api',
            name='app-dev-websocket-api',
            api_gateway_stage='api',
            routes=['$connect', '$default', '$disconnect'],
            connect_function=connect_function,
            message_function=message_function,
            disconnect_function=disconnect_function,
        )
        self.remote_state.declare_resource_exists(websocket_api)
        self.remote_state.deployed_values['websocket_api'] = {
            'websocket_api_id': 'my_websocket_api_id',
        }
        plan = self.determine_plan(websocket_api)
        self.assert_loads_needed_variables(plan)
        assert plan[5:] == [
            models.StoreValue(
                name='websocket_api_id',
                value='my_websocket_api_id',
            ),
            models.APICall(
                method_name='get_websocket_routes',
                params={'api_id': Variable('websocket_api_id')},
                output_var='routes',
            ),
            models.APICall(
                method_name='delete_websocket_routes',
                params={'api_id': Variable('websocket_api_id'),
                        'routes': Variable('routes')},
            ),
            models.APICall(
                method_name='get_websocket_integrations',
                params={'api_id': Variable('websocket_api_id')},
                output_var='integrations',
            ),
            models.APICall(
                method_name='delete_websocket_integrations',
                params={'api_id': Variable('websocket_api_id'),
                        'integrations': Variable('integrations')},
            ),
            models.StoreValue(
                name='websocket-connect-integration-lambda-path',
                value=StringFormat(
                    'arn:{partition}:apigateway:{region_name}:lambda:path/'
                    '2015-03-31/functions/arn:{partition}:lambda'
                    ':{region_name}:{account_id}:function:%s/'
                    'invocations' % 'appname-dev-function_name_connect',
                    ['partition', 'region_name', 'account_id'],
                ),
            ),
            models.APICall(
                method_name='create_websocket_integration',
                params={
                    'api_id': Variable('websocket_api_id'),
                    'lambda_function': Variable(
                        'websocket-connect-integration-lambda-path'),
                    'handler_type': 'connect',
                },
                output_var='connect-integration-id',
            ),
            models.StoreValue(
                name='websocket-message-integration-lambda-path',
                value=StringFormat(
                    'arn:{partition}:apigateway:{region_name}:lambda:path/'
                    '2015-03-31/functions/arn:{partition}:lambda'
                    ':{region_name}:{account_id}:function:%s/'
                    'invocations' % 'appname-dev-function_name_message',
                    ['partition', 'region_name', 'account_id'],
                ),
            ),
            models.APICall(
                method_name='create_websocket_integration',
                params={
                    'api_id': Variable('websocket_api_id'),
                    'lambda_function': Variable(
                        'websocket-message-integration-lambda-path'),
                    'handler_type': 'message',
                },
                output_var='message-integration-id',
            ),
            models.StoreValue(
                name='websocket-disconnect-integration-lambda-path',
                value=StringFormat(
                    'arn:{partition}:apigateway:{region_name}:lambda:path/'
                    '2015-03-31/functions/arn:{partition}:lambda'
                    ':{region_name}:{account_id}:function:%s/'
                    'invocations' % 'appname-dev-function_name_disconnect',
                    ['partition', 'region_name', 'account_id'],
                ),
            ),
            models.APICall(
                method_name='create_websocket_integration',
                params={
                    'api_id': Variable('websocket_api_id'),
                    'lambda_function': Variable(
                        'websocket-disconnect-integration-lambda-path'),
                    'handler_type': 'disconnect',
                },
                output_var='disconnect-integration-id',
            ),
            models.APICall(
                method_name='create_websocket_route',
                params={
                    'api_id': Variable('websocket_api_id'),
                    'route_key': '$connect',
                    'integration_id': Variable('connect-integration-id'),
                },
            ),
            models.APICall(
                method_name='create_websocket_route',
                params={
                    'api_id': Variable('websocket_api_id'),
                    'route_key': '$default',
                    'integration_id': Variable('message-integration-id'),
                },
            ),
            models.APICall(
                method_name='create_websocket_route',
                params={
                    'api_id': Variable('websocket_api_id'),
                    'route_key': '$disconnect',
                    'integration_id': Variable('disconnect-integration-id'),
                },
            ),
            models.StoreValue(
                name='websocket_api_url',
                value=StringFormat(
                    'wss://{websocket_api_id}.execute-api.{region_name}'
                    '.{dns_suffix}/%s/' % 'api',
                    ['websocket_api_id', 'region_name', 'dns_suffix'],
                ),
            ),
            models.RecordResourceVariable(
                resource_type='websocket_api',
                resource_name='websocket_api',
                name='websocket_api_url',
                variable_name='websocket_api_url',
            ),
            models.RecordResourceVariable(
                resource_type='websocket_api',
                resource_name='websocket_api',
                name='websocket_api_id',
                variable_name='websocket_api_id',
            ),
            models.APICall(
                method_name='add_permission_for_apigateway_v2',
                params={'function_name': 'appname-dev-function_name_connect',
                        'region_name': Variable('region_name'),
                        'account_id': Variable('account_id'),
                        'api_id': Variable('websocket_api_id')},
            ),
            models.APICall(
                method_name='add_permission_for_apigateway_v2',
                params={'function_name': 'appname-dev-function_name_message',
                        'region_name': Variable('region_name'),
                        'account_id': Variable('account_id'),
                        'api_id': Variable('websocket_api_id')},
            ),
            models.APICall(
                method_name='add_permission_for_apigateway_v2',
                params={
                    'function_name': 'appname-dev-function_name_disconnect',
                    'region_name': Variable('region_name'),
                    'account_id': Variable('account_id'),
                    'api_id': Variable('websocket_api_id'),
                },
            ),
        ]


class TestPlanRestAPI(BasePlannerTests):
    def assert_loads_needed_variables(self, plan):
        # Parse arn and store region/account id for future
        # API calls.
        assert plan[0:6] == [
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
            models.JPSearch('partition',
                            input_var='parsed_lambda_arn',
                            output_var='partition'),
            models.JPSearch('dns_suffix',
                            input_var='parsed_lambda_arn',
                            output_var='dns_suffix'),
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
            endpoint_type='EDGE',
            minimum_compression='100',
            api_gateway_stage='api',
            xray=False,
            lambda_function=function,
        )
        plan = self.determine_plan(rest_api)
        self.assert_loads_needed_variables(plan)

        assert plan[6:] == [
            models.APICall(
                method_name='import_rest_api',
                params={'swagger_document': {'swagger': '2.0'},
                        'endpoint_type': 'EDGE'},
                output_var='rest_api_id',
            ),
            models.RecordResourceVariable(
                resource_type='rest_api',
                resource_name='rest_api',
                name='rest_api_id',
                variable_name='rest_api_id',
            ),
            models.APICall(
                method_name='update_rest_api',
                params={
                    'rest_api_id': Variable('rest_api_id'),
                    'patch_operations': [{
                        'op': 'replace',
                        'path': '/minimumCompressionSize',
                        'value': '100',
                    }],
                }
            ),
            models.APICall(
                method_name='add_permission_for_apigateway',
                params={
                    'function_name': 'appname-dev-function_name',
                    'region_name': Variable('region_name'),
                    'account_id': Variable('account_id'),
                    'rest_api_id': Variable('rest_api_id'),
                }
            ),
            models.APICall(method_name='deploy_rest_api',
                           params={'rest_api_id': Variable('rest_api_id'),
                                   'xray': False,
                                   'api_gateway_stage': 'api'}),
            models.StoreValue(
                name='rest_api_url',
                value=StringFormat(
                    'https://{rest_api_id}.execute-api.{region_name}'
                    '.{dns_suffix}/api/',
                    ['rest_api_id', 'region_name', 'dns_suffix'],
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

    def test_can_update_rest_api_with_policy(self):
        function = create_function_resource('function_name')
        rest_api = models.RestAPI(
            resource_name='rest_api',
            swagger_doc={'swagger': '2.0'},
            minimum_compression='',
            api_gateway_stage='api',
            endpoint_type='EDGE',
            policy="{'Statement': []}",
            lambda_function=function,
        )
        self.remote_state.declare_resource_exists(rest_api)
        self.remote_state.deployed_values['rest_api'] = {
            'rest_api_id': 'my_rest_api_id',
        }
        plan = self.determine_plan(rest_api)

        assert plan[10].params == {
            'patch_operations': [
                {'op': 'replace',
                 'path': '/minimumCompressionSize',
                 'value': ''},
                {'op': 'replace',
                 'path': StringFormat(
                     ("/endpointConfiguration/types/"
                      "{rest_api[endpointConfiguration][types][0]}"),
                     ['rest_api']),
                 'value': 'EDGE'}
            ],
            'rest_api_id': Variable("rest_api_id")
        }

    def test_can_update_rest_api(self):
        function = create_function_resource('function_name')
        rest_api = models.RestAPI(
            resource_name='rest_api',
            swagger_doc={'swagger': '2.0'},
            minimum_compression='',
            api_gateway_stage='api',
            endpoint_type='REGIONAL',
            xray=False,
            lambda_function=function,
        )
        self.remote_state.declare_resource_exists(rest_api)
        self.remote_state.deployed_values['rest_api'] = {
            'rest_api_id': 'my_rest_api_id',
        }
        plan = self.determine_plan(rest_api)
        self.assert_loads_needed_variables(plan)

        assert plan[6:] == [
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
                method_name='get_rest_api',
                params={'rest_api_id': Variable('rest_api_id')},
                output_var='rest_api'
            ),
            models.APICall(
                method_name='update_rest_api',
                params={
                    'rest_api_id': Variable('rest_api_id'),
                    'patch_operations': [{
                        'op': 'replace',
                        'path': '/minimumCompressionSize',
                        'value': ''},
                        {'op': 'replace',
                         'value': 'REGIONAL',
                         'path': StringFormat(
                             '/endpointConfiguration/types/%s' % (
                                '{rest_api[endpointConfiguration][types][0]}'),
                             ['rest_api'])},
                    ],
                },
            ),
            models.APICall(
                method_name='add_permission_for_apigateway',
                params={'rest_api_id': Variable("rest_api_id"),
                        'region_name': Variable("region_name"),
                        'account_id': Variable("account_id"),
                        'function_name': 'appname-dev-function_name'},
                output_var=None),
            models.APICall(
                method_name='deploy_rest_api',
                params={'rest_api_id': Variable('rest_api_id'),
                        'xray': False,
                        'api_gateway_stage': 'api'},
            ),
            models.StoreValue(
                name='rest_api_url',
                value=StringFormat(
                    'https://{rest_api_id}.execute-api.{region_name}'
                    '.{dns_suffix}/api/',
                    ['rest_api_id', 'region_name', 'dns_suffix'],
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
        plan_parse_arn = plan[:5]
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
            models.JPSearch(
                expression='partition',
                input_var='parsed_lambda_arn',
                output_var='partition'),
            models.StoreValue(
                name='function_name-sns-subscription_topic_arn',
                value=StringFormat(
                    "arn:{partition}:sns:{region_name}:{account_id}:mytopic",
                    variables=['partition', 'region_name', 'account_id'],
                )
            ),
        ]
        topic_arn_var = Variable("function_name-sns-subscription_topic_arn")
        assert plan[5:7] == [
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
        ]
        self.assert_recorded_values(
            plan, 'sns_event', 'function_name-sns-subscription', {
                'topic': 'mytopic',
                'lambda_arn': Variable('function_name_lambda_arn'),
                'subscription_arn': Variable(
                    'function_name-sns-subscription_subscription_arn'),
                'topic_arn': Variable(
                    'function_name-sns-subscription_topic_arn'),
            }
        )

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
        assert plan[1:3] == [
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
        ]
        self.assert_recorded_values(
            plan, 'sns_event', 'function_name-sns-subscription', {
                'topic': topic_arn,
                'lambda_arn': Variable('function_name_lambda_arn'),
                'subscription_arn': Variable(
                    'function_name-sns-subscription_subscription_arn'),
                'topic_arn': Variable(
                    'function_name-sns-subscription_topic_arn'),
            }
        )

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
        plan_parse_arn = plan[:5]
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
            models.JPSearch(
                expression='partition',
                input_var='parsed_lambda_arn',
                output_var='partition'),
            models.StoreValue(
                name='function_name-sns-subscription_topic_arn',
                value=StringFormat(
                    "arn:{partition}:sns:{region_name}:{account_id}:mytopic",
                    variables=['partition', 'region_name', 'account_id'],
                )
            ),
        ]
        self.assert_recorded_values(
            plan, 'sns_event', 'function_name-sns-subscription', {
                'topic': 'mytopic',
                'lambda_arn': Variable('function_name_lambda_arn'),
                'subscription_arn': 'arn:aws:subscribe',
                'topic_arn': Variable(
                    'function_name-sns-subscription_topic_arn'),
            }
        )


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
        plan_parse_arn = plan[:5]
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
            models.JPSearch(
                expression='partition',
                input_var='parsed_lambda_arn',
                output_var='partition'
            ),
            models.StoreValue(
                name='function_name-sqs-event-source_queue_arn',
                value=StringFormat(
                    "arn:{partition}:sqs:{region_name}:{account_id}:myqueue",
                    variables=['partition', 'region_name', 'account_id'],
                ),
            )
        ]
        assert plan[5] == models.APICall(
            method_name='create_lambda_event_source',
            params={
                'event_source_arn': Variable(
                    "function_name-sqs-event-source_queue_arn"
                ),
                'batch_size': 10,
                'function_name': Variable("function_name_lambda_arn")
            },
            output_var='function_name-sqs-event-source_uuid'
        )
        self.assert_recorded_values(
            plan, 'sqs_event', 'function_name-sqs-event-source', {
                'queue_arn': Variable(
                    'function_name-sqs-event-source_queue_arn'),
                'event_uuid': Variable(
                    'function_name-sqs-event-source_uuid'),
                'queue': 'myqueue',
                'lambda_arn': Variable(
                    'function_name_lambda_arn')
            }
        )

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
        plan_parse_arn = plan[:5]
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
            models.JPSearch(
                expression='partition',
                input_var='parsed_lambda_arn',
                output_var='partition'
            ),
            models.StoreValue(
                name='function_name-sqs-event-source_queue_arn',
                value=StringFormat(
                    "arn:{partition}:sqs:{region_name}:{account_id}:myqueue",
                    variables=['partition', 'region_name', 'account_id'],
                ),
            )
        ]
        assert plan[5] == models.APICall(
            method_name='update_lambda_event_source',
            params={
                'event_uuid': 'my-uuid',
                'batch_size': 10,
            },
        )
        self.assert_recorded_values(
            plan, 'sqs_event', 'function_name-sqs-event-source', {
                'queue_arn': 'arn:sqs:myqueue',
                'event_uuid': 'my-uuid',
                'queue': 'myqueue',
                'lambda_arn': 'arn:lambda'
            }
        )

    @pytest.mark.parametrize('functions,integration_injected', [
        (
            (create_function_resource('connect'), None, None),
            'connect'
        ),
        (
            (None, create_function_resource('message'), None),
            'message'
        ),
        (
            (None, None, create_function_resource('disconnect')),
            'disconnect'
        ),
    ])
    def test_websocket_api_plan_omits_unused_lambdas(
            self, functions, integration_injected):
        websocket_api = models.WebsocketAPI(
            resource_name='websocket_api',
            name='app-dev-websocket-api',
            api_gateway_stage='api',
            routes=['$connect', '$default', '$disconnect'],
            connect_function=functions[0],
            message_function=functions[1],
            disconnect_function=functions[2],
        )
        plan = self.determine_plan(websocket_api)
        integrations = [
            code.params['handler_type'] for code in plan
            if isinstance(code, APICall)
            and code.method_name == 'create_websocket_integration'
        ]

        assert len(integrations) == 1
        assert integrations[0] == integration_injected


class TestPlanKinesisSubscription(BasePlannerTests):
    def test_can_plan_kinesis_event_source(self):
        function = create_function_resource('function_name')
        kinesis_event_source = models.KinesisEventSource(
            resource_name='function_name-kinesis-event-source',
            stream='mystream',
            batch_size=10,
            starting_position='LATEST',
            lambda_function=function
        )
        plan = self.determine_plan(kinesis_event_source)
        plan_parse_arn = plan[:5]
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
            models.JPSearch(
                expression='partition',
                input_var='parsed_lambda_arn',
                output_var='partition'
            ),
            models.StoreValue(
                name='function_name-kinesis-event-source_stream_arn',
                value=StringFormat(
                    ("arn:{partition}:kinesis:{region_name}:{account_id}:"
                     "stream/mystream"),
                    variables=['partition', 'region_name', 'account_id'],
                ),
            )
        ]
        assert plan[5] == models.APICall(
            method_name='create_lambda_event_source',
            params={
                'event_source_arn': Variable(
                    "function_name-kinesis-event-source_stream_arn"
                ),
                'batch_size': 10,
                'starting_position': 'LATEST',
                'function_name': Variable("function_name_lambda_arn")
            },
            output_var='function_name-kinesis-event-source_uuid'
        )
        self.assert_recorded_values(
            plan, 'kinesis_event', 'function_name-kinesis-event-source', {
                'kinesis_arn': Variable(
                    'function_name-kinesis-event-source_stream_arn'),
                'event_uuid': Variable(
                    'function_name-kinesis-event-source_uuid'),
                'stream': 'mystream',
                'lambda_arn': Variable(
                    'function_name_lambda_arn')
            }
        )

    def test_can_update_kinesis_event_source(self):
        function = create_function_resource('function_name')
        kinesis_event_source = models.KinesisEventSource(
            resource_name='function_name-kinesis-event-source',
            stream='mystream',
            batch_size=10,
            starting_position='LATEST',
            lambda_function=function
        )
        self.remote_state.declare_resource_exists(
            kinesis_event_source,
            stream='mystream',
            kinesis_arn='arn:aws:kinesis:stream',
            resource_type='kinesis_event',
            lambda_arn='arn:lambda',
            event_uuid='my-uuid',
        )
        plan = self.determine_plan(kinesis_event_source)
        assert plan[5] == models.APICall(
            method_name='update_lambda_event_source',
            params={
                'event_uuid': 'my-uuid',
                'batch_size': 10,
            }
        )


class TestPlanDynamoDBSubscription(BasePlannerTests):
    def test_can_plan_dynamodb_event_source(self):
        function = create_function_resource('function_name')
        event_source = models.DynamoDBEventSource(
            resource_name='handler-dynamodb-event-source',
            stream_arn='arn:stream', batch_size=100,
            starting_position='LATEST', lambda_function=function)
        plan = self.determine_plan(event_source)
        assert plan[0] == models.APICall(
            method_name='create_lambda_event_source',
            params={
                'event_source_arn': 'arn:stream',
                'batch_size': 100,
                'function_name': Variable('function_name_lambda_arn'),
                'starting_position': 'LATEST',
            },
            output_var='handler-dynamodb-event-source_uuid',
        )

    def test_can_plan_dynamodb_event_source_update(self):
        function = create_function_resource('function_name')
        event_source = models.DynamoDBEventSource(
            resource_name='handler-dynamodb-event-source',
            stream_arn='arn:stream', batch_size=100,
            starting_position='LATEST', lambda_function=function)
        self.remote_state.declare_resource_exists(
            event_source,
            stream_arn='arn:stream',
            resource_type='dynamodb_event',
            lambda_arn='arn:lambda',
            event_uuid='my-uuid',
        )
        plan = self.determine_plan(event_source)
        assert plan[0] == models.APICall(
            method_name='update_lambda_event_source',
            params={
                'event_uuid': 'my-uuid',
                'batch_size': 100,
            },
        )


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
            minimum_compression='',
            endpoint_type='EDGE',
            api_gateway_stage='api',
            xray=False,
            lambda_function=None,
        )
        return rest_api

    def create_api_mapping(self):
        api_mapping = models.APIMapping(
            resource_name='api_mapping',
            mount_path='(none)',
            api_gateway_stage='dev'
        )
        return api_mapping

    def create_domain_name(self):
        domain_name = models.DomainName(
            protocol=models.APIType.HTTP,
            resource_name='api_gateway_custom_domain',
            domain_name='example.com',
            tls_version=models.TLSVersion.TLS_1_0,
            certificate_arn='certificate_arn',
            api_mapping=self.create_api_mapping()
        )
        return domain_name

    def create_websocket_api_model(self):
        websocket_api = models.WebsocketAPI(
            resource_name='websocket_api',
            name='app-stage-websocket-api',
            api_gateway_stage='api',
            routes=[],
            connect_function=None,
            message_function=None,
            disconnect_function=None,
        )
        return websocket_api

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

    def test_lambda_layer_not_exists(self):
        layer = models.LambdaLayer(
            resource_name='layer',
            layer_name='bar',
            runtime='python2.7',
            deployment_package=models.DeploymentPackage(
                filename='foo')
        )
        assert not self.remote_state.resource_exists(layer)

    def test_lambda_layer_exists(self):
        layer = models.LambdaLayer(
            resource_name='layer',
            layer_name='bar',
            runtime='python2.7',
            deployment_package=models.DeploymentPackage(
                filename='foo')
        )
        deployed_resources = {
            'resources': [{
                'name': 'layer',
                'resource_type': 'lambda_layer',
                'layer_version_arn': 'arn:layer:4'
            }]
        }
        self.client.get_layer_version.return_value = {
            'LayerVersionArn': 'arn:layer:4'}
        remote_state = RemoteState(
            self.client, DeployedResources(deployed_resources))
        assert remote_state.resource_exists(layer)

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

    def test_api_gateway_domain_name_exists(self):
        domain_name = self.create_domain_name()
        self.client.domain_name_exists.return_value = True
        assert self.remote_state.resource_exists(domain_name)

    def test_websocket_domain_name_exists(self):
        domain_name = self.create_domain_name()
        domain_name.protocol = models.APIType.WEBSOCKET
        domain_name.resource_name = 'websocket_api_custom_domain'
        self.client.domain_name_exists_v2.return_value = True
        assert self.remote_state.resource_exists(domain_name)

    def test_none_api_mapping_exists(self):
        api_mapping = self.create_api_mapping()
        self.client.api_mapping_exists.return_value = True
        assert self.remote_state.resource_exists(api_mapping, 'domain_name')

    def test_path_api_mapping_exists_with_slash(self):
        api_mapping = self.create_api_mapping()
        api_mapping.mount_path = '/path'
        self.client.api_mapping_exists.return_value = True
        assert self.remote_state.resource_exists(api_mapping, 'domain_name')

    def test_path_api_mapping_exists(self):
        api_mapping = self.create_api_mapping()
        api_mapping.mount_path = 'path'
        self.client.api_mapping_exists.return_value = True
        assert self.remote_state.resource_exists(api_mapping, 'domain_name')

    def test_domain_name_does_not_exist(self):
        domain_name = self.create_domain_name()
        self.client.domain_name_exists.return_value = False
        assert not self.remote_state.resource_exists(domain_name)

        domain_name.protocol = models.APIType.WEBSOCKET
        domain_name.resource_name = 'websocket_api_custom_domain'
        self.client.domain_name_exists_v2.return_value = False
        assert not self.remote_state.resource_exists(domain_name)

    def test_exists_check_is_cached(self):
        function = create_function_resource('function-name')
        self.client.lambda_function_exists.return_value = True
        assert self.remote_state.resource_exists(function)
        # Now if we call this method repeatedly we should only invoke
        # the underlying client method once.  Subsequent calls are cached.
        assert self.remote_state.resource_exists(function)
        assert self.remote_state.resource_exists(function)

        assert self.client.lambda_function_exists.call_count == 1

    def test_exists_check_is_cached_api_mapping(self):
        api_mapping = models.APIMapping(
            resource_name='api_mapping',
            mount_path='(none)',
            api_gateway_stage='dev'
        )
        self.client.api_mapping_exists.return_value = True
        assert self.remote_state.resource_exists(api_mapping, 'domain_name')
        assert self.remote_state.resource_exists(api_mapping, 'domain_name')
        assert self.remote_state.resource_exists(api_mapping, 'domain_name')

    def test_rest_api_exists_no_deploy(self, no_deployed_values):
        rest_api = self.create_rest_api_model()
        remote_state = RemoteState(
            self.client, no_deployed_values)
        assert not remote_state.resource_exists(rest_api)
        assert not self.client.get_rest_api.called

    def test_rest_api_exists_with_existing_deploy(self):
        rest_api = self.create_rest_api_model()
        deployed_resources = {
            'resources': [{
                'name': 'rest_api',
                'resource_type': 'rest_api',
                'rest_api_id': 'my_rest_api_id',
            }]
        }
        self.client.get_rest_api.return_value = {'apiId': 'my_rest_api_id'}
        remote_state = RemoteState(
            self.client, DeployedResources(deployed_resources))
        assert remote_state.resource_exists(rest_api)
        self.client.get_rest_api.assert_called_with('my_rest_api_id')

    def test_rest_api_not_exists_with_preexisting_deploy(self):
        rest_api = self.create_rest_api_model()
        deployed_resources = {
            'resources': [{
                'name': 'rest_api',
                'resource_type': 'rest_api',
                'rest_api_id': 'my_rest_api_id',
            }]
        }
        self.client.get_rest_api.return_value = {}
        remote_state = RemoteState(
            self.client, DeployedResources(deployed_resources))
        assert not remote_state.resource_exists(rest_api)
        self.client.get_rest_api.assert_called_with('my_rest_api_id')

    def test_websocket_api_exists_no_deploy(self, no_deployed_values):
        rest_api = self.create_websocket_api_model()
        remote_state = RemoteState(
            self.client, no_deployed_values)
        assert not remote_state.resource_exists(rest_api)
        assert not self.client.websocket_api_exists.called

    def test_websocket_api_exists_with_existing_deploy(self):
        websocket_api = self.create_websocket_api_model()
        deployed_resources = {
            'resources': [{
                'name': 'websocket_api',
                'resource_type': 'websocket_api',
                'websocket_api_id': 'my_websocket_api_id',
            }]
        }
        self.client.websocket_api_exists.return_value = True
        remote_state = RemoteState(
            self.client, DeployedResources(deployed_resources))
        assert remote_state.resource_exists(websocket_api)
        self.client.websocket_api_exists.assert_called_with(
            'my_websocket_api_id')

    def test_websocket_api_not_exists_with_preexisting_deploy(self):
        websocket_api = self.create_websocket_api_model()
        deployed_resources = {
            'resources': [{
                'name': 'websocket_api',
                'resource_type': 'websocket_api',
                'websocket_api_id': 'my_websocket_api_id',
            }]
        }
        self.client.websocket_api_exists.return_value = False
        remote_state = RemoteState(
            self.client, DeployedResources(deployed_resources))
        assert not remote_state.resource_exists(websocket_api)
        self.client.websocket_api_exists.assert_called_with(
            'my_websocket_api_id')

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

    def test_kinesis_event_source_not_exists(self):
        event_source = models.KinesisEventSource(
            resource_name='handler-kinesis-event-source',
            stream='mystream', batch_size=100, starting_position='LATEST',
            lambda_function=None)
        deployed_resources = {'resources': []}
        remote_state = RemoteState(
            self.client, DeployedResources(deployed_resources),
        )
        assert not remote_state.resource_exists(event_source)

    def test_kinesis_event_source_exists(self):
        event_source = models.KinesisEventSource(
            resource_name='handler-kinesis-event-source',
            stream='mystream', batch_size=100, starting_position='LATEST',
            lambda_function=None)
        deployed_resources = {
            'resources': [{
                'name': 'handler-kinesis-event-source',
                'resource_type': 'kinesis_event',
                'kinesis_arn': 'arn:aws:kinesis:...:stream/mystream',
                'event_uuid': 'abcd',
                'stream': 'mystream',
                'lambda_arn': 'arn:aws:lambda:function:test-dev-index'
            }]
        }
        remote_state = RemoteState(
            self.client, DeployedResources(deployed_resources),
        )
        self.client.verify_event_source_current.return_value = True
        assert remote_state.resource_exists(event_source)

    def test_ddb_event_source_not_exists(self):
        event_source = models.DynamoDBEventSource(
            resource_name='handler-dynamodb-event-source',
            stream_arn='arn:stream', batch_size=100,
            starting_position='LATEST', lambda_function=None)
        deployed_resources = {'resources': []}
        remote_state = RemoteState(
            self.client, DeployedResources(deployed_resources),
        )
        assert not remote_state.resource_exists(event_source)

    def test_ddb_event_source_exists(self):
        event_source = models.KinesisEventSource(
            resource_name='handler-kinesis-event-source',
            stream='mystream', batch_size=100, starting_position='LATEST',
            lambda_function=None)
        deployed_resources = {
            'resources': [{
                'name': 'handler-kinesis-event-source',
                'resource_type': 'kinesis_event',
                'stream_arn': 'arn:aws:kinesis:...:stream/mystream',
                'event_uuid': 'abcd',
                'stream': 'mystream',
                'lambda_arn': 'arn:aws:lambda:function:test-dev-index'
            }]
        }
        remote_state = RemoteState(
            self.client, DeployedResources(deployed_resources),
        )
        self.client.verify_event_source_arn_current.return_value = True
        assert remote_state.resource_exists(event_source)


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

    def test_can_delete_lambda_layer(self):
        plan = []
        deployed = {
            'resources': [{
                'name': 'layer',
                'resource_type': 'lambda_layer',
                'layer_version_arn': 'arn'}]}
        config = FakeConfig(deployed)
        self.execute(plan, config)
        assert plan == [
            models.APICall(
                method_name='delete_layer_version',
                params={'layer_version_arn': 'arn'})]

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

    def test_can_delete_websocket_api(self):
        plan = []
        deployed = {
            'resources': [{
                'name': 'websocket_api',
                'websocket_api_id': 'my_websocket_api_id',
                'resource_type': 'websocket_api',
            }]
        }
        config = FakeConfig(deployed)
        self.execute(plan, config)
        assert plan == [
            models.APICall(
                method_name='delete_websocket_api',
                params={'api_id': 'my_websocket_api_id'},
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
                method_name='remove_lambda_event_source',
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
                method_name='remove_lambda_event_source',
                params={'event_uuid': 'event-uuid'},
            ),
        ]

    def test_can_delete_domain_name(self):
        deployed = {
            'resources': [{
                'name': 'api_gateway_custom_domain',
                'resource_type': 'domain_name',
                'domain_name': 'example.com'
            }]
        }
        plan = []
        config = FakeConfig(deployed)
        self.execute(plan, config)
        assert plan[-1:] == [
            models.APICall(
                method_name='delete_domain_name',
                params={'domain_name': 'example.com'},
            ),
        ]

    def test_can_handle_domain_name_without_api_mapping(self):
        deployed = {
            'resources': [{
                'name': 'api_gateway_custom_domain',
                'resource_type': 'domain_name',
                'domain_name': 'example.com',
            }]
        }

        function = create_function_resource('function_name')
        domain_name = create_http_domain_name()
        rest_api = models.RestAPI(
            resource_name='rest_api',
            swagger_doc={'swagger': '2.0'},
            endpoint_type='EDGE',
            minimum_compression='100',
            api_gateway_stage='api',
            lambda_function=function,
            domain_name=domain_name
        )
        plan = self.determine_plan(
            rest_api
        )
        config = FakeConfig(deployed)
        self.execute(plan, config)
        assert plan[-1] == models.RecordResourceVariable(
            resource_type='domain_name',
            resource_name='api_gateway_custom_domain',
            name='api_mapping',
            variable_name='rest_api_mapping'
        )

    def test_can_delete_api_mapping(self):
        deployed = {
            'resources': [{
                'name': 'api_gateway_custom_domain',
                'resource_type': 'domain_name',
                'domain_name': 'example.com',
                'api_mapping':  [
                    {'key': '/path_key'}
                ]
            }]
        }

        domain_name = create_http_domain_name()
        plan = [
            models.RecordResourceVariable(
                resource_type='domain_name',
                resource_name=domain_name.resource_name,
                name='api_mapping',
                variable_name='rest_api_mapping'
            )
        ]
        config = FakeConfig(deployed)
        self.execute(plan, config)
        assert self.sweeper.plan.instructions[0] == models.APICall(
            method_name='delete_api_mapping',
            params={'domain_name': 'example.com',
                    'path_key': 'path_key'},
            output_var=None
        )

    def test_can_delete_api_mapping_none(self):
        deployed = {
            'resources': [{
                'name': 'api_gateway_custom_domain',
                'resource_type': 'domain_name',
                'domain_name': 'example.com',
                'api_mapping':  [
                    {'key': '/'}
                ]
            }]
        }
        domain_name = create_http_domain_name()
        plan = [
            models.RecordResourceVariable(
                resource_type='domain_name',
                resource_name=domain_name.resource_name,
                name='api_mapping',
                variable_name='rest_api_mapping'
            )
        ]
        config = FakeConfig(deployed)
        self.execute(plan, config)
        assert self.sweeper.plan.instructions[0] == models.APICall(
            method_name='delete_api_mapping',
            params={'domain_name': 'example.com',
                    'path_key': '(none)'},
            output_var=None
        )

    def test_raise_error_not_existed_resource_delete(self):
        deployed = {
            'resources': [{
                'name': 'name',
                'resource_type': 'not_existed',
            }]
        }
        config = FakeConfig(deployed)
        with pytest.raises(RuntimeError):
            self.execute([], config)

    def test_update_plan_with_insert_without_message(self):
        instructions = (
            models.APICall(
                method_name='unsubscribe_from_topic',
                params={'subscription_arn': 'subscription_arn'},
            ),
            models.APICall(
                method_name='remove_permission_for_sns_topic',
                params={
                    'topic_arn': 'topic_arn',
                    'function_arn': 'lambda_arn',
                },
            ),
        )  # type: Tuple[models.Instruction]
        self.sweeper._update_plan(instructions, insert=True)
        assert len(self.sweeper.plan.instructions) == 2


class TestKeyVariable(object):
    def test_key_variable_str(self):
        key_var = KeyDataVariable('name', 'key')
        assert str(key_var) == 'KeyDataVariable("name", "key")'

    def test_key_variables_equal(self):
        key_var = KeyDataVariable('name', 'key')
        key_var_1 = KeyDataVariable('name', 'key_1')
        assert not key_var == key_var_1

        key_var_2 = KeyDataVariable('name', 'key')
        assert key_var == key_var_2
