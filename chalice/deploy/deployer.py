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

import json
import os
import textwrap
import socket
import logging

import botocore.exceptions
from botocore.vendored.requests import ConnectionError as \
    RequestsConnectionError
from botocore.session import Session  # noqa
import jmespath
from typing import Optional, Dict, List, Any, Set, Tuple, cast  # noqa

from chalice import app
from chalice.config import Config  # noqa
from chalice.compat import is_broken_pipe_error
from chalice.awsclient import DeploymentPackageTooLargeError, TypedAWSClient
from chalice.awsclient import LambdaClientError, AWSClientError
from chalice.constants import MAX_LAMBDA_DEPLOYMENT_SIZE, VPC_ATTACH_POLICY, \
    DEFAULT_LAMBDA_TIMEOUT, DEFAULT_LAMBDA_MEMORY_SIZE, LAMBDA_TRUST_POLICY
from chalice.deploy import models
from chalice.deploy.packager import PipRunner, SubprocessPip, \
    DependencyBuilder as PipDependencyBuilder, LambdaDeploymentPackager
from chalice.deploy.planner import PlanStage, RemoteState, \
    ResourceSweeper, NoopPlanner, Variable, StringFormat
from chalice.deploy.swagger import TemplatedSwaggerGenerator
from chalice.deploy.swagger import SwaggerGenerator  # noqa
from chalice.policy import AppPolicyGenerator
from chalice.utils import OSUtils, UI, serialize_to_json
from chalice.deploy.validate import validate_configuration


OPT_STR = Optional[str]
LOGGER = logging.getLogger(__name__)


_AWSCLIENT_EXCEPTIONS = (
    botocore.exceptions.ClientError, AWSClientError
)


class ChaliceDeploymentError(Exception):
    def __init__(self, error):
        # type: (Exception) -> None
        self.original_error = error
        where = self._get_error_location(error)
        msg = self._wrap_text(
            'ERROR - %s, received the following error:' % where
        )
        msg += '\n\n'
        msg += self._wrap_text(self._get_error_message(error), indent=' ')
        msg += '\n\n'
        suggestion = self._get_error_suggestion(error)
        if suggestion is not None:
            msg += self._wrap_text(suggestion)
        super(ChaliceDeploymentError, self).__init__(msg)

    def _get_error_location(self, error):
        # type: (Exception) -> str
        where = 'While deploying your chalice application'
        if isinstance(error, LambdaClientError):
            where = (
                'While sending your chalice handler code to Lambda to %s '
                'function "%s"' % (
                    self._get_verb_from_client_method(
                        error.context.client_method_name),
                    error.context.function_name
                )
            )
        return where

    def _get_error_message(self, error):
        # type: (Exception) -> str
        msg = str(error)
        if isinstance(error, LambdaClientError):
            if isinstance(error.original_error, RequestsConnectionError):
                msg = self._get_error_message_for_connection_error(
                    error.original_error)
        return msg

    def _get_error_message_for_connection_error(self, connection_error):
        # type: (RequestsConnectionError) -> str

        # To get the underlying error that raised the
        # requests.ConnectionError it is required to go down two levels of
        # arguments to get the underlying exception. The instantiation of
        # one of these exceptions looks like this:
        #
        # requests.ConnectionError(
        #     urllib3.exceptions.ProtocolError(
        #         'Connection aborted.', <SomeException>)
        # )
        message = connection_error.args[0].args[0]
        underlying_error = connection_error.args[0].args[1]

        if is_broken_pipe_error(underlying_error):
            message += (
                ' Lambda closed the connection before chalice finished '
                'sending all of the data.'
            )
        elif isinstance(underlying_error, socket.timeout):
            message += ' Timed out sending your app to Lambda.'
        return message

    def _get_error_suggestion(self, error):
        # type: (Exception) -> OPT_STR
        suggestion = None
        if isinstance(error, DeploymentPackageTooLargeError):
            suggestion = (
                'To avoid this error, decrease the size of your chalice '
                'application by removing code or removing '
                'dependencies from your chalice application.'
            )
            deployment_size = error.context.deployment_size
            if deployment_size > MAX_LAMBDA_DEPLOYMENT_SIZE:
                size_warning = (
                    'This is likely because the deployment package is %s. '
                    'Lambda only allows deployment packages that are %s or '
                    'less in size.' % (
                        self._get_mb(deployment_size),
                        self._get_mb(MAX_LAMBDA_DEPLOYMENT_SIZE)
                    )
                )
                suggestion = size_warning + ' ' + suggestion
        return suggestion

    def _wrap_text(self, text, indent=''):
        # type: (str, str) -> str
        return '\n'.join(
            textwrap.wrap(
                text, 79, replace_whitespace=False, drop_whitespace=False,
                initial_indent=indent, subsequent_indent=indent
            )
        )

    def _get_verb_from_client_method(self, client_method_name):
        # type: (str) -> str
        client_method_name_to_verb = {
            'update_function_code': 'update',
            'create_function': 'create'
        }
        return client_method_name_to_verb.get(
            client_method_name, client_method_name)

    def _get_mb(self, value):
        # type: (int) -> str
        return '%.1f MB' % (float(value) / (1024 ** 2))


