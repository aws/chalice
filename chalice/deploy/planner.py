import json

from typing import List, Dict, Any, Optional, Union, cast  # noqa

from chalice.utils import OSUtils  # noqa
from chalice.deploy import models
from chalice.awsclient import ResourceDoesNotExistError
from chalice.awsclient import TypedAWSClient  # noqa


class PlanStage(object):
    def __init__(self, client, osutils):
        # type: (TypedAWSClient, OSUtils) -> None
        self._client = client
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
        role_arn = ''  # type: Optional[Union[str, Variable]]
        if isinstance(resource.role, models.PreCreatedIAMRole):
            role_arn = resource.role.role_arn
        elif isinstance(resource.role, models.ManagedIAMRole):
            role_arn = self._get_role_arn(resource.role)
            if role_arn is not None:
                resource.role.role_arn = role_arn
            if isinstance(resource.role.role_arn, models.Placeholder):
                role_arn = Variable('%s_role_arn' % resource.role.role_name)
        if self._client.lambda_function_exists(resource.function_name):
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
        return [models.APICall(
            method_name='create_function',
            params={'function_name': resource.function_name,
                    'role_arn': role_arn,
                    'zip_contents': self._osutils.get_file_contents(
                        resource.deployment_package.filename, binary=True),
                    'runtime': resource.runtime,
                    'handler': resource.handler,
                    'environment_variables': resource.environment_variables,
                    'tags': resource.tags,
                    'timeout': resource.timeout,
                    'memory_size': resource.memory_size},
            target_variable='%s_lambda_arn' % resource.resource_name,
            resource=resource,
        )]

    def plan_managediamrole(self, resource):
        # type: (models.ManagedIAMRole) -> List[models.APICall]
        document = self._get_policy_document(resource.policy)
        role_arn = self._get_role_arn(resource)
        if role_arn is not None:
            resource.role_arn = role_arn
        if isinstance(resource.role_arn, models.Placeholder):
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
        return [
            models.APICall(
                method_name='delete_role_policy',
                params={'role_name': resource.role_name,
                        'policy_name': resource.role_name},
                resource=resource
            ),
            models.APICall(
                method_name='put_role_policy',
                params={'role_name': resource.role_name,
                        'policy_name': resource.role_name,
                        'policy_document': document},
                resource=resource
            )
        ]

    def _get_role_arn(self, resource):
        # type: (models.ManagedIAMRole) -> Optional[str]
        try:
            return self._client.get_role_arn_for_name(resource.role_name)
        except ResourceDoesNotExistError:
            return None

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
