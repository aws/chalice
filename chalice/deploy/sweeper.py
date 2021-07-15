from typing import ( # noqa
    List,
    Dict,
    Optional,
    Tuple,
    Any,
    Union,
    Sequence,
    cast,
)

from chalice.config import Config, DeployedResources  # noqa
from chalice.deploy import models
from chalice.deploy.planner import Variable
from chalice.deploy.models import Instruction, StoreMultipleValue  # noqa

MarkedResource = Dict[str, List[models.RecordResource]]
ResourceValueType = Dict[str, Union[Sequence[Instruction], str]]
HandlerArgsType = List[Union[Dict[str, Any], str]]


class ResourceSweeper(object):

    specific_resources = (
        's3_event',
        'sns_event',
        'sqs_event',
        'kinesis_event',
        'dynamodb_event',
        'domain_name'
    )

    def __init__(self):
        # type: () -> None
        self.plan = models.Plan()
        self.marked = {}  # type: Dict

    def execute(self, plan, config):
        # type: (models.Plan, Config) -> None
        self.plan = plan
        self.marked = self._mark_resources()

        deployed = config.deployed_resources(config.chalice_stage)
        if deployed is not None:
            remaining = self._determine_remaining(deployed)
            self._plan_deletion(remaining, deployed)

    def _determine_sns_event(self, name, resource_values):
        # type: (str, Dict[str, str]) -> Optional[str]
        existing_topic = resource_values['topic']
        referenced_topic = [instruction for instruction in self.marked[name]
                            if instruction.name == 'topic' and
                            isinstance(instruction,
                                       models.RecordResourceValue)][0]
        if referenced_topic.value != existing_topic:
            return name
        return None

    def _determine_s3_event(self, name, resource_values):
        # type: (str, Dict[str, str]) -> Optional[str]
        # Special case, we have to check the resource values
        # to see if they've changed.  For s3 events, the resource
        # name is not tied to the bucket, which means if you change
        # the bucket, the resource name will stay the same.
        # So we match up the bucket referenced in the instruction
        # and the bucket recorded in the deployed values match up.
        # If they don't then we need to clean up the bucket config
        # referenced in the deployed values.
        bucket = [instruction for instruction in self.marked[name]
                  if instruction.name == 'bucket' and
                  isinstance(instruction,
                             models.RecordResourceValue)][0]
        if bucket.value != resource_values['bucket']:
            return name
        return None

    def _determine_sqs_event(self, name, resource_values):
        # type: (str, Dict[str, str]) -> Optional[str]
        existing_queue = resource_values['queue']
        referenced_queue = [instruction for instruction in self.marked[name]
                            if instruction.name == 'queue' and
                            isinstance(instruction,
                                       models.RecordResourceValue)][0]
        if referenced_queue.value != existing_queue:
            return name
        return None

    def _determine_kinesis_event(self, name, resource_values):
        # type: (str, Dict[str, str]) -> Optional[str]
        existing_stream = resource_values['stream']
        referenced_stream = [instruction for instruction in self.marked[name]
                             if instruction.name == 'stream' and
                             isinstance(instruction,
                                        models.RecordResourceValue)][0]
        if referenced_stream.value != existing_stream:
            return name
        return None

    def _determine_dynamodb_event(self, name, resource_values):
        # type: (str, Dict[str, str]) -> Optional[str]
        existing_stream_arn = resource_values['stream_arn']
        referenced_stream = [instruction for instruction in self.marked[name]
                             if instruction.name == 'stream_arn' and
                             isinstance(instruction,
                                        models.RecordResourceValue)][0]
        if referenced_stream.value != existing_stream_arn:
            return name
        return None

    def _determine_domain_name(self, name, resource_values):
        # type: (str, Dict[str, Any]) -> Optional[List[str]]
        api_mapping = resource_values.get('api_mapping')
        if not api_mapping:
            return None

        deployed_api_mappings_ids = {
            api_map['key']
            for api_map in api_mapping
        }
        api_mapping_data = (
            'rest_api_mapping',
            'websocket_api_mapping'
        )

        instructions = self.plan.instructions

        planned_api_mappings_ids = {
            instr.value[0]['key']
            for instr in instructions
            if isinstance(instr, StoreMultipleValue) and
            (instr.name in api_mapping_data and
                isinstance(instr.value[0], dict))
        }

        api_mappings_to_remove = list(
            deployed_api_mappings_ids - planned_api_mappings_ids
        )

        result_api_mappings = [
            "%s.api_mapping.%s" % (name, api_map)
            for api_map in api_mappings_to_remove
        ]
        return result_api_mappings

    def _determine_remaining(self, deployed):
        # type: (DeployedResources) -> List[str]
        remaining = []
        deployed_resource_names = reversed(deployed.resource_names())

        for name in deployed_resource_names:
            resource_values = deployed.resource_values(name)
            if name not in self.marked:
                remaining.append(name)
            elif resource_values['resource_type'] in self.specific_resources:
                method = '_determine_%s' % resource_values['resource_type']
                handler = getattr(self, method)
                resource_name = handler(name, resource_values)
                if resource_name:
                    if isinstance(resource_name, list):
                        remaining.extend(resource_name)
                    else:
                        remaining.append(resource_name)
        return remaining

    def _mark_resources(self):
        # type: () -> MarkedResource
        marked = {}  # type: MarkedResource
        for instruction in self.plan.instructions:
            if isinstance(instruction, models.RecordResource):
                marked.setdefault(instruction.resource_name, []).append(
                    instruction)
        return marked

    def _delete_domain_name(self,
                            resource_values  # type: Dict[str, Any]
                            ):
        # type: (...) -> ResourceValueType
        params = {
            'domain_name': resource_values['domain_name']
        }
        msg = 'Deleting custom domain name: %s\n' % resource_values['name']
        return {
            'instructions': (
                models.APICall(
                    method_name='delete_domain_name',
                    params=params,
                ),
            ),
            'message': msg
        }

    def _delete_api_mapping(self,
                            domain_name,   # type: str
                            api_mapping    # type: Dict[str, Any]
                            ):
        # type: (...) -> ResourceValueType
        if api_mapping['key'] == '/':
            path_key = '(none)'
        else:
            path_key = api_mapping['key'].lstrip("/")

        params = {
            'domain_name': domain_name,
            'path_key': path_key
        }
        msg = 'Deleting base path mapping from %s custom domain name: %s\n' % (
            domain_name, api_mapping['key']
        )
        return {
            'instructions': (
                models.APICall(
                    method_name='delete_api_mapping',
                    params=params,
                ),
            ),
            'message': msg
        }

    def _delete_lambda_function(self,
                                resource_values  # type: Dict[str, Any]
                                ):
        # type: (...) -> ResourceValueType
        msg = 'Deleting function: %s\n' % resource_values['lambda_arn']
        return {
            'instructions': (
                models.APICall(
                    method_name='delete_function',
                    params={'function_name': resource_values['lambda_arn']},
                ),
            ),
            'message': msg
        }

    def _delete_lambda_layer(self, resource_values):
        # type: (Dict[str, str]) -> ResourceValueType
        apicall = models.APICall(
            method_name='delete_layer_version',
            params={'layer_version_arn': resource_values[
                'layer_version_arn']})
        return {
            'instructions': (apicall,),
            'message': (
                "Deleting layer version: %s\n"
                % resource_values['layer_version_arn']
            )
        }

    def _delete_iam_role(self, resource_values):
        # type: (Dict[str, Any]) -> ResourceValueType
        return {
            'instructions': (
                models.APICall(
                    method_name='delete_role',
                    params={'name': resource_values['role_name']},
                ),
            ),
            'message': 'Deleting IAM role: %s\n' % resource_values['role_name']
        }

    def _delete_cloudwatch_event(self, resource_values):
        # type: (Dict[str, Any]) -> ResourceValueType
        return {
            'instructions': (
                models.APICall(
                    method_name='delete_rule',
                    params={'rule_name': resource_values['rule_name']},
                ),
            )
        }

    def _delete_rest_api(self, resource_values):
        # type: (Dict[str, Any]) -> ResourceValueType
        msg = 'Deleting Rest API: %s\n' % resource_values['rest_api_id']
        return {
            'instructions': (
                models.APICall(
                    method_name='delete_rest_api',
                    params={'rest_api_id': resource_values['rest_api_id']}
                ),
            ),
            'message': msg
        }

    def _delete_s3_event(self, resource_values):
        # type: (Dict[str, Any]) -> ResourceValueType
        bucket = resource_values['bucket']
        function_arn = resource_values['lambda_arn']
        return {
            'instructions': (
                models.BuiltinFunction('parse_arn', [function_arn],
                                       output_var='parsed_lambda_arn'),
                models.JPSearch('account_id', input_var='parsed_lambda_arn',
                                output_var='account_id'),
                models.APICall(
                    method_name='disconnect_s3_bucket_from_lambda',
                    params={'bucket': bucket, 'function_arn': function_arn}
                ),
                models.APICall(
                    method_name='remove_permission_for_s3_event',
                    params={'bucket': bucket, 'function_arn': function_arn,
                            'account_id': Variable('account_id')}
                ),
            )
        }

    def _delete_sns_event(self, resource_values):
        # type: (Dict[str, Any]) -> ResourceValueType
        subscription_arn = resource_values['subscription_arn']
        return {
            'instructions': (
                models.APICall(
                    method_name='unsubscribe_from_topic',
                    params={'subscription_arn': subscription_arn},
                ),
                models.APICall(
                    method_name='remove_permission_for_sns_topic',
                    params={
                        'topic_arn': resource_values['topic_arn'],
                        'function_arn': resource_values['lambda_arn'],
                    },
                ),
            )
        }

    def _delete_sqs_event(self, resource_values):
        # type: (Dict[str, Any]) -> ResourceValueType
        return {
            'instructions': (
                models.APICall(
                    method_name='remove_lambda_event_source',
                    params={'event_uuid': resource_values['event_uuid']},
                ),
            )
        }

    def _delete_kinesis_event(self, resource_values):
        # type: (Dict[str, Any]) -> ResourceValueType
        return {
            'instructions': (
                models.APICall(
                    method_name='remove_lambda_event_source',
                    params={'event_uuid': resource_values['event_uuid']},
                ),
            )
        }

    def _delete_dynamodb_event(self, resource_values):
        # type: (Dict[str, Any]) -> ResourceValueType
        return {
            'instructions': (
                models.APICall(
                    method_name='remove_lambda_event_source',
                    params={'event_uuid': resource_values['event_uuid']},
                ),
            )
        }

    def _delete_websocket_api(self, resource_values):
        # type: (Dict[str, Any]) -> ResourceValueType
        msg = 'Deleting Websocket API: %s\n' % (
            resource_values['websocket_api_id']
        )
        return {
            'instructions': (
                models.APICall(
                    method_name='delete_websocket_api',
                    params={'api_id': resource_values['websocket_api_id']},
                ),
            ),
            'message': msg
        }

    def _default_delete(self, resource_values):
        # type: (Dict[str, Any]) -> None
        err_msg = "Sweeper encountered an unknown resource: %s" % \
                  resource_values
        raise RuntimeError(err_msg)

    def _update_plan(self, instructions, message=None, insert=False):
        # type: (Tuple[Instruction], Optional[str], bool) -> None
        if insert:
            for instruction in instructions:
                self.plan.instructions.insert(
                    0, cast(Instruction, instruction)
                )
            if message:
                instr_id = id(self.plan.instructions[0])
                self.plan.messages[instr_id] = cast(
                    str, message
                )
        else:
            self.plan.instructions.extend(instructions)
            if message:
                self.plan.messages[id(self.plan.instructions[-1])] = message

    def _delete_domain_api_mappings(self, resource_values, name):
        # type: (Dict[str, Any], str) -> ResourceValueType
        path_key = name.split('.')[-1]

        api_mapping = {
            k: v
            for api_map in resource_values['api_mapping']
            for k, v in api_map.items()
            if api_map['key'] == path_key
        }  # type: Dict[str, str]

        resource_data = self._delete_api_mapping(
            resource_values['domain_name'],
            api_mapping
        )
        return resource_data

    def _plan_deletion(self,
                       remaining,  # type: List[str]
                       deployed,   # type: DeployedResources
                       ):
        # type: (...) -> None
        for name in remaining:
            resource_values = deployed.resource_values(name)

            resource_type = resource_values['resource_type']
            handler_args = [resource_values]  # type: HandlerArgsType
            insert = False
            if 'api_mapping' in name:
                resource_type = 'domain_api_mappings'
                handler_args.append(name)
                insert = True

            method_name = '_delete_%s' % resource_type
            handler = getattr(self, method_name, self._default_delete)
            resource_data = handler(*handler_args)
            instructions = cast(
                Tuple[Instruction],
                resource_data['instructions']
            )
            message = cast(Optional[str], resource_data.get('message'))
            self._update_plan(
                instructions,
                message,
                insert=insert
            )