class ChaliceBuildError(Exception):
    pass


def create_default_deployer(session, config, ui):
    # type: (Session, Config, UI) -> Deployer
    client = TypedAWSClient(session)
    osutils = OSUtils()
    return Deployer(
        application_builder=ApplicationGraphBuilder(),
        deps_builder=DependencyBuilder(),
        build_stage=create_build_stage(
            osutils, UI(), TemplatedSwaggerGenerator(),
        ),
        plan_stage=PlanStage(
            osutils=osutils, remote_state=RemoteState(
                client, config.deployed_resources(config.chalice_stage)),
        ),
        sweeper=ResourceSweeper(),
        executor=Executor(client, ui),
        recorder=ResultsRecorder(osutils=osutils),
    )


def create_build_stage(osutils, ui, swagger_gen):
    # type: (OSUtils, UI, SwaggerGenerator) -> BuildStage
    pip_runner = PipRunner(pip=SubprocessPip(osutils=osutils),
                           osutils=osutils)
    dependency_builder = PipDependencyBuilder(
        osutils=osutils,
        pip_runner=pip_runner
    )
    build_stage = BuildStage(
        steps=[
            InjectDefaults(),
            DeploymentPackager(
                packager=LambdaDeploymentPackager(
                    osutils=osutils,
                    dependency_builder=dependency_builder,
                    ui=ui,
                ),
            ),
            PolicyGenerator(
                policy_gen=AppPolicyGenerator(
                    osutils=osutils
                ),
                osutils=osutils,
            ),
            SwaggerBuilder(
                swagger_generator=swagger_gen,
            )
        ],
    )
    return build_stage


def create_deletion_deployer(client, ui):
    # type: (TypedAWSClient, UI) -> Deployer
    return Deployer(
        application_builder=ApplicationGraphBuilder(),
        deps_builder=DependencyBuilder(),
        build_stage=BuildStage(steps=[]),
        plan_stage=NoopPlanner(),
        sweeper=ResourceSweeper(),
        executor=Executor(client, ui),
        recorder=ResultsRecorder(osutils=OSUtils()),
    )


class UnresolvedValueError(Exception):
    MSG = (
        "The API parameter '%s' has an unresolved value "
        "of %s in the method call: %s"
    )

    def __init__(self, key, value, method_name):
        # type: (str, models.Placeholder, str) -> None
        super(UnresolvedValueError, self).__init__()
        self.key = key
        self.value = value
        self.method_name = method_name

    def __str__(self):
        # type: () -> str
        return self.MSG % (self.key, self.value, self.method_name)


