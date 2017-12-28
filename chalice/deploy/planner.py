import json

import attr
from typing import List, Dict, Any, Optional, Union, Tuple, Set, cast  # noqa

from chalice.config import Config, DeployedResources2  # noqa
from chalice.utils import OSUtils  # noqa
from chalice.deploy import models
from chalice.awsclient import TypedAWSClient, ResourceDoesNotExistError  # noqa


class RemoteState(object):
    def __init__(self, client):
        # type: (TypedAWSClient) -> None
        self._client = client
        self._cache = {}  # type: Dict[Tuple[str, str], bool]

    def _cache_key(self, resource):
        # type: (models.ManagedModel) -> Tuple[str, str]
        return (resource.resource_type, resource.resource_name)

    def resource_exists(self, resource):
        # type: (models.ManagedModel) -> bool
        key = self._cache_key(resource)
        if key in self._cache:
            return self._cache[key]
        # TODO: This code will likely be refactored and pulled into
        # per-resource classes so the RemoteState object doesn't need
        # to know about every type of resource.
        if isinstance(resource, models.ManagedIAMRole):
            result = self._resource_exists_iam_role(resource)
        elif isinstance(resource, models.LambdaFunction):
            result = self._resource_exists_lambda_function(resource)
        self._cache[key] = result
        return result

    def _resource_exists_lambda_function(self, resource):
        # type: (models.LambdaFunction) -> bool
        return self._client.lambda_function_exists(resource.function_name)

    def _resource_exists_iam_role(self, resource):
        # type: (models.ManagedIAMRole) -> bool
        try:
            self._client.get_role_arn_for_name(resource.role_name)
            return True
        except ResourceDoesNotExistError:
            return False

    def get_remote_model(self, resource):
        # type: (models.ManagedIAMRole) -> Optional[models.ManagedModel]
        # We only need ManagedIAMRole support for now, but this will
        # need to grow as needed.
        # TODO: revisit adding caching.  We don't need to make 2 API calls
        # here.
        if not self.resource_exists(resource):
            return None
        role = self._client.get_role(resource.role_name)
        return attr.evolve(resource,
                           trust_policy=role['AssumeRolePolicyDocument'],
                           role_arn=role['Arn'])


class UnreferencedResourcePlanner(object):

    def execute(self, plan, config):
        # type: (List[models.Instruction], Config) -> None
        marked = set(self._mark_resources(plan))
        deployed = config.deployed_resources(config.chalice_stage)
        if deployed is not None:
            deployed_resource_names = reversed(deployed.resource_names())
            remaining = [
                name for name in deployed_resource_names if name not in marked
            ]
            self._plan_deletion(plan, remaining, deployed)

    def _mark_resources(self, plan):
        # type: (List[models.Instruction]) -> List[str]
        marked = []  # type: List[str]
        for instruction in plan:
            if isinstance(instruction, models.RecordResource):
                marked.append(instruction.resource_name)
        return marked

    def _plan_deletion(self,
                       plan,       # type: List[models.Instruction]
                       remaining,  # type: List[str]
                       deployed,   # type: DeployedResources2
                       ):
        # type: (...) -> None
        for name in remaining:
            resource_values = deployed.resource_values(name)
            if resource_values['resource_type'] == 'lambda_function':
                apicall = models.APICall(
                    method_name='delete_function',
                    params={'function_name': resource_values['lambda_arn']},
                )
                plan.append(apicall)
            elif resource_values['resource_type'] == 'iam_role':
                # TODO: Consider adding the role_name to the deployed.json.
                # This is a separate value than the 'name' of the resource.
                # For now we have to parse out the role name from the role_arn
                # and it would be better if we could get the role name
                # directly.
                v = resource_values['role_arn'].rsplit('/')[1]
                apicall = models.APICall(
                    method_name='delete_role',
                    params={'name': v},
                )
                plan.append(apicall)


