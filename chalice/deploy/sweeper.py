from typing import List, Dict, Tuple  # noqa

from chalice.config import Config, DeployedResources  # noqa
from chalice.deploy import models


MarkedResource = Dict[str, List[models.RecordResource]]


class ResourceSweeper(object):

    def execute(self, plan, config):
        # type: (models.Plan, Config) -> None
        instructions = plan.instructions
        marked = self._mark_resources(instructions)
        deployed = config.deployed_resources(config.chalice_stage)
        if deployed is not None:
            remaining = self._determine_remaining(plan, deployed, marked)
            self._plan_deletion(instructions, plan.messages,
                                remaining, deployed)

    def _determine_remaining(self, plan, deployed, marked):
        # type: (models.Plan, DeployedResources, MarkedResource) -> List[str]
        remaining = []
        deployed_resource_names = reversed(deployed.resource_names())
        for name in deployed_resource_names:
            resource_values = deployed.resource_values(name)
            if name not in marked:
                remaining.append(name)
            elif resource_values['resource_type'] == 's3_event':
                # Special case, we have to check the resource values
                # to see if they've changed.  For s3 events, the resource
                # name is not tied to the bucket, which means if you change
                # the bucket, the resource name will stay the same.
                # So we match up the bucket referenced in the instruction
                # and the bucket recorded in the deployed values match up.
                # If they don't then we need to clean up the bucket config
                # referenced in the deployed values.
                bucket = [instruction for instruction in marked[name]
                          if instruction.name == 'bucket' and
                          isinstance(instruction,
                                     models.RecordResourceValue)][0]
                if bucket.value != resource_values['bucket']:
                    remaining.append(name)
            elif resource_values['resource_type'] == 'sns_event':
                existing_topic = resource_values['topic']
                referenced_topic = [instruction for instruction in marked[name]
                                    if instruction.name == 'topic' and
                                    isinstance(instruction,
                                               models.RecordResourceValue)][0]
                if referenced_topic.value != existing_topic:
                    remaining.append(name)
            elif resource_values['resource_type'] == 'sqs_event':
                existing_queue = resource_values['queue']
                referenced_queue = [instruction for instruction in marked[name]
                                    if instruction.name == 'queue' and
                                    isinstance(instruction,
                                               models.RecordResourceValue)][0]
                if referenced_queue.value != existing_queue:
                    remaining.append(name)
        return remaining

    def _mark_resources(self, plan):
        # type: (List[models.Instruction]) -> MarkedResource
        marked = {}  # type: MarkedResource
        for instruction in plan:
            if isinstance(instruction, models.RecordResource):
                marked.setdefault(instruction.resource_name, []).append(
                    instruction)
        return marked

    def _handle_lambda_function(self, resource_values):
        # type: (Dict[str, str]) -> Tuple[List[models.APICall], Dict[int, str]]
        apicall = models.APICall(
            method_name='delete_function',
            params={'function_name': resource_values['lambda_arn']},)
        return [apicall], {
            id(apicall): (
                "Deleting function: %s\n" % resource_values['lambda_arn'])}

    def _handle_lambda_layer(self, resource_values):
        # type: (Dict[str, str]) -> Tuple[List[models.APICall], Dict[int, str]]
        apicall = models.APICall(
            method_name='delete_layer_version',
            params={'layer_version_arn': resource_values[
                'layer_version_arn']})
        return [apicall], {
            id(apicall): "Deleting layer version: %s\n" % resource_values[
                'layer_version_arn']}

    def _handle_iam_role(self, resource_values):
        # type: (Dict[str, str]) -> Tuple[List[models.APICall], Dict[int, str]]
        apicall = models.APICall(
            method_name='delete_role',
            params={'name': resource_values['role_name']})
        return [apicall], {id(apicall): (
            "Deleting IAM role: %s\n" % resource_values['role_name'])}

    def _handle_cloudwatch_event(self, resource_values):
        # type: (Dict[str, str]) -> Tuple[List[models.APICall], Dict[int, str]]
        apicall = models.APICall(
            method_name='delete_rule',
            params={'rule_name': resource_values['rule_name']})
        return [apicall], {}

    def _handle_rest_api(self, resource_values):
        # type: (Dict[str, str]) -> Tuple[List[models.APICall], Dict[int, str]]
        rest_api_id = resource_values['rest_api_id']
        apicall = models.APICall(
            method_name='delete_rest_api',
            params={'rest_api_id': rest_api_id})
        return [apicall], {id(apicall): (
            "Deleting Rest API: %s\n" % resource_values['rest_api_id'])}

    def _handle_s3_event(self, resource_values):
        # type: (Dict[str, str]) -> Tuple[List[models.APICall], Dict[int, str]]
        bucket = resource_values['bucket']
        function_arn = resource_values['lambda_arn']
        return [
            models.APICall(
                method_name='disconnect_s3_bucket_from_lambda',
                params={'bucket': bucket, 'function_arn': function_arn}
            ),
            models.APICall(
                method_name='remove_permission_for_s3_event',
                params={'bucket': bucket, 'function_arn': function_arn}
            )], {}

    def _handle_sns_event(self, resource_values):
        # type: (Dict[str, str]) -> Tuple[List[models.APICall], Dict[int, str]]
        subscription_arn = resource_values['subscription_arn']
        return [
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
            )
        ], {}

    def _handle_sqs_event(self, resource_values):
        # type: (Dict[str, str]) -> Tuple[List[models.APICall], Dict[int, str]]
        return [
            models.APICall(
                method_name='remove_sqs_event_source',
                params={'event_uuid': resource_values['event_uuid']},
            )
        ], {}

    def _handle_websocket_api(self, resource_values):
        # type: (Dict[str, str]) -> Tuple[List[models.APICall], Dict[int, str]]
        apicall = models.APICall(
            method_name='delete_websocket_api',
            params={'api_id': resource_values['websocket_api_id']})
        return [apicall], {id(apicall): (
            "Deleting Websocket API: %s\n" % resource_values[
                'websocket_api_id'])}

    def _plan_deletion(self,
                       plan,       # type: List[models.Instruction]
                       messages,   # type: Dict[int, str]
                       remaining,  # type: List[str]
                       deployed,   # type: DeployedResources
                       ):
        # type: (...) -> None
        for name in remaining:
            resource_values = deployed.resource_values(name)
            handler = getattr(
                self, '_handle_%s' % resource_values['resource_type'])
            resource_calls, resource_messages = handler(resource_values)
            plan.extend(resource_calls)
            messages.update(resource_messages)
