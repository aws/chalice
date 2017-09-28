"""Chalice deployer module.

The deployment system in chalice is broken down into a pipeline of multiple
stages.  Each stage takes the input and transforms it to some other form.  The
reason for this is so that each stage can stay simple and focused on only a
single part of the deployment process.  This makes the code easier to follow
and easier to test.  The biggest downside is that adding support for a new
resource type is split across several objects now, but I imagine as we add
support for more resource types, we'll see common patterns emerge that we can
extract out into higher levels of abstraction.

These are the stages of the deployment process.

Application Graph Builder
=========================

The first stage is the resource graph builder.  This takes the objects in the
``Chalice`` app and structures them into an ``Application`` object which
consists of various ``models.Model`` objects.  These models are just python
objects that describe the attributes of various AWS resources.  These
models don't have any behavior on their own.

Dependency Builder
==================

This process takes the graph of resources created from the previous step and
orders them such that all objects are listed before objects that depend on
them.  The AWS resources in the ``chalice.deploy.models`` module also model
their required dependencies (see the ``dependencies()`` methods of the models).
This is the mechanism that's used to build the correct dependency ordering.

Local Build Stage
=================

This takes the ordered list of resources and allows any local build processes
to occur.  The rule of thumb here is no remote AWS calls.  This stage includes
auto policy generation, pip packaging, injecting default values, etc.  To
clarify which attributes are affected by the build stage, they'll usually have
a value of ``models.Placeholder.BUILD_STAGE``.  Processors in the build stage
will replaced those ``models.Placeholder.BUILD_STAGE`` values with whatever the
"built" value is (e.g the filename of the zipped deployment package).

For example, we know when we create a lambda function that we need to create a
deployment package, but we don't know the name nor contents of the deployment
package until the ``LambdaDeploymentPackager`` runs.  Therefore, the Resource
Builder stage can record the fact that it knows that a
``models.DeploymentPackage`` is needed, but use
``models.Placeholder.BUILD_STAGE`` for the value of the filename.  The enum
values aren't strictly necessary, they just add clarity about when this value
is expected to be filled in.  These could also just be set to ``None`` and be
of type ``Optional[T]``.


Execution Plan Stage
====================

This stage takes the ordered list of resources and figures out what AWS API
calls we have to make.  For example, if a resource doesn't exist at all, we'll
need to make a ``create_*`` call.  If the resource exists, we may need to make
a series of ``update_*`` calls.  If the resource exists and is already up to
date, we might not need to make any calls at all.  The output of this stage is
a list of ``APICall`` objects.  This stage doesn't actually make the mutating
API calls, it only figures out what calls we should make.  This stage will
typically only make ``describe/list`` AWS calls.


The Executor
============

This takes the list of ``APICall`` objects from the previous stage and finally
executes them.  It also manages taking the output of API calls and storing them
in variables so they can be referenced in subsequent ``APICall`` objects (see
the ``Variable`` class to see how this is used).  For example, if a lambda
function needs the ``role_arn`` that's the result of a previous ``create_role``
API call, a ``Variable`` object is used to forward this information.

The executor also records these variables with their associated resources so a
``deployed.json`` file can be written to disk afterwards.  An ``APICall``
takes an optional resource object when it's created whose ``resource_name``
is used as the key in the ``deployed.json`` dictionary.


"""
import os

from typing import List, Set, Dict, Any, Optional, Union, cast  # noqa
from botocore.session import Session  # noqa

from chalice.utils import OSUtils, UI
from chalice.deploy import models
from chalice.config import Config  # noqa
from chalice import app  # noqa
from chalice.deploy.packager import LambdaDeploymentPackager
from chalice.deploy.packager import PipRunner, SubprocessPip
from chalice.deploy.packager import DependencyBuilder as PipDependencyBuilder
from chalice.deploy.planner import PlanStage, Variable, RemoteState
from chalice.policy import AppPolicyGenerator
from chalice.constants import LAMBDA_TRUST_POLICY
from chalice.constants import DEFAULT_LAMBDA_TIMEOUT
from chalice.constants import DEFAULT_LAMBDA_MEMORY_SIZE
from chalice.awsclient import TypedAWSClient


def create_default_deployer(session):
    # type: (Session) -> Deployer
    client = TypedAWSClient(session)
    osutils = OSUtils()
    pip_runner = PipRunner(pip=SubprocessPip(osutils=osutils),
                           osutils=osutils)
    dependency_builder = PipDependencyBuilder(
        osutils=osutils,
        pip_runner=pip_runner
    )
    return Deployer(
        application_builder=ApplicationGraphBuilder(),
        deps_builder=DependencyBuilder(),
        build_stage=BuildStage(
            steps=[
                InjectDefaults(),
                DeploymentPackager(
                    packager=LambdaDeploymentPackager(
                        osutils=osutils,
                        dependency_builder=dependency_builder,
                        ui=UI(),
                    ),
                ),
                PolicyGenerator(
                    policy_gen=AppPolicyGenerator(
                        osutils=osutils
                    ),
                ),
            ],
        ),
        plan_stage=PlanStage(
            osutils=osutils, remote_state=RemoteState(client),
        ),
        executor=Executor(client),
    )


