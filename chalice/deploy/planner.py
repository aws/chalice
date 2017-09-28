import json

import attr
from typing import List, Dict, Any, Optional, Union, Tuple, cast  # noqa

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
        if not self.resource_exists(resource):
            return None
        role = self._client.get_role(resource.role_name)
        return attr.evolve(resource,
                           trust_policy=role['AssumeRolePolicyDocument'],
                           role_arn=role['Arn'])


class PlanStage(object):
    def __init__(self, remote_state, osutils):
        # type: (RemoteState, OSUtils) -> None
        self._remote_state = remote_state
        self._osutils = osutils

    def execute(self, resources):
        # type: (List[models.Model]) -> List[models.APICall]
        plan = []  # type: List[models.APICall]
        for resource in resources:
            name = 'plan_%s' % resource.__class__.__name__.lower()
            handler = getattr(self, name, None)
            if handler is not None:
                result = handler(resource)
                if result:
                    plan.extend(result)
        return plan

    def plan_lambdafunction(self, resource):
        # type: (models.LambdaFunction) -> List[models.APICall]
        role_arn = self._get_role_arn(resource.role)
        # Make mypy happy, it complains if we don't "declare" this upfront.
        params = {}  # type: Dict[str, Any]
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
                    target_variable='%s_lambda_arn' % resource.resource_name,
                    params=params,
                    resource=resource,
                )
            ]
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
            )
        ]

    def plan_managediamrole(self, resource):
        # type: (models.ManagedIAMRole) -> List[models.APICall]
        document = self._get_policy_document(resource.policy)
        role_exists = self._remote_state.resource_exists(resource)
        if not role_exists:
            return [
                models.APICall(
                    method_name='create_role',
                    params={'name': resource.role_name,
                            'trust_policy': resource.trust_policy,
                            'policy': document},
                    target_variable='%s_role_arn' % resource.role_name,
                    resource=resource
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


class Variable(object):
    def __init__(self, name):
        # type: (str) -> None
        self.name = name
