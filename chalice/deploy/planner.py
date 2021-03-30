# pylint: disable=too-many-lines
import re
import json
from collections import OrderedDict

from typing import List, Dict, Any, Optional, Union, Tuple, Set, cast  # noqa
from typing import Sequence  # noqa

from chalice.config import Config, DeployedResources  # noqa
from chalice.utils import OSUtils  # noqa
from chalice.deploy import models
from chalice.awsclient import TypedAWSClient, ResourceDoesNotExistError  # noqa


InstructionMsg = Union[models.Instruction, Tuple[models.Instruction, str]]
MarkedResource = Dict[str, List[models.RecordResource]]
CacheTuples = Union[Tuple[str, str, str], Tuple[str, str]]
ApiMap = Union[models.RestAPI, models.WebsocketAPI]


class RemoteState(object):
    def __init__(self, client, deployed_resources):
        # type: (TypedAWSClient, DeployedResources) -> None
        self._client = client
        self._cache = {}  # type: Dict[CacheTuples, bool]
        self._deployed_resources = deployed_resources

    def _cache_key(self, resource):
        # type: (models.ManagedModel) -> CacheTuples
        if isinstance(resource, models.APIMapping):
            return (
                resource.resource_type,
                resource.resource_name,
                resource.mount_path
            )
        return resource.resource_type, resource.resource_name

    def resource_deployed_values(self, resource):
        # type: (models.ManagedModel) -> Dict[str, Any]
        try:
            return self._deployed_resources.resource_values(
                resource.resource_name)
        except ValueError:
            return self._dynamically_lookup_values(resource)

    def _dynamically_lookup_values(self, resource):
        # type: (models.ManagedModel) -> Dict[str, str]
        if isinstance(resource, models.ManagedIAMRole):
            arn = self._client.get_role_arn_for_name(resource.role_name)
            return {
                "role_name": resource.role_name,
                "role_arn": arn,
                "name": resource.resource_name,
                "resource_type": "iam_role",
            }
        raise ValueError("Deployed values for resource does not exist: %s"
                         % resource.resource_name)

    def resource_exists(self, resource, *args):
        # type: (models.ManagedModel, Optional[Any]) -> bool
        key = self._cache_key(resource)
        if key in self._cache:
            return self._cache[key]
        try:
            handler = getattr(self, '_resource_exists_%s'
                              % resource.__class__.__name__.lower())
        except AttributeError:
            raise ValueError("RemoteState received an unsupported resource: %s"
                             % resource.resource_type)
        result = handler(resource, *args)
        self._cache[key] = result
        return result

    def _resource_exists_snslambdasubscription(self, resource):
        # type: (models.SNSLambdaSubscription) -> bool
        try:
            deployed_values = self._deployed_resources.resource_values(
                resource.resource_name)
        except ValueError:
            return False
        return self._client.verify_sns_subscription_current(
            deployed_values['subscription_arn'],
            topic_name=resource.topic,
            function_arn=deployed_values['lambda_arn'],
        )

    def _resource_exists_sqseventsource(self, resource):
        # type: (models.SQSEventSource) -> bool
        try:
            deployed_values = self._deployed_resources.resource_values(
                resource.resource_name)
        except ValueError:
            return False
        return self._client.verify_event_source_current(
            event_uuid=deployed_values['event_uuid'],
            resource_name=resource.queue,
            service_name='sqs',
            function_arn=deployed_values['lambda_arn'],
        )

    def _resource_exists_kinesiseventsource(self, resource):
        # type: (models.KinesisEventSource) -> bool
        try:
            deployed_values = self._deployed_resources.resource_values(
                resource.resource_name)
        except ValueError:
            return False
        return self._client.verify_event_source_current(
            event_uuid=deployed_values['event_uuid'],
            resource_name='stream/%s' % resource.stream,
            service_name='kinesis',
            function_arn=deployed_values['lambda_arn'],
        )

    def _resource_exists_dynamodbeventsource(self, resource):
        # type: (models.DynamoDBEventSource) -> bool
        try:
            deployed_values = self._deployed_resources.resource_values(
                resource.resource_name)
        except ValueError:
            return False
        return self._client.verify_event_source_arn_current(
            event_uuid=deployed_values['event_uuid'],
            event_source_arn=deployed_values['stream_arn'],
            function_arn=deployed_values['lambda_arn'],
        )

    def _resource_exists_lambdalayer(self, resource):
        # type: (models.LambdaLayer) -> bool
        try:
            deployed_values = self._deployed_resources.resource_values(
                resource.resource_name)
        except ValueError:
            return False
        return bool(self._client.get_layer_version(
            deployed_values['layer_version_arn']))

    def _resource_exists_lambdafunction(self, resource):
        # type: (models.LambdaFunction) -> bool
        return self._client.lambda_function_exists(resource.function_name)

    def _resource_exists_managediamrole(self, resource):
        # type: (models.ManagedIAMRole) -> bool
        try:
            self._client.get_role_arn_for_name(resource.role_name)
            return True
        except ResourceDoesNotExistError:
            return False

    def _resource_exists_apimapping(self, resource, domain_name):
        # type: (models.APIMapping, str) -> bool
        map_key = resource.mount_path
        if map_key == '(none)':
            map_key = ''
        elif map_key.startswith('/'):
            map_key = map_key.lstrip('/')

        return self._client.api_mapping_exists(domain_name, map_key)

    def _resource_exists_domainname(self, resource):
        # type: (models.DomainName) -> bool
        if resource.protocol == models.APIType.WEBSOCKET:
            return self._client.domain_name_exists_v2(
                resource.domain_name)
        return self._client.domain_name_exists(resource.domain_name)

    def _resource_exists_restapi(self, resource):
        # type: (models.RestAPI) -> bool
        try:
            deployed_values = self._deployed_resources.resource_values(
                resource.resource_name)
        except ValueError:
            return False
        rest_api_id = deployed_values['rest_api_id']
        return bool(self._client.get_rest_api(rest_api_id))

    def _resource_exists_websocketapi(self, resource):
        # type: (models.WebsocketAPI) -> bool
        try:
            deployed_values = self._deployed_resources.resource_values(
                resource.resource_name)
        except ValueError:
            return False
        api_id = deployed_values['websocket_api_id']
        return self._client.websocket_api_exists(api_id)


