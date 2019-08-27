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
# pylint: disable=too-many-lines
import json
import os
import textwrap
import socket
import logging

import botocore.exceptions
from botocore.vendored.requests import ConnectionError as \
    RequestsConnectionError
from botocore.session import Session  # noqa
from typing import Optional, Dict, List, Any, Set, Tuple, cast  # noqa

from chalice import app
from chalice.config import Config  # noqa
from chalice.config import DeployedResources  # noqa
from chalice.compat import is_broken_pipe_error
from chalice.awsclient import DeploymentPackageTooLargeError
from chalice.awsclient import LambdaClientError
from chalice.awsclient import AWSClientError
from chalice.awsclient import TypedAWSClient
from chalice.constants import MAX_LAMBDA_DEPLOYMENT_SIZE
from chalice.constants import VPC_ATTACH_POLICY
from chalice.constants import DEFAULT_LAMBDA_TIMEOUT
from chalice.constants import DEFAULT_LAMBDA_MEMORY_SIZE
from chalice.constants import LAMBDA_TRUST_POLICY
from chalice.constants import SQS_EVENT_SOURCE_POLICY
from chalice.constants import POST_TO_WEBSOCKET_CONNECTION_POLICY
from chalice.deploy import models
from chalice.deploy.executor import Executor
from chalice.deploy.packager import PipRunner
from chalice.deploy.packager import SubprocessPip
from chalice.deploy.packager import DependencyBuilder as PipDependencyBuilder
from chalice.deploy.packager import LambdaDeploymentPackager
from chalice.deploy.planner import PlanStage
from chalice.deploy.planner import RemoteState
from chalice.deploy.planner import NoopPlanner
from chalice.deploy.swagger import TemplatedSwaggerGenerator
from chalice.deploy.swagger import SwaggerGenerator  # noqa
from chalice.deploy.sweeper import ResourceSweeper
from chalice.deploy.validate import validate_configuration
from chalice.policy import AppPolicyGenerator
from chalice.utils import OSUtils
from chalice.utils import UI
from chalice.utils import serialize_to_json