class UnresolvedValueError(Exception):
    MSG = (
        "The API parameter '%s' has an unresolved value "
        "of %s in the method call: %s"
    )

    def __init__(self, key, value, method_name):
        # type: (str, models.Placeholder, str) -> None
        msg = self.MSG % (key, value, method_name)
        super(UnresolvedValueError, self).__init__(msg)
        self.key = key
        self.value = value
        self.method_name = method_name


class Deployer(object):
    def __init__(self,
                 application_builder,  # type: ApplicationGraphBuilder
                 deps_builder,         # type: DependencyBuilder
                 build_stage,          # type: BuildStage
                 plan_stage,           # type: PlanStage
                 executor,             # type: Executor
                 ):
        # type: (...) -> None
        self._application_builder = application_builder
        self._deps_builder = deps_builder
        self._build_stage = build_stage
        self._plan_stage = plan_stage
        self._executor = executor

    def deploy(self, config, chalice_stage_name):
        # type: (Config, str) -> Dict[str, Any]
        application = self._application_builder.build(
            config, chalice_stage_name)
        resources = self._deps_builder.build_dependencies(application)
        self._build_stage.execute(config, resources)
        plan = self._plan_stage.execute(resources)
        self._executor.execute(plan)
        return {'resources': self._executor.resources}


class ApplicationGraphBuilder(object):
    def __init__(self):
        # type: () -> None
        self._known_roles = {}  # type: Dict[str, models.IAMRole]

    def build(self, config, stage_name):
        # type: (Config, str) -> models.Application
        resources = []  # type: List[models.Model]
        deployment = models.DeploymentPackage(models.Placeholder.BUILD_STAGE)
        for function in config.chalice_app.pure_lambda_functions:
            new_config = config.scope(chalice_stage=config.chalice_stage,
                                      function_name=function.name)
            role = self._get_role_reference(new_config, stage_name, function)
            resource = self._build_lambda_function(
                new_config, function, deployment, role)
            resources.append(resource)
        return models.Application(stage_name, resources)

    def _get_role_reference(self, config, stage_name, function):
        # type: (Config, str, app.LambdaFunction) -> models.IAMRole
        role = self._create_role_reference(config, stage_name, function)
        role_identifier = self._get_role_identifier(role)
        if role_identifier in self._known_roles:
            # If we've already create a models.IAMRole with the same
            # identifier, we'll use the existing object instead of
            # creating a new one.
            return self._known_roles[role_identifier]
        self._known_roles[role_identifier] = role
        return role

    def _get_role_identifier(self, role):
        # type: (models.IAMRole) -> str
        if isinstance(role, models.PreCreatedIAMRole):
            return role.role_arn
        # We know that if it's not a PreCreatedIAMRole, it's
        # a managed role, so we're using cast() to make mypy happy.
        role = cast(models.ManagedIAMRole, role)
        return role.resource_name

    def _create_role_reference(self, config, stage_name, function):
        # type: (Config, str, app.LambdaFunction) -> models.IAMRole
        # First option, the user doesn't want us to manage
        # the role at all.
        if not config.manage_iam_role:
            # We've already validated the iam_role_arn is provided
            # if manage_iam_role is set to False.
            return models.PreCreatedIAMRole(
                role_arn=config.iam_role_arn,
            )
        policy = models.IAMPolicy()
        if not config.autogen_policy:
            resource_name = 'role-%s' % function.name
            role_name = '%s-%s-%s' % (config.app_name, stage_name,
                                      function.name)
            if config.iam_policy_file is not None:
                filename = os.path.join(config.project_dir,
                                        '.chalice',
                                        config.iam_policy_file)
            else:
                filename = os.path.join(config.project_dir,
                                        '.chalice',
                                        'policy-%s.json' % stage_name)
            policy = models.FileBasedIAMPolicy(filename=filename)
        else:
            resource_name = 'default-role'
            role_name = '%s-%s' % (config.app_name, stage_name)
            policy = models.AutoGenIAMPolicy(
                document=models.Placeholder.BUILD_STAGE)
        return models.ManagedIAMRole(
            resource_name=resource_name,
            role_arn=models.Placeholder.DEPLOY_STAGE,
            role_name=role_name,
            trust_policy=LAMBDA_TRUST_POLICY,
            policy=policy,
        )

    def _build_lambda_function(self,
                               config,      # type: Config
                               function,    # type: app.LambdaFunction
                               deployment,  # type: models.DeploymentPackage
                               role,        # type: models.IAMRole
                               ):
        # type: (...) -> models.LambdaFunction
        function_name = '%s-%s-%s' % (
            config.app_name, config.chalice_stage, function.name)
        return models.LambdaFunction(
            resource_name=function.name,
            function_name=function_name,
            environment_variables=config.environment_variables,
            runtime=config.lambda_python_version,
            handler=function.handler_string,
            tags=config.tags,
            timeout=config.lambda_timeout,
            memory_size=config.lambda_memory_size,
            deployment_package=deployment,
            role=role,
        )