class PlanStage(object):
    def __init__(self, remote_state, osutils):
        # type: (RemoteState, OSUtils) -> None
        self._remote_state = remote_state
        self._osutils = osutils

    def execute(self, resources):
        # type: (List[models.Model]) -> models.Plan
        plan = []  # type: List[models.Instruction]
        messages = {}  # type: Dict[int, str]
        for resource in resources:
            name = '_plan_%s' % resource.__class__.__name__.lower()
            handler = getattr(self, name, None)
            if handler is not None:
                result = handler(resource)
                if result:
                    self._add_result_to_plan(result, plan, messages)
        return models.Plan(plan, messages)

    def _add_result_to_plan(self,
                            result,    # type: Sequence[InstructionMsg]
                            plan,      # type: List[models.Instruction]
                            messages,  # type: Dict[int, str]
                            ):
        # type: (...) -> None
        for single in result:
            if isinstance(single, tuple):
                instruction, message = single
                plan.append(instruction)
                messages[id(instruction)] = message
            else:
                plan.append(single)

    # TODO: This code will likely be refactored and pulled into
    # per-resource classes so the PlanStage object doesn't need
    # to know about every type of resource.

    def _add_apimapping_plan(self,
                             resource,    # type: models.APIMapping
                             domain_name  # type: models.DomainName
                             ):
        # type: (...) -> Sequence[InstructionMsg]
        api_calls = []  # type: List[InstructionMsg]
        params = {
            'domain_name': domain_name.domain_name,
            'path_key': resource.mount_path,
            'stage': resource.api_gateway_stage
        }  # type: Dict[str, Any]
        if domain_name.protocol == models.APIType.WEBSOCKET:
            params['api_id'] = Variable('websocket_api_id')
            variable_name = 'websocket_api_mapping'
            api_call = models.APICall(
                method_name='create_api_mapping',
                params=params,
                output_var='api_mapping'
            )
        else:
            params['api_id'] = Variable('rest_api_id')
            variable_name = 'rest_api_mapping'
            api_call = models.APICall(
                method_name='create_base_path_mapping',
                params=params,
                output_var='api_mapping'
            )

        if not self._remote_state.resource_exists(
                resource, domain_name.domain_name
        ):
            path_to_print = '/'
            if resource.mount_path != '(none)' and \
                    not resource.mount_path.startswith("/"):
                path_to_print = '/%s' % resource.mount_path
            api_calls.extend([
                (api_call, "Creating api mapping: %s\n" % path_to_print),
                models.StoreMultipleValue(
                    name=variable_name,
                    value=[Variable('api_mapping')]
                ),
                models.RecordResourceVariable(
                    resource_type='domain_name',
                    resource_name=domain_name.resource_name,
                    name='api_mapping',
                    variable_name=variable_name
                ),
            ])
        else:
            deployed = self._remote_state.resource_deployed_values(
                domain_name
            )
            for api_mapping in deployed['api_mapping']:

                mount_path = api_mapping['key'].lstrip('/')
                if not mount_path:
                    mount_path = '(none)'
                if mount_path != resource.mount_path:
                    continue

                api_calls.extend([
                    models.StoreMultipleValue(
                        name=variable_name,
                        value=[api_mapping]
                    ),
                    models.RecordResourceVariable(
                        resource_type='domain_name',
                        resource_name=domain_name.resource_name,
                        name='api_mapping',
                        variable_name=variable_name
                    ),
                ])
        return api_calls

    def _add_domainname_plan(self, resource, endpoint_type):
        # type: (models.DomainName, str) -> Sequence[InstructionMsg]
        api_calls = []  # type: List[InstructionMsg]

        params = {
            'protocol': resource.protocol.value,
            'tags': resource.tags,
            'endpoint_type': endpoint_type,
            'domain_name': resource.domain_name,
        }
        params['certificate_arn'] = resource.certificate_arn
        if resource.tls_version is not None:
            params['security_policy'] = resource.tls_version.value

        if not self._remote_state.resource_exists(resource):
            domain_name_api_call = (
                models.APICall(
                    method_name='create_domain_name',
                    params=params,
                    output_var=resource.resource_name
                ),
                "Creating custom domain name: %s\n" % resource.domain_name
            )

        else:
            domain_name_api_call = (
                models.APICall(
                    method_name='update_domain_name',
                    params=params,
                    output_var=resource.resource_name
                ),
                "Updating custom domain name: %s\n" % resource.domain_name
            )

        api_calls.extend([
            domain_name_api_call,
            models.StoreValue(
                name='hosted_zone_id',
                value=KeyDataVariable(resource.resource_name,
                                      'hosted_zone_id')
            ),
            models.RecordResourceVariable(
                resource_type='domain_name',
                resource_name=resource.resource_name,
                name='hosted_zone_id',
                variable_name='hosted_zone_id'
            ),
            models.StoreValue(
                name='alias_domain_name',
                value=KeyDataVariable(resource.resource_name,
                                      'alias_domain_name')
            ),
            models.RecordResourceVariable(
                resource_type='domain_name',
                resource_name=resource.resource_name,
                name='alias_domain_name',
                variable_name='alias_domain_name'
            ),
            models.StoreValue(
                name='certificate_arn',
                value=KeyDataVariable(resource.resource_name,
                                      'certificate_arn')
            ),
            models.RecordResourceVariable(
                resource_type='domain_name',
                resource_name=resource.resource_name,
                name='certificate_arn',
                variable_name='certificate_arn'
            ),
            models.StoreValue(
                name='security_policy',
                value=KeyDataVariable(resource.resource_name,
                                      'security_policy')
            ),
            models.RecordResourceVariable(
                resource_type='domain_name',
                resource_name=resource.resource_name,
                name='security_policy',
                variable_name='security_policy'
            ),
            models.RecordResourceValue(
                resource_type='domain_name',
                resource_name=resource.resource_name,
                name='domain_name',
                value=resource.domain_name
            )
        ])
        return api_calls

    def _plan_lambdalayer(self, resource):
        # type: (models.LambdaLayer) -> Sequence[InstructionMsg]

        api_calls = []  # type: List[InstructionMsg]
        filename = cast(str, resource.deployment_package.filename)

        # Automatically clean up old layer versions.
        # See:
        # https://docs.aws.amazon.com/lambda/latest/dg/API_DeleteLayerVersion.html
        msg = 'Creating'
        if self._remote_state.resource_exists(resource):
            state = self._remote_state.resource_deployed_values(resource)
            # Deleting a layer version won't break functions still using it.
            # From the doc link above:
            #
            # "To avoid breaking functions, a copy of the version remains in
            # Lambda until no functions refer to it."
            api_calls.append(
                models.APICall(
                    method_name='delete_layer_version',
                    params={'layer_version_arn': state['layer_version_arn']}
                )
            )
            msg = 'Updating'

        api_calls.extend([(
            models.APICall(
                method_name='publish_layer',
                params={'layer_name': resource.layer_name,
                        'zip_contents': self._osutils.get_file_contents(
                            filename, binary=True),
                        'runtime': resource.runtime},
                output_var='layer_version_arn'
            ), "%s lambda layer: %s\n" % (msg, resource.layer_name)),
            models.RecordResourceVariable(
                resource_type='lambda_layer',
                resource_name=resource.resource_name,
                name='layer_version_arn',
                variable_name='layer_version_arn',
        )])
        return api_calls

    def _plan_lambdafunction(self, resource):
        # type: (models.LambdaFunction) -> Sequence[InstructionMsg]
        role_arn = self._get_role_arn(resource.role)
        # Make mypy happy, it complains if we don't "declare" this upfront.
        params = {}  # type: Dict[str, Any]
        varname = '%s_lambda_arn' % resource.resource_name
        # Not sure the best way to express this via mypy, but we know
        # that in the build stage we replace the deployment package
        # name with the actual filename generated from the pip
        # packager.  For now we resort to a cast.
        filename = cast(str, resource.deployment_package.filename)

        if resource.reserved_concurrency is None:
            concurrency_api_call = models.APICall(
                method_name='delete_function_concurrency',
                params={
                    'function_name': resource.function_name,
                },
                output_var='reserved_concurrency_result'
            )
        else:
            concurrency = resource.reserved_concurrency
            concurrency_api_call = (
                models.APICall(
                    method_name='put_function_concurrency',
                    params={
                        'function_name': resource.function_name,
                        'reserved_concurrent_executions': concurrency,
                    },
                    output_var='reserved_concurrency_result'),
                "Updating lambda function concurrency limit: %s\n"
                % resource.function_name
            )

        api_calls = []  # type: List[InstructionMsg]
        layers = []  # type: List[Any]
        if resource.managed_layer is not None:
            layers.append(Variable('layer_version_arn'))
        if resource.layers:
            layers.extend(resource.layers)

        if not self._remote_state.resource_exists(resource):
            params = {
                'function_name': resource.function_name,
                'role_arn': role_arn,
                'zip_contents': self._osutils.get_file_contents(
                    filename, binary=True),
                'runtime': resource.runtime,
                'handler': resource.handler,
                'environment_variables': resource.environment_variables,
                'xray': resource.xray,
                'tags': resource.tags,
                'timeout': resource.timeout,
                'memory_size': resource.memory_size,
                'security_group_ids': resource.security_group_ids,
                'subnet_ids': resource.subnet_ids,
                'layers': layers
            }

            api_calls.extend([
                (models.APICall(
                    method_name='create_function',
                    params=params,
                    output_var=varname,
                ), "Creating lambda function: %s\n" % resource.function_name),
                models.RecordResourceVariable(
                    resource_type='lambda_function',
                    resource_name=resource.resource_name,
                    name='lambda_arn',
                    variable_name=varname,
                )
            ])
        else:
            # TODO: Consider a smarter diff where we check if we even need
            # to do an update() API call.
            params = {
                'function_name': resource.function_name,
                'role_arn': role_arn,
                'zip_contents': self._osutils.get_file_contents(
                    filename, binary=True),
                'runtime': resource.runtime,
                'environment_variables': resource.environment_variables,
                'xray': resource.xray,
                'tags': resource.tags,
                'timeout': resource.timeout,
                'memory_size': resource.memory_size,
                'security_group_ids': resource.security_group_ids,
                'subnet_ids': resource.subnet_ids,
                'layers': layers
            }
            api_calls.extend([
                (models.APICall(
                    method_name='update_function',
                    params=params,
                    output_var='update_function_result',
                ), "Updating lambda function: %s\n" % resource.function_name),
                models.JPSearch(
                    'FunctionArn',
                    input_var='update_function_result',
                    output_var=varname,
                ),
                models.RecordResourceVariable(
                    resource_type='lambda_function',
                    resource_name=resource.resource_name,
                    name='lambda_arn',
                    variable_name=varname,
                )
            ])
        api_calls.append(concurrency_api_call)
        return api_calls

    def _plan_managediamrole(self, resource):
        # type: (models.ManagedIAMRole) -> Sequence[InstructionMsg]
        document = resource.policy.document
        role_exists = self._remote_state.resource_exists(resource)
        varname = '%s_role_arn' % resource.role_name
        if not role_exists:
            return [
                models.BuiltinFunction(
                    'service_principal',
                    ['lambda'],
                    output_var='lambda_service_principal',
                ),
                models.JPSearch('principal',
                                input_var='lambda_service_principal',
                                output_var='lambda_principal'),
                models.StoreValue(
                    name='lambda_principal',
                    value=StringFormat('{lambda_principal}',
                                       ['lambda_principal']),
                ),
                models.StoreValue(
                    name='lambda_trust_policy',
                    value={
                        "Version": "2012-10-17",
                        "Statement": [{
                            "Sid": "",
                            "Effect": "Allow",
                            "Principal": {
                                "Service": Variable('lambda_principal')
                            },
                            "Action": "sts:AssumeRole"
                        }]
                    },
                ),
                (models.APICall(
                    method_name='create_role',
                    params={'name': resource.role_name,
                            'trust_policy': Variable('lambda_trust_policy'),
                            'policy': document},
                    output_var=varname,
                ), "Creating IAM role: %s\n" % resource.role_name),
                models.RecordResourceVariable(
                    resource_type='iam_role',
                    resource_name=resource.resource_name,
                    name='role_arn',
                    variable_name=varname,
                ),
                models.RecordResourceValue(
                    resource_type='iam_role',
                    resource_name=resource.resource_name,
                    name='role_name',
                    value=resource.role_name,
                )
            ]
        role_arn = self._remote_state.resource_deployed_values(
            resource)['role_arn']
        return [
            models.StoreValue(name=varname, value=role_arn),
            (models.APICall(
                method_name='put_role_policy',
                params={'role_name': resource.role_name,
                        'policy_name': resource.role_name,
                        'policy_document': document},
            ), "Updating policy for IAM role: %s\n" % resource.role_name),
            models.RecordResourceVariable(
                resource_type='iam_role',
                resource_name=resource.resource_name,
                name='role_arn',
                variable_name=varname,
            ),
            models.RecordResourceValue(
                resource_type='iam_role',
                resource_name=resource.resource_name,
                name='role_name',
                value=resource.role_name,
            )
        ]

    def _plan_snslambdasubscription(self, resource):
        # type: (models.SNSLambdaSubscription) -> Sequence[InstructionMsg]
        function_arn = Variable(
            '%s_lambda_arn' % resource.lambda_function.resource_name
        )
        topic_arn_varname = '%s_topic_arn' % resource.resource_name
        subscribe_varname = '%s_subscription_arn' % resource.resource_name

        instruction_for_topic_arn = []  # type: List[InstructionMsg]
        if re.match(r"^arn:aws[a-z\-]*:sns:", resource.topic):
            instruction_for_topic_arn += [
                models.StoreValue(
                    name=topic_arn_varname,
                    value=resource.topic,
                )
            ]
        else:
            # To keep the user API simple, we only require the topic
            # name and not the ARN.  However, the APIs require the topic
            # ARN so we need to reconstruct it here in the planner.
            instruction_for_topic_arn += self._arn_parse_instructions(
                function_arn) + [
                models.StoreValue(
                    name=topic_arn_varname,
                    value=StringFormat(
                        'arn:{partition}:sns:{region_name}:{account_id}:%s' % (
                            resource.topic
                        ),
                        ['partition', 'region_name', 'account_id'],
                    ),
                )
            ]
        if self._remote_state.resource_exists(resource):
            # Given there's nothing about an SNS subscription you can
            # configure for now, if the resource exists, we don't do
            # anything.  The resource sweeper will verify that if the
            # subscription doesn't actually apply that we should unsubscribe
            # from the topic.
            deployed = self._remote_state.resource_deployed_values(resource)
            subscription_arn = deployed['subscription_arn']
            return instruction_for_topic_arn + self._batch_record_resource(
                'sns_event', resource.resource_name, {
                    'topic': resource.topic,
                    'lambda_arn': Variable(function_arn.name),
                    'subscription_arn': subscription_arn,
                    'topic_arn': Variable(topic_arn_varname),
                }
            )
        return instruction_for_topic_arn + [
            models.APICall(
                method_name='add_permission_for_sns_topic',
                params={'topic_arn': Variable(topic_arn_varname),
                        'function_arn': function_arn},
            ),
            (models.APICall(
                method_name='subscribe_function_to_topic',
                params={'topic_arn': Variable(topic_arn_varname),
                        'function_arn': function_arn},
                output_var=subscribe_varname,
            ), 'Subscribing %s to SNS topic %s\n'
                % (resource.lambda_function.function_name, resource.topic)
            )
        ] + self._batch_record_resource(
            'sns_event', resource.resource_name, {
                'topic': resource.topic,
                'lambda_arn': Variable(function_arn.name),
                'subscription_arn': Variable(subscribe_varname),
                'topic_arn': Variable(topic_arn_varname),
            }
        )

    def _plan_sqseventsource(self, resource):
        # type: (models.SQSEventSource) -> Sequence[InstructionMsg]
        queue_arn_varname = '%s_queue_arn' % resource.resource_name
        uuid_varname = '%s_uuid' % resource.resource_name
        function_arn = Variable(
            '%s_lambda_arn' % resource.lambda_function.resource_name
        )
        instruction_for_queue_arn = self._arn_parse_instructions(function_arn)
        instruction_for_queue_arn.append(
            models.StoreValue(
                name=queue_arn_varname,
                value=StringFormat(
                    'arn:{partition}:sqs:{region_name}:{account_id}:%s' % (
                        resource.queue
                    ),
                    ['partition', 'region_name', 'account_id'],
                ),
            )
        )
        if self._remote_state.resource_exists(resource):
            deployed = self._remote_state.resource_deployed_values(resource)
            uuid = deployed['event_uuid']
            return instruction_for_queue_arn + [
                models.APICall(
                    method_name='update_lambda_event_source',
                    params={'event_uuid': uuid,
                            'batch_size': resource.batch_size}
                )
            ] + self._batch_record_resource(
                'sqs_event', resource.resource_name, {
                    'queue_arn': deployed['queue_arn'],
                    'event_uuid': uuid,
                    'queue': resource.queue,
                    'lambda_arn': deployed['lambda_arn'],
                }
            )
        return instruction_for_queue_arn + [
            (models.APICall(
                method_name='create_lambda_event_source',
                params={'event_source_arn': Variable(queue_arn_varname),
                        'batch_size': resource.batch_size,
                        'function_name': function_arn},
                output_var=uuid_varname,
            ), 'Subscribing %s to SQS queue %s\n'
                % (resource.lambda_function.function_name, resource.queue)
            ),
        ] + self._batch_record_resource(
            'sqs_event', resource.resource_name, {
                'queue_arn': Variable(queue_arn_varname),
                'event_uuid': Variable(uuid_varname),
                'queue': resource.queue,
                'lambda_arn': Variable(function_arn.name)
            }
        )

    def _plan_kinesiseventsource(self, resource):
        # type: (models.KinesisEventSource) -> Sequence[InstructionMsg]
        stream_arn_varname = '%s_stream_arn' % resource.resource_name
        uuid_varname = '%s_uuid' % resource.resource_name
        function_arn = Variable(
            '%s_lambda_arn' % resource.lambda_function.resource_name
        )
        instruction_for_stream_arn = self._arn_parse_instructions(function_arn)
        instruction_for_stream_arn.append(
            models.StoreValue(
                name=stream_arn_varname,
                value=StringFormat(
                    'arn:{partition}:kinesis:{region_name}:{account_id}:'
                    'stream/%s' % resource.stream,
                    ['partition', 'region_name', 'account_id'],
                ),
            )
        )
        if self._remote_state.resource_exists(resource):
            deployed = self._remote_state.resource_deployed_values(resource)
            uuid = deployed['event_uuid']
            return instruction_for_stream_arn + [
                models.APICall(
                    method_name='update_lambda_event_source',
                    params={'event_uuid': uuid,
                            'batch_size': resource.batch_size}
                )
            ] + self._batch_record_resource(
                'kinesis_event', resource.resource_name, {
                    'kinesis_arn': deployed['kinesis_arn'],
                    'event_uuid': uuid,
                    'stream': resource.stream,
                    'lambda_arn': deployed['lambda_arn'],
                }
            )
        return instruction_for_stream_arn + [
            (models.APICall(
                method_name='create_lambda_event_source',
                params={'event_source_arn': Variable(stream_arn_varname),
                        'batch_size': resource.batch_size,
                        'function_name': function_arn,
                        'starting_position': resource.starting_position},
                output_var=uuid_varname,
            ), 'Subscribing %s to Kinesis stream %s\n'
                % (resource.lambda_function.function_name, resource.stream)
            )
        ] + self._batch_record_resource(
            'kinesis_event', resource.resource_name, {
                'kinesis_arn': Variable(stream_arn_varname),
                'event_uuid': Variable(uuid_varname),
                'stream': resource.stream,
                'lambda_arn': Variable(function_arn.name),
            }
        )

    def _plan_dynamodbeventsource(self, resource):
        # type: (models.DynamoDBEventSource) -> Sequence[InstructionMsg]
        uuid_varname = '%s_uuid' % resource.resource_name
        function_arn = Variable(
            '%s_lambda_arn' % resource.lambda_function.resource_name
        )
        instructions = []  # type: List[InstructionMsg]
        if self._remote_state.resource_exists(resource):
            deployed = self._remote_state.resource_deployed_values(resource)
            uuid = deployed['event_uuid']
            return instructions + [
                models.APICall(
                    method_name='update_lambda_event_source',
                    params={'event_uuid': uuid,
                            'batch_size': resource.batch_size}
                )
            ] + self._batch_record_resource(
                'dynamodb_event', resource.resource_name, {
                    'stream_arn': deployed['stream_arn'],
                    'event_uuid': deployed['event_uuid'],
                    'lambda_arn': deployed['lambda_arn'],
                }
            )
        return instructions + [
            (models.APICall(
                method_name='create_lambda_event_source',
                params={'event_source_arn': resource.stream_arn,
                        'batch_size': resource.batch_size,
                        'function_name': function_arn,
                        'starting_position': resource.starting_position},
                output_var=uuid_varname,
            ), 'Subscribing %s to DynamoDB stream %s\n'
                % (resource.lambda_function.function_name,
                   resource.stream_arn))
        ] + self._batch_record_resource(
            'dynamodb_event', resource.resource_name, {
                'stream_arn': resource.stream_arn,
                'event_uuid': Variable(uuid_varname),
                'lambda_arn': function_arn,
            }
        )

    def _arn_parse_instructions(self, function_arn):
        # type: (Variable) -> List[InstructionMsg]
        instruction_for_stream_arn = [
            models.BuiltinFunction('parse_arn', [function_arn],
                                   output_var='parsed_lambda_arn'),
            models.JPSearch('account_id', input_var='parsed_lambda_arn',
                            output_var='account_id'),
            models.JPSearch('region', input_var='parsed_lambda_arn',
                            output_var='region_name'),
            models.JPSearch('partition', input_var='parsed_lambda_arn',
                            output_var='partition'),
        ]  # type: List[InstructionMsg]
        return instruction_for_stream_arn

    def _plan_s3bucketnotification(self, resource):
        # type: (models.S3BucketNotification) -> Sequence[InstructionMsg]
        function_arn = Variable(
            '%s_lambda_arn' % resource.lambda_function.resource_name
        )
        return [
            models.APICall(
                method_name='add_permission_for_s3_event',
                params={'bucket': resource.bucket,
                        'function_arn': function_arn},
            ),
            (models.APICall(
                method_name='connect_s3_bucket_to_lambda',
                params={'bucket': resource.bucket,
                        'function_arn': function_arn,
                        'prefix': resource.prefix,
                        'suffix': resource.suffix,
                        'events': resource.events}
            ), 'Configuring S3 events in bucket %s to function %s\n'
                % (resource.bucket, resource.lambda_function.function_name)
            ),
            models.RecordResourceValue(
                resource_type='s3_event',
                resource_name=resource.resource_name,
                name='bucket',
                value=resource.bucket,
            ),
            models.RecordResourceVariable(
                resource_type='s3_event',
                resource_name=resource.resource_name,
                name='lambda_arn',
                variable_name=function_arn.name,
            ),
        ]

    def _create_cloudwatchevent(self, resource):
        # type: (models.CloudWatchEventBase) -> Sequence[InstructionMsg]

        function_arn = Variable(
            '%s_lambda_arn' % resource.lambda_function.resource_name
        )

        params = {'rule_name': resource.rule_name}
        if isinstance(resource, models.ScheduledEvent):
            resource = cast(models.ScheduledEvent, resource)
            params['schedule_expression'] = resource.schedule_expression
            if resource.rule_description is not None:
                params['rule_description'] = resource.rule_description
        else:
            resource = cast(models.CloudWatchEvent, resource)
            params['event_pattern'] = resource.event_pattern

        plan = [
            models.APICall(
                method_name='get_or_create_rule_arn',
                params=params,
                output_var='rule-arn',
            ),
            models.APICall(
                method_name='connect_rule_to_lambda',
                params={'rule_name': resource.rule_name,
                        'function_arn': function_arn}
            ),
            models.APICall(
                method_name='add_permission_for_cloudwatch_event',
                params={'rule_arn': Variable('rule-arn'),
                        'function_arn': function_arn},
            ),
            # You need to remove targets (which have IDs)
            # before you can delete a rule.
            models.RecordResourceValue(
                resource_type='cloudwatch_event',
                resource_name=resource.resource_name,
                name='rule_name',
                value=resource.rule_name,
            )
        ]
        return plan

    def _plan_cloudwatchevent(self, resource):
        # type: (models.CloudWatchEvent) -> Sequence[InstructionMsg]
        return self._create_cloudwatchevent(resource)

    def _plan_scheduledevent(self, resource):
        # type: (models.ScheduledEvent) -> Sequence[InstructionMsg]
        return self._create_cloudwatchevent(resource)

    def _create_websocket_function_configs(self, resource):
        # type: (models.WebsocketAPI) -> Dict[str, Dict[str, Any]]
        configs = OrderedDict()  # type: Dict[str, Dict[str, Any]]
        if resource.connect_function is not None:
            configs['connect'] = self._create_websocket_function_config(
                resource.connect_function)
        if resource.message_function is not None:
            configs['message'] = self._create_websocket_function_config(
                resource.message_function)
        if resource.disconnect_function is not None:
            configs['disconnect'] = self._create_websocket_function_config(
                resource.disconnect_function)
        return configs

    def _create_websocket_function_config(self, function):
        # type: (models.LambdaFunction) -> Dict[str, Any]
        varname = '%s_lambda_arn' % function.resource_name
        return {
            'function': function,
            'name': function.function_name,
            'varname': varname,
            'lambda_arn_var': Variable(varname),
        }

    def _inject_websocket_integrations(self, configs):
        # type: (Dict[str, Any]) -> Sequence[InstructionMsg]
        instructions = []  # type: List[InstructionMsg]
        for key, config in configs.items():
            instructions.append(
                models.StoreValue(
                    name='websocket-%s-integration-lambda-path' % key,
                    value=StringFormat(
                        'arn:{partition}:apigateway:{region_name}:lambda:path/'
                        '2015-03-31/functions/arn:{partition}'
                        ':lambda:{region_name}:{account_id}:function'
                        ':%s/invocations' % config['name'],
                        ['partition', 'region_name', 'account_id'],
                    ),
                ),
            )
            instructions.append(
                models.APICall(
                    method_name='create_websocket_integration',
                    params={
                        'api_id': Variable('websocket_api_id'),
                        'lambda_function': Variable(
                            'websocket-%s-integration-lambda-path' % key),
                        'handler_type': key,
                    },
                    output_var='%s-integration-id' % key,
                ),
            )
        return instructions

    def _create_route_for_key(self, route_key):
        # type: (str) -> models.APICall
        integration_id = {
            '$connect': 'connect-integration-id',
            '$disconnect': 'disconnect-integration-id',
        }.get(route_key, 'message-integration-id')
        return models.APICall(
            method_name='create_websocket_route',
            params={
                'api_id': Variable('websocket_api_id'),
                'route_key': route_key,
                'integration_id': Variable(integration_id),
            },
        )

    def _plan_websocketapi(self, resource):
        # type: (models.WebsocketAPI) -> Sequence[InstructionMsg]
        configs = self._create_websocket_function_configs(resource)
        routes = resource.routes

        # Which lambda function we use here does not matter. We are only using
        # it to find the account id and the region.
        lambda_arn_var = list(configs.values())[0]['lambda_arn_var']
        shared_plan_preamble = self._arn_parse_instructions(lambda_arn_var) + [
            models.JPSearch('dns_suffix',
                            input_var='parsed_lambda_arn',
                            output_var='dns_suffix'),
        ]  # type: List[InstructionMsg]

        # There's also a set of instructions that are needed
        # at the end of deploying a websocket API that apply to both
        # the update and create case.
        shared_plan_epilogue = [
            models.StoreValue(
                name='websocket_api_url',
                value=StringFormat(
                    'wss://{websocket_api_id}.execute-api.{region_name}'
                    '.{dns_suffix}/%s/' % resource.api_gateway_stage,
                    ['websocket_api_id', 'region_name', 'dns_suffix'],
                ),
            ),
            models.RecordResourceVariable(
                resource_type='websocket_api',
                resource_name=resource.resource_name,
                name='websocket_api_url',
                variable_name='websocket_api_url',
            ),
            models.RecordResourceVariable(
                resource_type='websocket_api',
                resource_name=resource.resource_name,
                name='websocket_api_id',
                variable_name='websocket_api_id',
            ),
        ]  # type: List[InstructionMsg]

        shared_plan_epilogue += [
            models.APICall(
                method_name='add_permission_for_apigateway_v2',
                params={'function_name': function_config['name'],
                        'region_name': Variable('region_name'),
                        'account_id': Variable('account_id'),
                        'api_id': Variable('websocket_api_id')},
            ) for function_config in configs.values()
        ]

        main_plan = []  # type: List[InstructionMsg]
        if not self._remote_state.resource_exists(resource):
            # The resource does not exist, we create it in full here.
            main_plan += [
                (models.APICall(
                    method_name='create_websocket_api',
                    params={'name': resource.name},
                    output_var='websocket_api_id',
                ), "Creating websocket api: %s\n" % resource.name),
                models.StoreValue(
                    name='routes',
                    value=[],
                ),
            ]
            main_plan += self._inject_websocket_integrations(configs)

            for route_key in routes:
                main_plan += [self._create_route_for_key(route_key)]
            main_plan += [
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
                        'stage_name': resource.api_gateway_stage,
                        'deployment_id': Variable('deployment-id'),
                    }
                ),
            ]
        else:
            # Already exists. Need to sync up the routes, the easiest way to do
            # this is to delete them and their integrations and re-create them.
            # They will not work if the lambda function changes from under
            # them, and the logic for detecting that and making just the needed
            # changes is complex. There is an integration test to ensure there
            # no dropped messages during a redeployment.
            deployed = self._remote_state.resource_deployed_values(resource)
            main_plan += [
                models.StoreValue(
                    name='websocket_api_id',
                    value=deployed['websocket_api_id']
                ),
                models.APICall(
                    method_name='get_websocket_routes',
                    params={'api_id': Variable('websocket_api_id')},
                    output_var='routes',
                ),
                models.APICall(
                    method_name='delete_websocket_routes',
                    params={
                        'api_id': Variable('websocket_api_id'),
                        'routes': Variable('routes'),
                    },
                ),
                models.APICall(
                    method_name='get_websocket_integrations',
                    params={
                        'api_id': Variable('websocket_api_id'),
                    },
                    output_var='integrations'
                ),
                models.APICall(
                    method_name='delete_websocket_integrations',
                    params={
                        'api_id': Variable('websocket_api_id'),
                        'integrations': Variable('integrations'),
                    }
                )
            ]
            main_plan += self._inject_websocket_integrations(configs)
            for route_key in routes:
                main_plan += [self._create_route_for_key(route_key)]

        ws_plan = shared_plan_preamble + main_plan + shared_plan_epilogue

        if resource.domain_name:
            custom_domain_plan = self._add_custom_domain_plan(
                resource.domain_name, 'REGIONAL',
            )
            ws_plan += custom_domain_plan

        return ws_plan

    def _plan_restapi(self, resource):
        # type: (models.RestAPI) -> Sequence[InstructionMsg]
        function = resource.lambda_function
        function_name = function.function_name
        varname = '%s_lambda_arn' % function.resource_name
        lambda_arn_var = Variable(varname)
        # There's a set of shared instructions that are needed
        # in both the update as well as the initial create case.
        # That's what this shared_plan_premable is for.
        shared_plan_preamble = self._arn_parse_instructions(lambda_arn_var) + [
            models.JPSearch('dns_suffix',
                            input_var='parsed_lambda_arn',
                            output_var='dns_suffix'),
            # The swagger doc uses the 'api_handler_lambda_arn'
            # var name so we need to make sure we populate this variable
            # before importing the rest API.
            models.CopyVariable(from_var=varname,
                                to_var='api_handler_lambda_arn'),
        ]  # type: List[InstructionMsg]
        # There's also a set of instructions that are needed
        # at the end of deploying a rest API that apply to both
        # the update and create case.
        shared_plan_patch_ops = [{
            'op': 'replace',
            'path': '/minimumCompressionSize',
            'value': resource.minimum_compression}
        ]  # type: List[Dict]

        shared_plan_epilogue = [
            models.APICall(
                method_name='update_rest_api',
                params={
                    'rest_api_id': Variable('rest_api_id'),
                    'patch_operations': shared_plan_patch_ops
                }
            ),
            models.APICall(
                method_name='add_permission_for_apigateway',
                params={'function_name': function_name,
                        'region_name': Variable('region_name'),
                        'account_id': Variable('account_id'),
                        'rest_api_id': Variable('rest_api_id')},
            ),
            models.APICall(
                method_name='deploy_rest_api',
                params={'rest_api_id': Variable('rest_api_id'),
                        'xray': resource.xray,
                        'api_gateway_stage': resource.api_gateway_stage},
            ),
            models.StoreValue(
                name='rest_api_url',
                value=StringFormat(
                    'https://{rest_api_id}.execute-api.{region_name}'
                    '.{dns_suffix}/%s/' % resource.api_gateway_stage,
                    ['rest_api_id', 'region_name', 'dns_suffix'],
                ),
            ),
            models.RecordResourceVariable(
                resource_type='rest_api',
                resource_name=resource.resource_name,
                name='rest_api_url',
                variable_name='rest_api_url',
            ),
        ]  # type: List[InstructionMsg]
        for auth in resource.authorizers:
            shared_plan_epilogue.append(
                models.APICall(
                    method_name='add_permission_for_apigateway',
                    params={'function_name': auth.function_name,
                            'region_name': Variable('region_name'),
                            'account_id': Variable('account_id'),
                            'rest_api_id': Variable('rest_api_id')},
                )
            )
        if not self._remote_state.resource_exists(resource):
            plan = shared_plan_preamble + [
                (models.APICall(
                    method_name='import_rest_api',
                    params={'swagger_document': resource.swagger_doc,
                            'endpoint_type': resource.endpoint_type},
                    output_var='rest_api_id',
                ), "Creating Rest API\n"),
                models.RecordResourceVariable(
                    resource_type='rest_api',
                    resource_name=resource.resource_name,
                    name='rest_api_id',
                    variable_name='rest_api_id',
                ),
            ]
        else:
            deployed = self._remote_state.resource_deployed_values(resource)
            shared_plan_epilogue.insert(
                0,
                models.APICall(
                    method_name='get_rest_api',
                    params={'rest_api_id': Variable('rest_api_id')},
                    output_var='rest_api')
            )
            shared_plan_patch_ops.append({
                'op': 'replace',
                'path': StringFormat(
                    '/endpointConfiguration/types/%s' % (
                        '{rest_api[endpointConfiguration][types][0]}'),
                    ['rest_api']),
                'value': resource.endpoint_type}
            )
            plan = shared_plan_preamble + [
                models.StoreValue(
                    name='rest_api_id',
                    value=deployed['rest_api_id']),
                models.RecordResourceVariable(
                    resource_type='rest_api',
                    resource_name=resource.resource_name,
                    name='rest_api_id',
                    variable_name='rest_api_id',
                ),
                (models.APICall(
                    method_name='update_api_from_swagger',
                    params={
                        'rest_api_id': Variable('rest_api_id'),
                        'swagger_document': resource.swagger_doc,
                    },
                ), "Updating rest API\n"),
            ]

        plan.extend(shared_plan_epilogue)

        if resource.domain_name:
            custom_domain_plan = self._add_custom_domain_plan(
                resource.domain_name, resource.endpoint_type
            )
            plan += custom_domain_plan
        return plan

    def _add_custom_domain_plan(self, resource, endpoint_type):
        # type: (models.DomainName, str) -> Sequence[InstructionMsg]
        result = []  # type: List[InstructionMsg]
        custom_domain_plan = self._add_domainname_plan(
            resource, endpoint_type
        )
        result += custom_domain_plan
        api_mapping_plan = self._add_apimapping_plan(
            resource.api_mapping, resource
        )
        result += api_mapping_plan
        return result

    def _get_role_arn(self, resource):
        # type: (models.IAMRole) -> Union[str, Variable]
        if isinstance(resource, models.PreCreatedIAMRole):
            return resource.role_arn
        elif isinstance(resource, models.ManagedIAMRole):
            return Variable('%s_role_arn' % resource.role_name)
        # Make mypy happy.
        raise RuntimeError("Unknown resource type: %s" % resource)

    def _batch_record_resource(self, resource_type, resource_name,
                               mapping):
        # type: (str, str, Dict[str, Any]) -> List[InstructionMsg]
        # This is a helper function for recording multiple values into
        # the same resource dict.  The mapping is the set of variables
        # you want to record.  If the value in a pair is a Variable type,
        # then RecordResourceVariable is used, otherwise, RecordResourceValue
        # is used.
        instructions = []  # type: List[InstructionMsg]
        for key, value in mapping.items():
            instruction = cast(InstructionMsg, None)
            if isinstance(value, Variable):
                instruction = models.RecordResourceVariable(
                    resource_type=resource_type,
                    resource_name=resource_name,
                    name=key,
                    variable_name=value.name
                )
            else:
                instruction = models.RecordResourceValue(
                    resource_type=resource_type,
                    resource_name=resource_name,
                    name=key,
                    value=value
                )
            instructions.append(instruction)
        return instructions


