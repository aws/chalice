import json
import os

from typing import cast
from typing import Dict, List, Tuple, Any, Set, Optional, Text, Union  # noqa
from attr import asdict

from chalice.config import Config  # noqa
from chalice import app
from chalice.constants import LAMBDA_TRUST_POLICY
from chalice.deploy import models
from chalice.utils import UI  # noqa

StrMapAny = Dict[str, Any]


class ChaliceBuildError(Exception):
    pass


class ApplicationGraphBuilder(object):
    def __init__(self):
        # type: () -> None
        self._known_roles = {}  # type: Dict[str, models.IAMRole]
        self._managed_layer = None  # type: Optional[models.LambdaLayer]

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
                config, deployment, stage_name
            )
            resources.append(rest_api)
        if config.chalice_app.websocket_handlers:
            websocket_api = self._create_websocket_api_model(
                config, deployment, stage_name)
            resources.append(websocket_api)
        return models.Application(stage_name, resources)

    def _create_custom_domain_name(
            self,
            api_type,                # type: models.APIType
            domain_name_data,        # type: StrMapAny
            endpoint_configuration,  # type: str
            api_gateway_stage,       # type: str
    ):
        # type: (...) -> models.DomainName
        url_prefix = domain_name_data.get("url_prefix", '(none)')
        api_mapping_model = self._create_api_mapping_model(
            url_prefix, api_gateway_stage)
        domain_name = self._create_domain_name_model(
            api_type,
            domain_name_data,
            endpoint_configuration,
            api_mapping_model
        )
        return domain_name

    def _create_api_mapping_model(self,
                                  key,         # type: str
                                  stage        # type: str
                                  ):
        # type: (...) -> models.APIMapping
        if key == '/':
            key = '(none)'
        return models.APIMapping(
            resource_name='api_mapping',
            mount_path=key,
            api_gateway_stage=stage
        )

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
            elif isinstance(event_source, app.KinesisEventConfig):
                resources.append(
                    self._create_kinesis_subscription(
                        config, deployment, event_source, stage_name,
                    )
                )
            elif isinstance(event_source, app.DynamoDBEventConfig):
                resources.append(
                    self._create_ddb_subscription(
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

        custom_domain_name = None
        if config.api_gateway_custom_domain:
            custom_domain_name = self._create_custom_domain_name(
                models.APIType.HTTP,
                config.api_gateway_custom_domain,
                config.api_gateway_endpoint_type,
                config.api_gateway_stage,
            )

        return models.RestAPI(
            resource_name='rest_api',
            swagger_doc=models.Placeholder.BUILD_STAGE,
            endpoint_type=config.api_gateway_endpoint_type,
            minimum_compression=minimum_compression,
            api_gateway_stage=config.api_gateway_stage,
            lambda_function=lambda_function,
            authorizers=authorizers,
            policy=policy,
            domain_name=custom_domain_name,
            xray=config.xray_enabled,
        )

    def _get_default_private_api_policy(self, config):
        # type: (Config) -> StrMapAny
        statements = [{
            "Effect": "Allow",
            "Principal": "*",
            "Action": "execute-api:Invoke",
            "Resource": "arn:*:execute-api:*:*:*",
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

        custom_domain_name = None
        if config.websocket_api_custom_domain:
            custom_domain_name = self._create_custom_domain_name(
                models.APIType.WEBSOCKET,
                config.websocket_api_custom_domain,
                config.api_gateway_endpoint_type,
                config.api_gateway_stage,
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
            domain_name=custom_domain_name
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

    def _create_domain_name_model(self,
                                  protocol,        # type: models.APIType
                                  data,            # type: StrMapAny
                                  endpoint_type,   # type: str
                                  api_mapping      # type: models.APIMapping
                                  ):
        # type: (...) -> models.DomainName
        default_name = 'api_gateway_custom_domain'
        resource_name_map = {
            'HTTP': default_name,
            'WEBSOCKET': 'websocket_api_custom_domain'
        }  # type: Dict[str, str]

        domain_name = models.DomainName(
            protocol=protocol,
            resource_name=resource_name_map.get(protocol.value, default_name),
            domain_name=data['domain_name'],
            tls_version=models.TLSVersion.create(data.get('tls_version', '')),
            certificate_arn=data['certificate_arn'],
            tags=data.get('tags'),
            api_mapping=api_mapping
        )
        return domain_name

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

    def _get_managed_lambda_layer(self, config):
        # type: (Config) -> Optional[models.LambdaLayer]
        if not config.automatic_layer:
            return None
        if self._managed_layer is None:
            self._managed_layer = models.LambdaLayer(
                resource_name='managed-layer',
                layer_name='%s-%s-%s' % (
                    config.app_name, config.chalice_stage, 'managed-layer'),
                runtime=config.lambda_python_version,
                deployment_package=models.DeploymentPackage(
                    models.Placeholder.BUILD_STAGE)
            )
        return self._managed_layer

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
            layers=lambda_layers,
            managed_layer=self._get_managed_lambda_layer(config),
            xray=config.xray_enabled,
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
        queue = ''  # type: Union[str, models.QueueARN]
        if sqs_config.queue_arn is not None:
            queue = models.QueueARN(arn=sqs_config.queue_arn)
        elif sqs_config.queue is not None:
            queue = sqs_config.queue
        batch_window = sqs_config.maximum_batching_window_in_seconds
        sqs_event_source = models.SQSEventSource(
            resource_name=resource_name,
            queue=queue,
            batch_size=sqs_config.batch_size,
            lambda_function=lambda_function,
            maximum_batching_window_in_seconds=batch_window,
        )
        return sqs_event_source

    def _create_kinesis_subscription(
        self,
        config,          # type: Config
        deployment,      # type: models.DeploymentPackage
        kinesis_config,  # type: app.KinesisEventConfig
        stage_name,      # type: str
    ):
        # type: (...) -> models.KinesisEventSource
        lambda_function = self._create_lambda_model(
            config=config, deployment=deployment, name=kinesis_config.name,
            handler_name=kinesis_config.handler_string, stage_name=stage_name
        )
        resource_name = kinesis_config.name + '-kinesis-event-source'
        batch_window = kinesis_config.maximum_batching_window_in_seconds
        kinesis_event_source = models.KinesisEventSource(
            resource_name=resource_name,
            stream=kinesis_config.stream,
            batch_size=kinesis_config.batch_size,
            maximum_batching_window_in_seconds=batch_window,
            starting_position=kinesis_config.starting_position,
            lambda_function=lambda_function,
        )
        return kinesis_event_source

    def _create_ddb_subscription(
        self,
        config,          # type: Config
        deployment,      # type: models.DeploymentPackage
        ddb_config,      # type: app.DynamoDBEventConfig
        stage_name,      # type: str
    ):
        # type: (...) -> models.DynamoDBEventSource
        lambda_function = self._create_lambda_model(
            config=config, deployment=deployment, name=ddb_config.name,
            handler_name=ddb_config.handler_string, stage_name=stage_name
        )
        resource_name = ddb_config.name + '-dynamodb-event-source'
        batch_window = ddb_config.maximum_batching_window_in_seconds
        ddb_event_source = models.DynamoDBEventSource(
            resource_name=resource_name,
            stream_arn=ddb_config.stream_arn,
            batch_size=ddb_config.batch_size,
            maximum_batching_window_in_seconds=batch_window,
            starting_position=ddb_config.starting_position,
            lambda_function=lambda_function,
        )
        return ddb_event_source


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


class GraphPrettyPrint(object):

    _NEW_SECTION = u'\u251c\u2500\u2500'
    _LINE_VERTICAL = u'\u2502'

    def __init__(self, ui):
        # type: (UI) -> None
        self._ui = ui

    def display_graph(self, graph):
        # type: (models.Model) -> None
        self._ui.write("Application\n")
        for model in graph.dependencies():
            self._traverse(model, level=0)

    def _traverse(self, graph, level):
        # type: (models.Model, int) -> None
        prefix = ('%s   ' % self._LINE_VERTICAL) * level
        spaces = prefix + self._NEW_SECTION + ' '
        model_text = self._get_model_text(graph, spaces, level)
        current_line = cast(str, '%s%s\n' % (spaces, model_text))
        self._ui.write(current_line)
        for model in graph.dependencies():
            self._traverse(model, level + 1)

    def _get_model_text(self, model, spaces, level):
        # type: (models.Model, Text, int) -> Text
        name = model.__class__.__name__
        filtered = self._get_filtered_params(model)
        if not filtered:
            return '%s()' % name
        total_len_prefix = len(spaces) + len(name) + 1
        prefix = ('%s   ' % self._LINE_VERTICAL) * (level + 2)
        full = '%s%s' % (prefix, ' ' * (total_len_prefix - len(prefix)))
        param_items = list(filtered.items())
        first = param_items[0]
        remaining = param_items[1:]
        lines = ['%s(%s=%s,' % (name, first[0], first[1])]
        self._add_remaining_lines(lines, remaining, full)
        return '\n'.join(lines) + ')'

    def _add_remaining_lines(self, lines, remaining, full):
        # type: (List[str], List[Tuple[str, Any]], Text) -> None
        for key, value in remaining:
            if isinstance(value, (list, dict)):
                value = key.upper()
            current = cast(str, '%s%s=%s,' % (full, key, value))
            lines.append(current)

    def _get_filtered_params(self, model):
        # type: (models.Model) -> StrMapAny
        dependencies = model.dependencies()
        filtered = asdict(
            model, filter=lambda _, v: v not in dependencies and v)
        return filtered