class PlanStage(object):
    def __init__(self, remote_state, osutils):
        # type: (RemoteState, OSUtils) -> None
        self._remote_state = remote_state
        self._osutils = osutils

    def execute(self, resources):
        # type: (List[models.Model]) -> List[models.Instruction]
        plan = []  # type: List[models.Instruction]
        for resource in resources:
            name = 'plan_%s' % resource.__class__.__name__.lower()
            handler = getattr(self, name, None)
            if handler is not None:
                result = handler(resource)
                if result:
                    plan.extend(result)
        return plan

    # TODO: This code will likely be refactored and pulled into
    # per-resource classes so the PlanStage object doesn't need
    # to know about every type of resource.

    def plan_lambdafunction(self, resource):
        # type: (models.LambdaFunction) -> List[models.Instruction]
        role_arn = self._get_role_arn(resource.role)
        # Make mypy happy, it complains if we don't "declare" this upfront.
        params = {}  # type: Dict[str, Any]
        varname = '%s_lambda_arn' % resource.resource_name
        if not self._remote_state.resource_exists(resource):
            params = {
                'function_name': resource.function_name,
                'role_arn': role_arn,
                'zip_contents': self._osutils.get_file_contents(
                    resource.deployment_package.filename, binary=True),
                'runtime': resource.runtime,
                'handler': resource.handler,
                'environment_variables': resource.environment_variables,
                'tags': resource.tags,
                'timeout': resource.timeout,
                'memory_size': resource.memory_size,
            }
            return [
                models.APICall(
                    method_name='create_function',
                    params=params,
                    resource=resource,
                ),
                models.StoreValue(name=varname),
                models.RecordResourceVariable(
                    resource_type='lambda_function',
                    resource_name=resource.resource_name,
                    name='lambda_arn',
                    variable_name=varname,
                )
            ]
        # TODO: Consider a smarter diff where we check if we even need
        # to do an update() API call.
        params = {
            'function_name': resource.function_name,
            'role_arn': resource.role.role_arn,
            'zip_contents': self._osutils.get_file_contents(
                resource.deployment_package.filename, binary=True),
            'runtime': resource.runtime,
            'environment_variables': resource.environment_variables,
            'tags': resource.tags,
            'timeout': resource.timeout,
            'memory_size': resource.memory_size,
        }
        return [
            models.APICall(
                method_name='update_function',
                params=params,
                resource=resource,
            ),
            models.JPSearch('FunctionArn'),
            models.StoreValue(name=varname),
            models.RecordResourceVariable(
                resource_type='lambda_function',
                resource_name=resource.resource_name,
                name='lambda_arn',
                variable_name=varname,
            )
        ]

    def plan_managediamrole(self, resource):
        # type: (models.ManagedIAMRole) -> List[models.Instruction]
        document = self._get_policy_document(resource.policy)
        role_exists = self._remote_state.resource_exists(resource)
        if not role_exists:
            varname = '%s_role_arn' % resource.role_name
            return [
                models.APICall(
                    method_name='create_role',
                    params={'name': resource.role_name,
                            'trust_policy': resource.trust_policy,
                            'policy': document},
                    resource=resource
                ),
                models.StoreValue(varname),
                models.RecordResourceVariable(
                    resource_type='iam_role',
                    resource_name=resource.resource_name,
                    name='role_arn',
                    variable_name=varname,
                )
            ]
        remote_model = cast(
            models.ManagedIAMRole,
            self._remote_state.get_remote_model(resource),
        )
        resource.role_arn = remote_model.role_arn
        return [
            models.APICall(
                method_name='put_role_policy',
                params={'role_name': resource.role_name,
                        'policy_name': resource.role_name,
                        'policy_document': document},
                resource=resource
            ),
            models.RecordResourceValue(
                resource_type='iam_role',
                resource_name=resource.resource_name,
                name='role_arn',
                value=resource.role_arn,
            )
        ]

    def _get_role_arn(self, resource):
        # type: (models.IAMRole) -> Union[str, Variable]
        if isinstance(resource, models.PreCreatedIAMRole):
            return resource.role_arn
        elif isinstance(resource, models.ManagedIAMRole):
            if isinstance(resource.role_arn, models.Placeholder):
                return Variable('%s_role_arn' % resource.role_name)
            return resource.role_arn
        # Make mypy happy.
        raise RuntimeError("Unknown resource type: %s" % resource)

    def _get_policy_document(self, resource):
        # type: (models.IAMPolicy) -> Dict[str, Any]
        if isinstance(resource, models.AutoGenIAMPolicy):
            # mypy can't check this, but we assert that the
            # placeholder values are filled in before we invoke
            # any planners, so we can safely cast from
            # Placholder[T] to T.
            document = cast(Dict[str, Any], resource.document)
        elif isinstance(resource, models.FileBasedIAMPolicy):
            document = json.loads(
                self._osutils.get_file_contents(resource.filename))
        return document


class NoopPlanner(PlanStage):
    def __init__(self):
        # type: () -> None
        pass

    def execute(self, resources):
        # type: (List[models.Model]) -> List[models.Instruction]
        return []


class Variable(object):
    def __init__(self, name):
        # type: (str) -> None
        self.name = name