class NoopPlanner(PlanStage):
    def __init__(self):
        # type: () -> None
        pass

    def execute(self, resources):
        # type: (List[models.Model]) -> models.Plan
        return models.Plan(instructions=[], messages={})


class Variable(object):
    def __init__(self, name):
        # type: (str) -> None
        self.name = name

    def __repr__(self):
        # type: () -> str
        return 'Variable("%s")' % self.name

    def __eq__(self, other):
        # type: (Any) -> bool
        return isinstance(other, Variable) and self.name == other.name


class StringFormat(object):
    def __init__(self, template, variables):
        # type: (str, List[str]) -> None
        self.template = template
        self.variables = variables

    def __repr__(self):
        # type: () -> str
        return 'StringFormat("%s")' % self.template

    def __eq__(self, other):
        # type: (Any) -> bool
        return (
            isinstance(other, StringFormat) and
            self.template == other.template and
            self.variables == other.variables
        )


class PlanEncoder(json.JSONEncoder):
    # pylint false positive overriden below
    # https://github.com/PyCQA/pylint/issues/414
    def default(self, o):  # pylint: disable=E0202
        # type: (Any) -> Any
        if isinstance(o, StringFormat):
            return o.template
        return o


class KeyDataVariable(object):
    def __init__(self, name, key):
        # type: (str, str) -> None
        self.name = name
        self.key = key

    def __repr__(self):
        # type: () -> str
        return 'KeyDataVariable("%s", "%s")' % (self.name, self.key)

    def __eq__(self, other):
        # type: (Any) -> bool
        return (
            isinstance(other, KeyDataVariable) and
            self.name == other.name and
            self.key == other.key
        )