class Deployer(object):

    BACKEND_NAME = 'api'

    def __init__(self,
                 application_builder,  # type: ApplicationGraphBuilder
                 deps_builder,         # type: DependencyBuilder
                 build_stage,          # type: BuildStage
                 plan_stage,           # type: PlanStage
                 sweeper,              # type: ResourceSweeper
                 executor,             # type: Executor
                 recorder,             # type: ResultsRecorder
                 ):
        # type: (...) -> None
        self._application_builder = application_builder
        self._deps_builder = deps_builder
        self._build_stage = build_stage
        self._plan_stage = plan_stage
        self._sweeper = sweeper
        self._executor = executor
        self._recorder = recorder

    def deploy(self, config, chalice_stage_name):
        # type: (Config, str) -> Dict[str, Any]
        try:
            return self._deploy(config, chalice_stage_name)
        except _AWSCLIENT_EXCEPTIONS as e:
            raise ChaliceDeploymentError(e)

    def _deploy(self, config, chalice_stage_name):
        # type: (Config, str) -> Dict[str, Any]
        self._validate_config(config)
        application = self._application_builder.build(
            config, chalice_stage_name)
        resources = self._deps_builder.build_dependencies(application)
        self._build_stage.execute(config, resources)
        plan = self._plan_stage.execute(resources)
        self._sweeper.execute(plan, config)
        self._executor.execute(plan)
        deployed_values = {
            'resources': self._executor.resource_values,
            'schema_version': '2.0',
            'backend': self.BACKEND_NAME,
        }
        self._recorder.record_results(
            deployed_values,
            chalice_stage_name,
            config.project_dir,
        )
        return deployed_values

    def _validate_config(self, config):
        # type: (Config) -> None
        try:
            validate_configuration(config)
        except ValueError as e:
            raise ChaliceDeploymentError(e)


