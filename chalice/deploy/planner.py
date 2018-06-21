from typing import List, Dict, Any, Optional, Union, Tuple, Set, cast  # noqa
from typing import Sequence  # noqa

from chalice.config import Config, DeployedResources  # noqa
from chalice.utils import OSUtils  # noqa
from chalice.deploy import models
from chalice.awsclient import TypedAWSClient, ResourceDoesNotExistError  # noqa


_INSTRUCTION_MSG = Union[models.Instruction, Tuple[models.Instruction, str]]
_MARKED_RESOURCE = Dict[str, List[models.RecordResource]]


class RemoteState(object):
    def __init__(self, client, deployed_resources):
        # type: (TypedAWSClient, DeployedResources) -> None
        self._client = client
        self._cache = {}  # type: Dict[Tuple[str, str], bool]
        self._deployed_resources = deployed_resources

    def _cache_key(self, resource):
        # type: (models.ManagedModel) -> Tuple[str, str]
        return (resource.resource_type, resource.resource_name)

    def resource_deployed_values(self, resource):
        # type: (models.ManagedModel) -> Dict[str, str]
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

    def resource_exists(self, resource):
        # type: (models.ManagedModel) -> bool
        key = self._cache_key(resource)
        if key in self._cache:
            return self._cache[key]
        try:
            handler = getattr(self, '_resource_exists_%s'
                              % resource.__class__.__name__.lower())
        except AttributeError:
            raise ValueError("RemoteState received an unsupported resource: %s"
                             % resource.resource_type)
        result = handler(resource)
        self._cache[key] = result
        return result

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

    def _resource_exists_restapi(self, resource):
        # type: (models.RestAPI) -> bool
        try:
            deployed_values = self._deployed_resources.resource_values(
                resource.resource_name)
        except ValueError:
            return False
        rest_api_id = deployed_values['rest_api_id']
        return self._client.rest_api_exists(rest_api_id)


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
        # type: (models.Plan, DeployedResources, _MARKED_RESOURCE) -> List[str]
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
        return remaining

    def _mark_resources(self, plan):
        # type: (List[models.Instruction]) -> _MARKED_RESOURCE
        marked = {}  # type: _MARKED_RESOURCE
        for instruction in plan:
            if isinstance(instruction, models.RecordResource):
                marked.setdefault(instruction.resource_name, []).append(
                    instruction)
        return marked

    def _plan_deletion(self,
                       plan,       # type: List[models.Instruction]
                       messages,   # type: Dict[int, str]
                       remaining,  # type: List[str]
                       deployed,   # type: DeployedResources
                       ):
        # type: (...) -> None
        for name in remaining:
            resource_values = deployed.resource_values(name)
            if resource_values['resource_type'] == 'lambda_function':
                apicall = models.APICall(
                    method_name='delete_function',
                    params={'function_name': resource_values['lambda_arn']},)
                messages[id(apicall)] = (
                    "Deleting function: %s\n" % resource_values['lambda_arn'])
                plan.append(apicall)
            elif resource_values['resource_type'] == 'iam_role':
                apicall = models.APICall(
                    method_name='delete_role',
                    params={'name': resource_values['role_name']},
                )
                messages[id(apicall)] = (
                    "Deleting IAM role: %s\n" % resource_values['role_name'])
                plan.append(apicall)
            elif resource_values['resource_type'] == 'cloudwatch_event':
                apicall = models.APICall(
                    method_name='delete_rule',
                    params={'rule_name': resource_values['rule_name']},
                )
                plan.append(apicall)
            elif resource_values['resource_type'] == 'rest_api':
                rest_api_id = resource_values['rest_api_id']
                apicall = models.APICall(
                    method_name='delete_rest_api',
                    params={'rest_api_id': rest_api_id}
                )
                messages[id(apicall)] = (
                    "Deleting Rest API: %s\n" % resource_values['rest_api_id'])
                plan.append(apicall)
            elif resource_values['resource_type'] == 's3_event':
                bucket = resource_values['bucket']
                function_arn = resource_values['lambda_arn']
                apicall = models.APICall(
                    method_name='disconnect_s3_bucket_from_lambda',
                    params={'bucket': bucket, 'function_arn': function_arn}
                )
                plan.append(apicall)


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
                            result,    # type: Sequence[_INSTRUCTION_MSG]
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

    def _plan_lambdafunction(self, resource):
        # type: (models.LambdaFunction) -> Sequence[_INSTRUCTION_MSG]
        role_arn = self._get_role_arn(resource.role)
        # Make mypy happy, it complains if we don't "declare" this upfront.
        params = {}  # type: Dict[str, Any]
        varname = '%s_lambda_arn' % resource.resource_name
        # Not sure the best way to express this via mypy, but we know
        # that in the build stage we replace the deployment package
        # name with the actual filename generated from the pip
        # packager.  For now we resort to a cast.
        filename = cast(str, resource.deployment_package.filename)
        concurrency_method_name = ''

        concurrency_params = {}  # type: Dict[str, Any]
        concurrency_params['function_name'] = resource.function_name
        if resource.reserved_concurrency is None:
            concurrency_method_name = 'delete_function_concurrency'
        else:
            concurrency_method_name = 'put_function_concurrency'
            concurrency_params.update({
                'reserved_concurrent_executions': resource.reserved_concurrency
            })

        api_calls = []  # type: List[_INSTRUCTION_MSG]

        if not self._remote_state.resource_exists(resource):
            params = {
                'function_name': resource.function_name,
                'role_arn': role_arn,
                'zip_contents': self._osutils.get_file_contents(
                    filename, binary=True),
                'runtime': resource.runtime,
                'handler': resource.handler,
                'environment_variables': resource.environment_variables,
                'tags': resource.tags,
                'timeout': resource.timeout,
                'memory_size': resource.memory_size,
                'security_group_ids': resource.security_group_ids,
                'subnet_ids': resource.subnet_ids,
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
                'tags': resource.tags,
                'timeout': resource.timeout,
                'memory_size': resource.memory_size,
                'security_group_ids': resource.security_group_ids,
                'subnet_ids': resource.subnet_ids,
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

        api_calls.append((models.APICall(
            method_name=concurrency_method_name,
            params=concurrency_params,
            output_var='reserved_concurrency_result',
        ), "Updating lambda function concurrency limit: %s\n" %
            resource.function_name))

        return api_calls

    def _plan_managediamrole(self, resource):
        # type: (models.ManagedIAMRole) -> Sequence[_INSTRUCTION_MSG]
        document = resource.policy.document
        role_exists = self._remote_state.resource_exists(resource)
        varname = '%s_role_arn' % resource.role_name
        if not role_exists:
            return [
                (models.APICall(
                    method_name='create_role',
                    params={'name': resource.role_name,
                            'trust_policy': resource.trust_policy,
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

    def _plan_s3bucketnotification(self, resource):
        # type: (models.S3BucketNotification) -> Sequence[_INSTRUCTION_MSG]
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

    def _plan_scheduledevent(self, resource):
        # type: (models.ScheduledEvent) -> Sequence[_INSTRUCTION_MSG]
        function_arn = Variable(
            '%s_lambda_arn' % resource.lambda_function.resource_name
        )
        # Because the underlying API calls have PUT semantics,
        # we don't have to check if the resource exists and have
        # a separate code path for updates.  We could however
        # check if the resource exists to avoid unnecessary API
        # calls, but that's a later optimization.
        plan = [
            models.APICall(
                method_name='get_or_create_rule_arn',
                params={'rule_name': resource.rule_name,
                        'schedule_expression': resource.schedule_expression},
                output_var='rule-arn',
            ),
            models.APICall(
                method_name='connect_rule_to_lambda',
                params={'rule_name': resource.rule_name,
                        'function_arn': function_arn}
            ),
            models.APICall(
                method_name='add_permission_for_scheduled_event',
                params={'rule_arn': Variable('rule-arn'),
                        'function_arn': function_arn},
            ),
            # You need to remote targets (which have IDs)
            # before you can delete a rule.
            models.RecordResourceValue(
                resource_type='cloudwatch_event',
                resource_name=resource.resource_name,
                name='rule_name',
                value=resource.rule_name,
            )
        ]
        return plan

    def _plan_restapi(self, resource):
        # type: (models.RestAPI) -> Sequence[_INSTRUCTION_MSG]
        function = resource.lambda_function
        function_name = function.function_name
        varname = '%s_lambda_arn' % function.resource_name
        lambda_arn_var = Variable(varname)
        # There's a set of shared instructions that are needed
        # in both the update as well as the initial create case.
        # That's what this shared_plan_premable is for.
        shared_plan_preamble = [
            # The various API gateway API calls need
            # to know the region name and account id so
            # we'll take care of that up front and store
            # them in variables.
            models.BuiltinFunction(
                'parse_arn',
                [lambda_arn_var],
                output_var='parsed_lambda_arn',
            ),
            models.JPSearch('account_id',
                            input_var='parsed_lambda_arn',
                            output_var='account_id'),
            models.JPSearch('region',
                            input_var='parsed_lambda_arn',
                            output_var='region_name'),
            # The swagger doc uses the 'api_handler_lambda_arn'
            # var name so we need to make sure we populate this variable
            # before importing the rest API.
            models.CopyVariable(from_var=varname,
                                to_var='api_handler_lambda_arn'),
        ]  # type: List[_INSTRUCTION_MSG]
        # There's also a set of instructions that are needed
        # at the end of deploying a rest API that apply to both
        # the update and create case.
        shared_plan_epilogue = [
            models.APICall(
                method_name='add_permission_for_apigateway_if_needed',
                params={'function_name': function_name,
                        'region_name': Variable('region_name'),
                        'account_id': Variable('account_id'),
                        'rest_api_id': Variable('rest_api_id')},
            ),
            models.StoreValue(
                name='rest_api_url',
                value=StringFormat(
                    'https://{rest_api_id}.execute-api.{region_name}'
                    '.amazonaws.com/%s/' % resource.api_gateway_stage,
                    ['rest_api_id', 'region_name'],
                ),
            ),
            models.RecordResourceVariable(
                resource_type='rest_api',
                resource_name=resource.resource_name,
                name='rest_api_url',
                variable_name='rest_api_url',
            ),
        ]  # type: List[_INSTRUCTION_MSG]
        for auth in resource.authorizers:
            shared_plan_epilogue.append(
                models.APICall(
                    method_name='add_permission_for_apigateway_if_needed',
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
                    params={'swagger_document': resource.swagger_doc},
                    output_var='rest_api_id',
                ), "Creating Rest API\n"),
                models.RecordResourceVariable(
                    resource_type='rest_api',
                    resource_name=resource.resource_name,
                    name='rest_api_id',
                    variable_name='rest_api_id',
                ),
                models.APICall(
                    method_name='deploy_rest_api',
                    params={'rest_api_id': Variable('rest_api_id'),
                            'api_gateway_stage': resource.api_gateway_stage},
                ),
            ] + shared_plan_epilogue
        else:
            deployed = self._remote_state.resource_deployed_values(resource)
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
                models.APICall(
                    method_name='deploy_rest_api',
                    params={'rest_api_id': Variable('rest_api_id'),
                            'api_gateway_stage': resource.api_gateway_stage},
                ),
                models.APICall(
                    method_name='add_permission_for_apigateway_if_needed',
                    params={'function_name': function_name,
                            'region_name': Variable('region_name'),
                            'account_id': Variable('account_id'),
                            'rest_api_id': Variable('rest_api_id')},
                ),
            ] + shared_plan_epilogue
        return plan

    def _get_role_arn(self, resource):
        # type: (models.IAMRole) -> Union[str, Variable]
        if isinstance(resource, models.PreCreatedIAMRole):
            return resource.role_arn
        elif isinstance(resource, models.ManagedIAMRole):
            return Variable('%s_role_arn' % resource.role_name)
        # Make mypy happy.
        raise RuntimeError("Unknown resource type: %s" % resource)


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