class DependencyBuilder(object):
    def __init__(self):
        # type: () -> None
        pass

    def build_dependencies(self, graph):
        # type: (models.Model) -> List[models.Model]
        seen = set()  # type: Set[int]
        ordered = []  # type: List[models.Model]
        for resource in graph.dependencies():
            self._traverse(resource, ordered, seen)
        return ordered

    def _traverse(self, resource, ordered, seen):
        # type: (models.Model, List[models.Model], Set[int]) -> None
        for dep in resource.dependencies():
            if id(dep) not in seen:
                seen.add(id(dep))
                self._traverse(dep, ordered, seen)
        ordered.append(resource)


class BaseDeployStep(object):

    def handle(self, config, resource):
        # type: (Config, models.Model) -> None
        name = 'handle_%s' % resource.__class__.__name__.lower()
        handler = getattr(self, name, None)
        if handler is not None:
            handler(config, resource)


class InjectDefaults(BaseDeployStep):
    def __init__(self, lambda_timeout=DEFAULT_LAMBDA_TIMEOUT,
                 lambda_memory_size=DEFAULT_LAMBDA_MEMORY_SIZE):
        # type: (int, int) -> None
        self._lambda_timeout = lambda_timeout
        self._lambda_memory_size = lambda_memory_size

    def handle_lambdafunction(self, config, resource):
        # type: (Config, models.LambdaFunction) -> None
        if resource.timeout is None:
            resource.timeout = self._lambda_timeout
        if resource.memory_size is None:
            resource.memory_size = self._lambda_memory_size


class DeploymentPackager(BaseDeployStep):
    def __init__(self, packager):
        # type: (LambdaDeploymentPackager) -> None
        self._packager = packager

    def handle_deploymentpackage(self, config, resource):
        # type: (Config, models.DeploymentPackage) -> None
        if isinstance(resource.filename, models.Placeholder):
            zip_filename = self._packager.create_deployment_package(
                config.project_dir, config.lambda_python_version
            )
            resource.filename = zip_filename


class PolicyGenerator(BaseDeployStep):
    def __init__(self, policy_gen):
        # type: (AppPolicyGenerator) -> None
        self._policy_gen = policy_gen

    def handle_autogeniampolicy(self, config, resource):
        # type: (Config, models.AutoGenIAMPolicy) -> None
        if isinstance(resource.document, models.Placeholder):
            resource.document = self._policy_gen.generate_policy(config)


class BuildStage(object):
    def __init__(self, steps):
        # type: (List[BaseDeployStep]) -> None
        self._steps = steps

    def execute(self, config, resources):
        # type: (Config, List[models.Model]) -> None
        for resource in resources:
            for step in self._steps:
                step.handle(config, resource)


class Executor(object):
    def __init__(self, client):
        # type: (TypedAWSClient) -> None
        self._client = client
        # A mapping of variables that's populated as API calls
        # are made.  These can be used in subsequent API calls.
        self.variables = {}  # type: Dict[str, Any]
        self.resources = {}  # type: Dict[str, Dict[str, Any]]

    def execute(self, api_calls):
        # type: (List[models.APICall]) -> None
        for api_call in api_calls:
            final_kwargs = self._resolve_variables(api_call)
            method = getattr(self._client, api_call.method_name)
            # TODO: we need proper error handling here.
            result = method(**final_kwargs)
            if api_call.target_variable is not None:
                varname = api_call.target_variable
                self.variables[varname] = result
                if api_call.resource is not None:
                    name = api_call.resource.resource_name
                    mapping = self.resources.setdefault(
                        name,
                        {'resource_type': api_call.resource.resource_type}
                    )
                    mapping[varname] = result

    def _resolve_variables(self, api_call):
        # type: (models.APICall) -> Dict[str, Any]
        final = {}
        for key, value in api_call.params.items():
            if isinstance(value, Variable):
                final[key] = self.variables[value.name]
            elif isinstance(value, models.Placeholder):
                raise UnresolvedValueError(key, value, api_call.method_name)
            else:
                final[key] = value
        return final