class ApplicationGraphBuilder(object):
    def __init__(self):
        # type: () -> None
        self._known_roles = {}  # type: Dict[str, models.IAMRole]

    def build(self, config, stage_name):
        # type: (Config, str) -> models.Application
        resources = []  # type: List[models.Model]
        deployment = models.DeploymentPackage(models.Placeholder.BUILD_STAGE)
        for function in config.chalice_app.pure_lambda_functions:
            resource = self._create_lambda_model(
                config=config, deployment=deployment,
                name=function.name, handler_name=function.handler_string,
                stage_name=stage_name)
            resources.append(resource)
        for event_source in config.chalice_app.event_sources:
            scheduled_event = self._create_event_model(
                config, deployment, event_source, stage_name)
            resources.append(scheduled_event)
        if config.chalice_app.routes:
            rest_api = self._create_rest_api_model(
                config, deployment, config.chalice_app, stage_name)
            resources.append(rest_api)
        return models.Application(stage_name, resources)

    def _create_rest_api_model(self,
                               config,        # type: Config
                               deployment,    # type: models.DeploymentPackage
                               chalice_app,   # type: app.Chalice
                               stage_name,    # type: str
                               ):
        # type: (...) -> models.RestAPI
        # Need to mess with the function name for back-compat.
        lambda_function = self._create_lambda_model(
            config=config, deployment=deployment, name='api_handler',
            handler_name='app.app', stage_name=stage_name
        )
        # For backwards compatibility with the old deployer, the
        # lambda function for the API handler doesn't have the
        # resource_name appended to its complete function_name,
        # it's just <app>-<stage>.
        function_name = '%s-%s' % (config.app_name, config.chalice_stage)
        lambda_function.function_name = function_name
        authorizers = []
        for auth in config.chalice_app.builtin_auth_handlers:
            auth_lambda = self._create_lambda_model(
                config=config, deployment=deployment, name=auth.name,
                handler_name=auth.handler_string, stage_name=stage_name,
            )
            authorizers.append(auth_lambda)
        return models.RestAPI(
            resource_name='rest_api',
            swagger_doc=models.Placeholder.BUILD_STAGE,
            api_gateway_stage=config.api_gateway_stage,
            lambda_function=lambda_function,
            authorizers=authorizers,
        )

    def _create_event_model(self,
                            config,        # type: Config
                            deployment,    # type: models.DeploymentPackage
                            event_source,  # type: app.CloudWatchEventSource
                            stage_name,    # type: str
                            ):
        # type: (...) -> models.ScheduledEvent
        lambda_function = self._create_lambda_model(
            config=config, deployment=deployment, name=event_source.name,
            handler_name=event_source.handler_string, stage_name=stage_name
        )
        # Resource names must be unique across a chalice app.
        # However, in the original deployer code, the cloudwatch
        # event + lambda function was considered a single resource.
        # Now that they're treated as two separate resources we need
        # a unique name for the event_source that's not the lambda
        # function resource name.  We handle this by just appending
        # '-event' to the name.  Ideally this is handled in app.py
        # but we won't be able to do that until the old deployer
        # is gone.
        resource_name = event_source.name + '-event'
        if isinstance(event_source.schedule_expression,
                      app.ScheduleExpression):
            expression = event_source.schedule_expression.to_string()
        else:
            expression = event_source.schedule_expression
        rule_name = '%s-%s-%s' % (config.app_name, config.chalice_stage,
                                  resource_name)
        scheduled_event = models.ScheduledEvent(
            resource_name=resource_name,
            rule_name=rule_name,
            schedule_expression=expression,
            lambda_function=lambda_function,
        )
        return scheduled_event

    def _create_lambda_model(self,
                             config,        # type: Config
                             deployment,    # type: models.DeploymentPackage
                             name,          # type: str
                             handler_name,  # type: str
                             stage_name,    # type: str
                             ):
        # type: (...) -> models.LambdaFunction
        new_config = config.scope(
            chalice_stage=config.chalice_stage,
            function_name=name
        )
        role = self._get_role_reference(
            new_config, stage_name, name)
        resource = self._build_lambda_function(
            new_config, name, handler_name,
            deployment, role
        )
        return resource

    def _get_role_reference(self, config, stage_name, function_name):
        # type: (Config, str, str) -> models.IAMRole
        role = self._create_role_reference(config, stage_name, function_name)
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

    def _create_role_reference(self, config, stage_name, function_name):
        # type: (Config, str, str) -> models.IAMRole
        # First option, the user doesn't want us to manage
        # the role at all.
        if not config.manage_iam_role:
            # We've already validated the iam_role_arn is provided
            # if manage_iam_role is set to False.
            return models.PreCreatedIAMRole(
                role_arn=config.iam_role_arn,
            )
        policy = models.IAMPolicy(document=models.Placeholder.BUILD_STAGE)
        if not config.autogen_policy:
            resource_name = '%s_role' % function_name
            role_name = '%s-%s-%s' % (config.app_name, stage_name,
                                      function_name)
            if config.iam_policy_file is not None:
                filename = os.path.join(config.project_dir,
                                        '.chalice',
                                        config.iam_policy_file)
            else:
                filename = os.path.join(config.project_dir,
                                        '.chalice',
                                        'policy-%s.json' % stage_name)
            policy = models.FileBasedIAMPolicy(
                filename=filename, document=models.Placeholder.BUILD_STAGE)
        else:
            resource_name = 'default-role'
            role_name = '%s-%s' % (config.app_name, stage_name)
            policy = models.AutoGenIAMPolicy(
                document=models.Placeholder.BUILD_STAGE,
                traits=set([]),
            )
        return models.ManagedIAMRole(
            resource_name=resource_name,
            role_name=role_name,
            trust_policy=LAMBDA_TRUST_POLICY,
            policy=policy,
        )

    def _get_vpc_params(self, function_name, config):
        # type: (str, Config) -> Tuple[List[str], List[str]]
        security_group_ids = config.security_group_ids
        subnet_ids = config.subnet_ids
        if security_group_ids and subnet_ids:
            return security_group_ids, subnet_ids
        elif not security_group_ids and not subnet_ids:
            return [], []
        else:
            raise ChaliceBuildError(
                "Invalid VPC params for function '%s', in order to configure "
                "VPC for a Lambda function, you must provide the subnet_ids "
                "as well as the security_group_ids, got subnet_ids: %s, "
                "security_group_ids: %s" % (function_name,
                                            subnet_ids,
                                            security_group_ids)
            )

    def _build_lambda_function(self,
                               config,        # type: Config
                               name,          # type: str
                               handler_name,  # type: str
                               deployment,    # type: models.DeploymentPackage
                               role,          # type: models.IAMRole
                               ):
        # type: (...) -> models.LambdaFunction
        function_name = '%s-%s-%s' % (
            config.app_name, config.chalice_stage, name)
        security_group_ids, subnet_ids = self._get_vpc_params(name, config)
        function = models.LambdaFunction(
            resource_name=name,
            function_name=function_name,
            environment_variables=config.environment_variables,
            runtime=config.lambda_python_version,
            handler=handler_name,
            tags=config.tags,
            timeout=config.lambda_timeout,
            memory_size=config.lambda_memory_size,
            deployment_package=deployment,
            role=role,
            security_group_ids=security_group_ids,
            subnet_ids=subnet_ids,
        )
        self._inject_role_traits(function, role)
        return function

    def _inject_role_traits(self, function, role):
        # type: (models.LambdaFunction, models.IAMRole) -> None
        if not isinstance(role, models.ManagedIAMRole):
            return
        policy = role.policy
        if not isinstance(policy, models.AutoGenIAMPolicy):
            return
        if function.security_group_ids and function.subnet_ids:
            policy.traits.add(models.RoleTraits.VPC_NEEDED)


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
        # If recreating this list is a perf issue later on,
        # we can create yet-another set of ids that gets updated
        # when we add a resource to the ordered list.
        if id(resource) not in [id(r) for r in ordered]:
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