OptStr = Optional[str]
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
        # type: (Exception) -> OptStr
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
            ),
            LambdaEventSourcePolicyInjector(),
            WebsocketPolicyInjector()
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
        event_resources = self._create_lambda_event_resources(
            config, deployment, stage_name)
        resources.extend(event_resources)
        if config.chalice_app.routes:
            rest_api = self._create_rest_api_model(
                config, deployment, stage_name)
            resources.append(rest_api)
        if config.chalice_app.websocket_handlers:
            websocket_api = self._create_websocket_api_model(
                config, deployment, stage_name)
            resources.append(websocket_api)
        return models.Application(stage_name, resources)

    def _create_lambda_event_resources(self, config, deployment, stage_name):
        # type: (Config, models.DeploymentPackage, str) -> List[models.Model]
        resources = []  # type: List[models.Model]
        for event_source in config.chalice_app.event_sources:
            if isinstance(event_source, app.S3EventConfig):
                resources.append(
                    self._create_bucket_notification(
                        config, deployment, event_source, stage_name
                    )
                )
            elif isinstance(event_source, app.SNSEventConfig):
                resources.append(
                    self._create_sns_subscription(
                        config, deployment, event_source, stage_name,
                    )
                )
            elif isinstance(event_source, app.CloudWatchEventConfig):
                resources.append(
                    self._create_cwe_subscription(
                        config, deployment, event_source, stage_name
                    )
                )
            elif isinstance(event_source, app.ScheduledEventConfig):
                resources.append(
                    self._create_scheduled_model(
                        config, deployment, event_source, stage_name
                    )
                )
            elif isinstance(event_source, app.SQSEventConfig):
                resources.append(
                    self._create_sqs_subscription(
                        config, deployment, event_source, stage_name,
                    )
                )
        return resources

    def _create_rest_api_model(self,
                               config,        # type: Config
                               deployment,    # type: models.DeploymentPackage
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
        if config.minimum_compression_size is None:
            minimum_compression = ''
        else:
            minimum_compression = str(config.minimum_compression_size)
        authorizers = []
        for auth in config.chalice_app.builtin_auth_handlers:
            auth_lambda = self._create_lambda_model(
                config=config, deployment=deployment, name=auth.name,
                handler_name=auth.handler_string, stage_name=stage_name,
            )
            authorizers.append(auth_lambda)

        policy = None
        policy_path = config.api_gateway_policy_file
        if (config.api_gateway_endpoint_type == 'PRIVATE' and not policy_path):
            policy = models.IAMPolicy(
                document=self._get_default_private_api_policy(config))
        elif policy_path:
            policy = models.FileBasedIAMPolicy(
                document=models.Placeholder.BUILD_STAGE,
                filename=os.path.join(
                    config.project_dir, '.chalice', policy_path))

        return models.RestAPI(
            resource_name='rest_api',
            swagger_doc=models.Placeholder.BUILD_STAGE,
            endpoint_type=config.api_gateway_endpoint_type,
            minimum_compression=minimum_compression,
            api_gateway_stage=config.api_gateway_stage,
            lambda_function=lambda_function,
            authorizers=authorizers,
            policy=policy
        )

    def _get_default_private_api_policy(self, config):
        # type: (Config) -> Dict[str, Any]
        statements = [{
            "Effect": "Allow",
            "Principal": "*",
            "Action": "execute-api:Invoke",
            "Resource": "arn:aws:execute-api:*:*:*",
            "Condition": {
                "StringEquals": {
                    "aws:SourceVpce": config.api_gateway_endpoint_vpce
                }
            }
        }]
        return {"Version": "2012-10-17", "Statement": statements}

    def _create_websocket_api_model(
            self,
            config,      # type: Config
            deployment,  # type: models.DeploymentPackage
            stage_name,  # type: str
    ):
        # type: (...) -> models.WebsocketAPI
        connect_handler = None     # type: Optional[models.LambdaFunction]
        message_handler = None     # type: Optional[models.LambdaFunction]
        disconnect_handler = None  # type: Optional[models.LambdaFunction]

        routes = {h.route_key_handled: h.handler_string for h
                  in config.chalice_app.websocket_handlers.values()}
        if '$connect' in routes:
            connect_handler = self._create_lambda_model(
                config=config, deployment=deployment, name='websocket_connect',
                handler_name=routes['$connect'], stage_name=stage_name)
            routes.pop('$connect')
        if '$disconnect' in routes:
            disconnect_handler = self._create_lambda_model(
                config=config, deployment=deployment,
                name='websocket_disconnect',
                handler_name=routes['$disconnect'], stage_name=stage_name)
            routes.pop('$disconnect')
        if routes:
            # If there are left over routes they are message handlers.
            handler_string = list(routes.values())[0]
            message_handler = self._create_lambda_model(
                config=config, deployment=deployment, name='websocket_message',
                handler_name=handler_string, stage_name=stage_name
            )

        return models.WebsocketAPI(
            name='%s-%s-websocket-api' % (config.app_name, stage_name),
            resource_name='websocket_api',
            connect_function=connect_handler,
            message_function=message_handler,
            disconnect_function=disconnect_handler,
            routes=[h.route_key_handled for h
                    in config.chalice_app.websocket_handlers.values()],
            api_gateway_stage=config.api_gateway_stage,
        )

    def _create_cwe_subscription(
            self,
            config,        # type: Config
            deployment,    # type: models.DeploymentPackage
            event_source,  # type: app.CloudWatchEventConfig
            stage_name,    # type: str
    ):
        # type: (...) -> models.CloudWatchEvent
        lambda_function = self._create_lambda_model(
            config=config, deployment=deployment, name=event_source.name,
            handler_name=event_source.handler_string, stage_name=stage_name
        )

        resource_name = event_source.name + '-event'
        rule_name = '%s-%s-%s' % (config.app_name, config.chalice_stage,
                                  resource_name)
        cwe = models.CloudWatchEvent(
            resource_name=resource_name,
            rule_name=rule_name,
            event_pattern=json.dumps(event_source.event_pattern),
            lambda_function=lambda_function,
        )
        return cwe

    def _create_scheduled_model(self,
                                config,        # type: Config
                                deployment,    # type: models.DeploymentPackage
                                event_source,  # type: app.ScheduledEventConfig
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
            rule_description=event_source.description,
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

    def _get_lambda_layers(self, config):
        # type: (Config) -> List[str]
        layers = config.layers
        return layers if layers else []

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
        lambda_layers = self._get_lambda_layers(config)
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
            reserved_concurrency=config.reserved_concurrency,
            layers=lambda_layers
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

    def _create_bucket_notification(
        self,
        config,      # type: Config
        deployment,  # type: models.DeploymentPackage
        s3_event,    # type: app.S3EventConfig
        stage_name,  # type: str
    ):
        # type: (...) -> models.S3BucketNotification
        lambda_function = self._create_lambda_model(
            config=config, deployment=deployment, name=s3_event.name,
            handler_name=s3_event.handler_string, stage_name=stage_name
        )
        resource_name = s3_event.name + '-s3event'
        s3_bucket = models.S3BucketNotification(
            resource_name=resource_name,
            bucket=s3_event.bucket,
            prefix=s3_event.prefix,
            suffix=s3_event.suffix,
            events=s3_event.events,
            lambda_function=lambda_function,
        )
        return s3_bucket

    def _create_sns_subscription(
        self,
        config,      # type: Config
        deployment,  # type: models.DeploymentPackage
        sns_config,  # type: app.SNSEventConfig
        stage_name,  # type: str
    ):
        # type: (...) -> models.SNSLambdaSubscription
        lambda_function = self._create_lambda_model(
            config=config, deployment=deployment, name=sns_config.name,
            handler_name=sns_config.handler_string, stage_name=stage_name
        )
        resource_name = sns_config.name + '-sns-subscription'
        sns_subscription = models.SNSLambdaSubscription(
            resource_name=resource_name,
            topic=sns_config.topic,
            lambda_function=lambda_function,
        )
        return sns_subscription

    def _create_sqs_subscription(
        self,
        config,      # type: Config
        deployment,  # type: models.DeploymentPackage
        sqs_config,  # type: app.SQSEventConfig
        stage_name,  # type: str
    ):
        # type: (...) -> models.SQSEventSource
        lambda_function = self._create_lambda_model(
            config=config, deployment=deployment, name=sqs_config.name,
            handler_name=sqs_config.handler_string, stage_name=stage_name
        )
        resource_name = sqs_config.name + '-sqs-event-source'
        sqs_event_source = models.SQSEventSource(
            resource_name=resource_name,
            queue=sqs_config.queue,
            batch_size=sqs_config.batch_size,
            lambda_function=lambda_function,
        )
        return sqs_event_source


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
                config.project_dir, config.lambda_python_version)
            resource.filename = zip_filename


class SwaggerBuilder(BaseDeployStep):
    def __init__(self, swagger_generator):
        # type: (SwaggerGenerator) -> None
        self._swagger_generator = swagger_generator

    def handle_restapi(self, config, resource):
        # type: (Config, models.RestAPI) -> None
        swagger_doc = self._swagger_generator.generate_swagger(
            config.chalice_app, resource)
        resource.swagger_doc = swagger_doc


class LambdaEventSourcePolicyInjector(BaseDeployStep):
    def __init__(self):
        # type: () -> None
        self._policy_injected = False

    def handle_sqseventsource(self, config, resource):
        # type: (Config, models.SQSEventSource) -> None
        # The sqs integration works by polling for
        # available records so the lambda function needs
        # permission to call sqs.
        role = resource.lambda_function.role
        if (not self._policy_injected and
            isinstance(role, models.ManagedIAMRole) and
            isinstance(role.policy, models.AutoGenIAMPolicy) and
            not isinstance(role.policy.document,
                           models.Placeholder)):
            self._inject_trigger_policy(role.policy.document,
                                        SQS_EVENT_SOURCE_POLICY.copy())
            self._policy_injected = True

    def _inject_trigger_policy(self, document, policy):
        # type: (Dict[str, Any], Dict[str, Any]) -> None
        document['Statement'].append(policy)


class WebsocketPolicyInjector(BaseDeployStep):
    def __init__(self):
        # type: () -> None
        self._policy_injected = False

    def handle_websocketapi(self, config, resource):
        # type: (Config, models.WebsocketAPI) -> None
        self._inject_into_function(config, resource.connect_function)
        self._inject_into_function(config, resource.message_function)
        self._inject_into_function(config, resource.disconnect_function)

    def _inject_into_function(self, config, lambda_function):
        # type: (Config, Optional[models.LambdaFunction]) -> None
        if lambda_function is None:
            return
        role = lambda_function.role
        if role is None:
            return
        if (not self._policy_injected and
            isinstance(role, models.ManagedIAMRole) and
            isinstance(role.policy, models.AutoGenIAMPolicy) and
            not isinstance(role.policy.document,
                           models.Placeholder)):
            self._inject_policy(
                role.policy.document,
                POST_TO_WEBSOCKET_CONNECTION_POLICY.copy())
        self._policy_injected = True

    def _inject_policy(self, document, policy):
        # type: (Dict[str, Any], Dict[str, Any]) -> None
        document['Statement'].append(policy)


class PolicyGenerator(BaseDeployStep):
    def __init__(self, policy_gen, osutils):
        # type: (AppPolicyGenerator, OSUtils) -> None
        self._policy_gen = policy_gen
        self._osutils = osutils

    def _read_document_from_file(self, filename):
        # type: (PolicyGenerator, str) -> Dict[str, Any]
        try:
            return json.loads(self._osutils.get_file_contents(filename))
        except IOError as e:
            raise RuntimeError("Unable to load IAM policy file %s: %s"
                               % (filename, e))

    def handle_filebasediampolicy(self, config, resource):
        # type: (Config, models.FileBasedIAMPolicy) -> None
        resource.document = self._read_document_from_file(resource.filename)

    def handle_restapi(self, config, resource):
        # type: (Config, models.RestAPI) -> None
        if resource.policy and isinstance(
                resource.policy, models.FileBasedIAMPolicy):
            resource.policy.document = self._read_document_from_file(
                resource.policy.filename)

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
    # We want the API URLs to be displayed last.
    _SORT_ORDER = {
        'rest_api': 100,
        'websocket_api': 100,
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
        report.append('  - Rest API URL: %s' % resource['rest_api_url'])

    def _report_websocket_api(self, resource, report):
        # type: (Dict[str, Any], List[str]) -> None
        report.append(
            '  - Websocket API URL: %s' % resource['websocket_api_url'])

    def _report_lambda_function(self, resource, report):
        # type: (Dict[str, Any], List[str]) -> None
        report.append('  - Lambda ARN: %s' % resource['lambda_arn'])

    def _default_report(self, resource, report):
        # type: (Dict[str, Any], List[str]) -> None
        # The default behavior is to not report a resource.  This
        # cuts down on the output verbosity.
        pass

    def display_report(self, deployed_values):
        # type: (Dict[str, Any]) -> None
        report = self.generate_report(deployed_values)
        self._ui.write(report)
