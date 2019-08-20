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
from chalice.deploy.models import Instruction, StoreMultipleValue  # noqa

MarkedResource = Dict[str, List[models.RecordResource]]
ResourceValueType = Dict[str, Union[Sequence[Instruction], str]]
HandlerArgsType = List[Union[Dict[str, Any], str]]


class ResourceSweeper(object):

    specific_resources = (
        's3_event',
        'sns_event',
        'sqs_event',
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

    def _determine_domain_name(self, name, resource_values):
        # type: (str, Dict[str, Any]) -> Optional[List[str]]
        base_path_mappings = resource_values.get('base_path_mappings')
        if not base_path_mappings:
            return None

        deployed_path_mappings_ids = {
            path_map['id']
            for path_map in base_path_mappings
        }
        path_mapping_data = (
            'rest_base_path_mapping',
            'websocket_base_path_mapping'
        )

        instructions = self.plan.instructions

        planned_path_mappings_ids = {
            instr.value[0]['id']
            for instr in instructions
            if isinstance(instr, StoreMultipleValue) and
            (instr.name in path_mapping_data and
                isinstance(instr.value[0], dict))
        }

        path_mappings_to_remove = list(
            deployed_path_mappings_ids - planned_path_mappings_ids
        )

        result_paths = [
            "%s.base_path_mappings.%s" % (name, path_map)
            for path_map in path_mappings_to_remove
        ]
        return result_paths

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

    def _delete_base_path_mappings(self,
                                   domain_name,         # type: str
                                   base_path_mapping    # type: Dict[str, Any]
                                   ):
        # type: (...) -> ResourceValueType
        params = {
            'domain_name': domain_name,
            'base_path_id': base_path_mapping['id']
        }
        msg = 'Deleting base path mapping from %s custom domain name: %s\n' % (
            domain_name, base_path_mapping['key']
        )
        return {
            'instructions': (
                models.APICall(
                    method_name='delete_base_path_mapping',
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
                models.APICall(
                    method_name='disconnect_s3_bucket_from_lambda',
                    params={'bucket': bucket, 'function_arn': function_arn}
                ),
                models.APICall(
                    method_name='remove_permission_for_s3_event',
                    params={'bucket': bucket, 'function_arn': function_arn}
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
                    method_name='remove_sqs_event_source',
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

    def _delete_domain_base_path_mappings(self, resource_values, name):
        # type: (Dict[str, Any], str) -> ResourceValueType
        path_id = name.split('.')[-1]

        base_path_mapping = {
            k: v
            for path_map in resource_values['base_path_mappings']
            for k, v in path_map.items()
            if path_map['id'] == path_id
        }  # type: Dict[str, str]

        resource_data = self._delete_base_path_mappings(
            resource_values['domain_name'],
            base_path_mapping
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
            if 'base_path_mappings' in name:
                resource_type = 'domain_base_path_mappings'
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