class SwaggerBuilder(BaseDeployStep):
    def __init__(self, swagger_generator):
        # type: (SwaggerGenerator) -> None
        self._swagger_generator = swagger_generator

    def handle_restapi(self, config, resource):
        # type: (Config, models.RestAPI) -> None
        swagger_doc = self._swagger_generator.generate_swagger(
            config.chalice_app)
        resource.swagger_doc = swagger_doc


class PolicyGenerator(BaseDeployStep):
    def __init__(self, policy_gen, osutils):
        # type: (AppPolicyGenerator, OSUtils) -> None
        self._policy_gen = policy_gen
        self._osutils = osutils

    def handle_filebasediampolicy(self, config, resource):
        # type: (Config, models.FileBasedIAMPolicy) -> None
        try:
            resource.document = json.loads(
                self._osutils.get_file_contents(resource.filename))
        except IOError as e:
            raise RuntimeError("Unable to load IAM policy file %s: %s"
                               % (resource.filename, e))

    def handle_autogeniampolicy(self, config, resource):
        # type: (Config, models.AutoGenIAMPolicy) -> None
        if isinstance(resource.document, models.Placeholder):
            policy = self._policy_gen.generate_policy(config)
            if models.RoleTraits.VPC_NEEDED in resource.traits:
                policy['Statement'].append(VPC_ATTACH_POLICY)
            resource.document = policy


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
    def __init__(self, client, ui):
        # type: (TypedAWSClient, UI) -> None
        self._client = client
        self._ui = ui
        # A mapping of variables that's populated as API calls
        # are made.  These can be used in subsequent API calls.
        self.variables = {}  # type: Dict[str, Any]
        self.resource_values = []  # type: List[Dict[str, Any]]
        self._resource_value_index = {}  # type: Dict[str, Any]
        self._variable_resolver = VariableResolver()

    def execute(self, plan):
        # type: (models.Plan) -> None
        messages = plan.messages
        for instruction in plan.instructions:
            message = messages.get(id(instruction))
            if message is not None:
                self._ui.write(message)
            getattr(self, '_do_%s' % instruction.__class__.__name__.lower(),
                    self._default_handler)(instruction)

    def _default_handler(self, instruction):
        # type: (models.Instruction) -> None
        raise RuntimeError("Deployment executor encountered an "
                           "unknown instruction: %s"
                           % instruction.__class__.__name__)

    def _do_apicall(self, instruction):
        # type: (models.APICall) -> None
        final_kwargs = self._resolve_variables(instruction)
        method = getattr(self._client, instruction.method_name)
        result = method(**final_kwargs)
        if instruction.output_var is not None:
            self.variables[instruction.output_var] = result

    def _do_copyvariable(self, instruction):
        # type: (models.CopyVariable) -> None
        to_var = instruction.to_var
        from_var = instruction.from_var
        self.variables[to_var] = self.variables[from_var]

    def _do_storevalue(self, instruction):
        # type: (models.StoreValue) -> None
        result = self._variable_resolver.resolve_variables(
            instruction.value, self.variables)
        self.variables[instruction.name] = result

    def _do_recordresourcevariable(self, instruction):
        # type: (models.RecordResourceVariable) -> None
        payload = {
            'name': instruction.resource_name,
            'resource_type': instruction.resource_type,
            instruction.name: self.variables[instruction.variable_name],
        }
        self._add_to_deployed_values(payload)

    def _do_recordresourcevalue(self, instruction):
        # type: (models.RecordResourceValue) -> None
        payload = {
            'name': instruction.resource_name,
            'resource_type': instruction.resource_type,
            instruction.name: instruction.value,
        }
        self._add_to_deployed_values(payload)

    def _add_to_deployed_values(self, payload):
        # type: (Dict[str, str]) -> None
        key = payload['name']
        if key not in self._resource_value_index:
            self._resource_value_index[key] = payload
            self.resource_values.append(payload)
        else:
            # If the key already exists, we merge the new payload
            # with the existing payload.
            self._resource_value_index[key].update(payload)

    def _do_jpsearch(self, instruction):
        # type: (models.JPSearch) -> None
        v = self.variables[instruction.input_var]
        result = jmespath.search(instruction.expression, v)
        self.variables[instruction.output_var] = result

    def _do_builtinfunction(self, instruction):
        # type: (models.BuiltinFunction) -> None
        # Split this out to a separate class of built in functions
        # once we add more functions.
        if instruction.function_name == 'parse_arn':
            resolved_args = self._variable_resolver.resolve_variables(
                instruction.args, self.variables)
            value = resolved_args[0]
            parts = value.split(':')
            result = {
                'service': parts[2],
                'region': parts[3],
                'account_id': parts[4],
            }
            self.variables[instruction.output_var] = result
        else:
            raise ValueError("Unknown builtin function: %s"
                             % instruction.function_name)

    def _resolve_variables(self, api_call):
        # type: (models.APICall) -> Dict[str, Any]
        try:
            return self._variable_resolver.resolve_variables(
                api_call.params, self.variables)
        except UnresolvedValueError as e:
            e.method_name = api_call.method_name
            raise


class VariableResolver(object):
    def resolve_variables(self, value, variables):
        # type: (Any, Dict[str, str]) -> Any
        if isinstance(value, Variable):
            return variables[value.name]
        elif isinstance(value, StringFormat):
            v = {k: variables[k] for k in value.variables}
            return value.template.format(**v)
        elif isinstance(value, models.Placeholder):
            # The key and method_name values are added
            # as the exception propagates up the stack.
            raise UnresolvedValueError('', value, '')
        elif isinstance(value, dict):
            final = {}
            for k, v in value.items():
                try:
                    final[k] = self.resolve_variables(v, variables)
                except UnresolvedValueError as e:
                    e.key = k
                    raise
            return final
        elif isinstance(value, list):
            final_list = []
            for v in value:
                final_list.append(self.resolve_variables(v, variables))
            return final_list
        else:
            return value


class ResultsRecorder(object):
    def __init__(self, osutils):
        # type: (OSUtils) -> None
        self._osutils = osutils

    def record_results(self, results, chalice_stage_name, project_dir):
        # type: (Any, str, str) -> None
        deployed_dir = self._osutils.joinpath(
            project_dir, '.chalice', 'deployed')
        deployed_filename = self._osutils.joinpath(
            deployed_dir, '%s.json' % chalice_stage_name)
        if not self._osutils.directory_exists(deployed_dir):
            self._osutils.makedirs(deployed_dir)
        serialized = serialize_to_json(results)
        self._osutils.set_file_contents(
            filename=deployed_filename,
            contents=serialized,
            binary=False
        )


class DeploymentReporter(object):
    # We want the Rest API to be displayed last.
    _SORT_ORDER = {
        'rest_api': 100,
    }
    # The default is chosen to sort before the rest_api
    _DEFAULT_ORDERING = 50

    def __init__(self, ui):
        # type: (UI) -> None
        self._ui = ui

    def generate_report(self, deployed_values):
        # type: (Dict[str, Any]) -> str
        report = [
            'Resources deployed:',
        ]
        ordered = sorted(
            deployed_values['resources'],
            key=lambda x: self._SORT_ORDER.get(x['resource_type'],
                                               self._DEFAULT_ORDERING))
        for resource in ordered:
            getattr(self, '_report_%s' % resource['resource_type'],
                    self._default_report)(resource, report)
        report.append('')
        return '\n'.join(report)

    def _report_rest_api(self, resource, report):
        # type: (Dict[str, Any], List[str]) -> None
        report.append(
            '  - Rest API URL: %s' % resource['rest_api_url']
        )

    def _report_lambda_function(self, resource, report):
        # type: (Dict[str, Any], List[str]) -> None
        report.append(
            '  - Lambda ARN: %s' % resource['lambda_arn']
        )

    def _default_report(self, resource, report):
        # type: (Dict[str, Any], List[str]) -> None
        # The default behavior is to not report a resource.  This
        # cuts down on the output verbosity.
        pass

    def display_report(self, deployed_values):
        # type: (Dict[str, Any]) -> None
        report = self.generate_report(deployed_values)
        self._ui.write(report)
