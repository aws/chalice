import os
import copy
import json

from typing import Any, Optional, Dict, List, Set, Union  # noqa
from typing import cast

from chalice.deploy.swagger import CFNSwaggerGenerator
from chalice.utils import OSUtils, UI, serialize_to_json, to_cfn_resource_name
from chalice.config import Config  # noqa
from chalice.deploy import models
from chalice.deploy.deployer import ApplicationGraphBuilder
from chalice.deploy.deployer import DependencyBuilder
from chalice.deploy.deployer import BuildStage  # noqa
from chalice.deploy.deployer import create_build_stage


def create_app_packager(config, merge_template=None):
    # type: (Config, Optional[str]) -> AppPackager
    osutils = OSUtils()
    ui = UI()
    application_builder = ApplicationGraphBuilder()
    deps_builder = DependencyBuilder()
    build_stage = create_build_stage(
        osutils, ui, CFNSwaggerGenerator()
    )
    resource_builder = ResourceBuilder(application_builder,
                                       deps_builder, build_stage)
    processors = [
        ReplaceCodeLocationPostProcessor(osutils=osutils),
        TemplateMergePostProcessor(
            osutils=osutils,
            merger=TemplateDeepMerger(),
            merge_template=merge_template,
        ),
    ]
    return AppPackager(
        SAMTemplateGenerator(),
        resource_builder,
        CompositePostProcessor(processors),
        osutils,
    )


class UnsupportedFeatureError(Exception):
    pass


class DuplicateResourceNameError(Exception):
    pass


class ResourceBuilder(object):
    def __init__(self,
                 application_builder,  # type: ApplicationGraphBuilder
                 deps_builder,         # type: DependencyBuilder
                 build_stage,          # type: BuildStage
                 ):
        # type: (...) -> None
        self._application_builder = application_builder
        self._deps_builder = deps_builder
        self._build_stage = build_stage

    def construct_resources(self, config, chalice_stage_name):
        # type: (Config, str) -> List[models.Model]
        application = self._application_builder.build(
            config, chalice_stage_name)
        resources = self._deps_builder.build_dependencies(application)
        self._build_stage.execute(config, resources)
        return resources


class SAMTemplateGenerator(object):
    _BASE_TEMPLATE = {
        'AWSTemplateFormatVersion': '2010-09-09',
        'Transform': 'AWS::Serverless-2016-10-31',
        'Outputs': {},
        'Resources': {},
    }

    def __init__(self):
        # type: () -> None
        self._seen_names = set([])  # type: Set[str]

    def generate_sam_template(self, resources):
        # type: (List[models.Model]) -> Dict[str, Any]
        template = copy.deepcopy(self._BASE_TEMPLATE)
        self._seen_names.clear()
        for resource in resources:
            name = '_generate_%s' % resource.__class__.__name__.lower()
            handler = getattr(self, name, self._default)
            handler(resource, template)
        return template

    def _generate_scheduledevent(self, resource, template):
        # type: (models.ScheduledEvent, Dict[str, Any]) -> None
        function_cfn_name = to_cfn_resource_name(
            resource.lambda_function.resource_name)
        function_cfn = template['Resources'][function_cfn_name]
        event_cfn_name = self._register_cfn_resource_name(
            resource.resource_name)
        function_cfn['Properties']['Events'] = {
            event_cfn_name: {
                'Type': 'Schedule',
                'Properties': {
                    'Schedule': resource.schedule_expression,
                }
            }
        }

    def _generate_lambdafunction(self, resource, template):
        # type: (models.LambdaFunction, Dict[str, Any]) -> None
        resources = template['Resources']
        cfn_name = self._register_cfn_resource_name(resource.resource_name)
        lambdafunction_definition = {
            'Type': 'AWS::Serverless::Function',
            'Properties': {
                'Runtime': resource.runtime,
                'Handler': resource.handler,
                'CodeUri': resource.deployment_package.filename,
                'Tags': resource.tags,
                'Timeout': resource.timeout,
                'MemorySize': resource.memory_size,
            },
        }  # type: Dict[str, Any]

        if resource.environment_variables:
            environment_config = {
                'Environment': {
                    'Variables': resource.environment_variables
                }
            }  # type: Dict[str, Dict[str, Dict[str, str]]]
            lambdafunction_definition['Properties'].update(environment_config)
        if resource.security_group_ids and resource.subnet_ids:
            vpc_config = {
                'VpcConfig': {
                    'SecurityGroupIds': resource.security_group_ids,
                    'SubnetIds': resource.subnet_ids,
                }
            }  # type: Dict[str, Dict[str, List[str]]]
            lambdafunction_definition['Properties'].update(vpc_config)
        if resource.reserved_concurrency is not None:
            reserved_concurrency_config = {
                'ReservedConcurrentExecutions': resource.reserved_concurrency
            }
            lambdafunction_definition['Properties'].update(
                reserved_concurrency_config)
        if resource.layers:
            layers_config = {
                'Layers': resource.layers
            }  # type: Dict[str, List[str]]
            lambdafunction_definition['Properties'].update(layers_config)

        resources[cfn_name] = lambdafunction_definition
        self._add_iam_role(resource, resources[cfn_name])

    def _add_iam_role(self, resource, cfn_resource):
        # type: (models.LambdaFunction, Dict[str, Any]) -> None
        role = resource.role
        if isinstance(role, models.ManagedIAMRole):
            cfn_resource['Properties']['Role'] = {
                'Fn::GetAtt': [
                    to_cfn_resource_name(role.resource_name), 'Arn'
                ],
            }
        else:
            # resource is a PreCreatedIAMRole.  This is the only other
            # subclass of IAMRole.
            role = cast(models.PreCreatedIAMRole, role)
            cfn_resource['Properties']['Role'] = role.role_arn

    def _generate_restapi(self, resource, template):
        # type: (models.RestAPI, Dict[str, Any]) -> None
        resources = template['Resources']
        resources['RestAPI'] = {
            'Type': 'AWS::Serverless::Api',
            'Properties': {
                'EndpointConfiguration': resource.endpoint_type,
                'StageName': resource.api_gateway_stage,
                'DefinitionBody': resource.swagger_doc,
            }
        }
        if resource.minimum_compression:
            properties = resources['RestAPI']['Properties']
            properties['MinimumCompressionSize'] = \
                int(resource.minimum_compression)

        handler_cfn_name = to_cfn_resource_name(
            resource.lambda_function.resource_name)
        api_handler = template['Resources'].pop(handler_cfn_name)
        template['Resources']['APIHandler'] = api_handler
        resources['APIHandlerInvokePermission'] = {
            'Type': 'AWS::Lambda::Permission',
            'Properties': {
                'FunctionName': {'Ref': 'APIHandler'},
                'Action': 'lambda:InvokeFunction',
                'Principal': 'apigateway.amazonaws.com',
                'SourceArn': {
                    'Fn::Sub': [
                        ('arn:aws:execute-api:${AWS::Region}:${AWS::AccountId}'
                         ':${RestAPIId}/*'),
                        {'RestAPIId': {'Ref': 'RestAPI'}},
                    ]
                },
            }
        }
        for auth in resource.authorizers:
            auth_cfn_name = to_cfn_resource_name(auth.resource_name)
            resources[auth_cfn_name + 'InvokePermission'] = {
                'Type': 'AWS::Lambda::Permission',
                'Properties': {
                    'FunctionName': {'Fn::GetAtt': [auth_cfn_name, 'Arn']},
                    'Action': 'lambda:InvokeFunction',
                    'Principal': 'apigateway.amazonaws.com',
                    'SourceArn': {
                        'Fn::Sub': [
                            ('arn:aws:execute-api:${AWS::Region}:'
                             '${AWS::AccountId}:${RestAPIId}/*'),
                            {'RestAPIId': {'Ref': 'RestAPI'}},
                        ]
                    },
                }
            }
        self._inject_restapi_outputs(template)

    def _inject_restapi_outputs(self, template):
        # type: (Dict[str, Any]) -> None
        # The 'Outputs' of the SAM template are considered
        # part of the public API of chalice and therefore
        # need to maintain backwards compatibility.  This
        # method uses the same output key names as the old
        # deployer.
        # For now, we aren't adding any of the new resources
        # to the Outputs section until we can figure out
        # a consist naming scheme.  Ideally we don't use
        # the autogen'd names that contain the md5 suffixes.
        stage_name = template['Resources']['RestAPI'][
            'Properties']['StageName']
        outputs = template['Outputs']
        outputs['RestAPIId'] = {
            'Value': {'Ref': 'RestAPI'}
        }
        outputs['APIHandlerName'] = {
            'Value': {'Ref': 'APIHandler'}
        }
        outputs['APIHandlerArn'] = {
            'Value': {'Fn::GetAtt': ['APIHandler', 'Arn']}
        }
        outputs['EndpointURL'] = {
            'Value': {
                'Fn::Sub': (
                    'https://${RestAPI}.execute-api.${AWS::Region}'
                    # The api_gateway_stage is filled in when
                    # the template is built.
                    '.amazonaws.com/%s/'
                ) % stage_name
            }
        }

    def _add_websocket_lambda_integration(
            self, api_ref, websocket_handler, resources):
        # type: (Dict[str, Any], str, Dict[str, Any]) -> None
        resources['%sAPIIntegration' % websocket_handler] = {
            'Type': 'AWS::ApiGatewayV2::Integration',
            'Properties': {
                'ApiId': api_ref,
                'ConnectionType': 'INTERNET',
                'ContentHandlingStrategy': 'CONVERT_TO_TEXT',
                'IntegrationType': 'AWS_PROXY',
                'IntegrationUri': {
                    'Fn::Sub': [
                        (
                            'arn:aws:apigateway:${AWS::Region}:lambda:path/'
                            '2015-03-31/functions/arn:aws:lambda:'
                            '${AWS::Region}:' '${AWS::AccountId}:function:'
                            '${WebsocketHandler}/invocations'
                        ),
                        {'WebsocketHandler': {'Ref': websocket_handler}}
                    ],
                }
            }
        }

    def _add_websocket_lambda_invoke_permission(
            self, api_ref, websocket_handler, resources):
        # type: (Dict[str, str], str, Dict[str, Any]) -> None
        resources['%sInvokePermission' % websocket_handler] = {
            'Type': 'AWS::Lambda::Permission',
            'Properties': {
                'FunctionName': {'Ref': websocket_handler},
                'Action': 'lambda:InvokeFunction',
                'Principal': 'apigateway.amazonaws.com',
                'SourceArn': {
                    'Fn::Sub': [
                        ('arn:aws:execute-api:${AWS::Region}:${AWS::AccountId}'
                         ':${WebsocketAPIId}/*'),
                        {'WebsocketAPIId': api_ref},
                    ]
                },
            }
        }

    def _add_websocket_lambda_integrations(self, api_ref, resources):
        # type: (Dict[str, str], Dict[str, Any]) -> None
        websocket_handlers = [
            'WebsocketConnect',
            'WebsocketMessage',
            'WebsocketDisconnect',
        ]
        for handler in websocket_handlers:
            if handler in resources:
                self._add_websocket_lambda_integration(
                    api_ref, handler, resources)
                self._add_websocket_lambda_invoke_permission(
                    api_ref, handler, resources)

    def _create_route_for_key(self, route_key, api_ref):
        # type: (str, Dict[str, str]) -> Dict[str, Any]
        integration_ref = {
            '$connect': 'WebsocketConnectAPIIntegration',
            '$disconnect': 'WebsocketDisconnectAPIIntegration',
        }.get(route_key, 'WebsocketMessageAPIIntegration')

        return {
            'Type': 'AWS::ApiGatewayV2::Route',
            'Properties': {
                'ApiId': api_ref,
                'RouteKey': route_key,
                'Target': {
                    'Fn::Join': [
                        '/',
                        [
                            'integrations',
                            {'Ref': integration_ref},
                        ]
                    ]
                },
            },
        }

    def _generate_websocketapi(self, resource, template):
        # type: (models.WebsocketAPI, Dict[str, Any]) -> None
        resources = template['Resources']
        api_ref = {'Ref': 'WebsocketAPI'}
        resources['WebsocketAPI'] = {
            'Type': 'AWS::ApiGatewayV2::Api',
            'Properties': {
                'Name': resource.name,
                'RouteSelectionExpression': '$request.body.action',
                'ProtocolType': 'WEBSOCKET',
            }
        }

        self._add_websocket_lambda_integrations(api_ref, resources)

        route_key_names = []
        for route in resource.routes:
            key_name = 'Websocket%sRoute' % route.replace(
                '$', '').replace('default', 'message').capitalize()
            route_key_names.append(key_name)
            resources[key_name] = self._create_route_for_key(route, api_ref)

        resources['WebsocketAPIDeployment'] = {
            'Type': 'AWS::ApiGatewayV2::Deployment',
            'DependsOn': route_key_names,
            'Properties': {
                'ApiId': api_ref,
            }
        }

        resources['WebsocketAPIStage'] = {
            'Type': 'AWS::ApiGatewayV2::Stage',
            'Properties': {
                'ApiId': api_ref,
                'DeploymentId': {'Ref': 'WebsocketAPIDeployment'},
                'StageName': resource.api_gateway_stage,
            }
        }

        self._inject_websocketapi_outputs(template)

    def _inject_websocketapi_outputs(self, template):
        # type: (Dict[str, Any]) -> None
        # The 'Outputs' of the SAM template are considered
        # part of the public API of chalice and therefore
        # need to maintain backwards compatibility.  This
        # method uses the same output key names as the old
        # deployer.
        # For now, we aren't adding any of the new resources
        # to the Outputs section until we can figure out
        # a consist naming scheme.  Ideally we don't use
        # the autogen'd names that contain the md5 suffixes.
        stage_name = template['Resources']['WebsocketAPIStage'][
            'Properties']['StageName']
        outputs = template['Outputs']
        resources = template['Resources']
        outputs['WebsocketAPIId'] = {
            'Value': {'Ref': 'WebsocketAPI'}
        }
        if 'WebsocketConnect' in resources:
            outputs['WebsocketConnectHandlerArn'] = {
                'Value': {'Fn::GetAtt': ['WebsocketConnect', 'Arn']}
            }
            outputs['WebsocketConnectHandlerName'] = {
                'Value': {'Ref': 'WebsocketConnect'}
            }
        if 'WebsocketMessage' in resources:
            outputs['WebsocketMessageHandlerArn'] = {
                'Value': {'Fn::GetAtt': ['WebsocketMessage', 'Arn']}
            }
            outputs['WebsocketMessageHandlerName'] = {
                'Value': {'Ref': 'WebsocketMessage'}
            }
        if 'WebsocketDisconnect' in resources:
            outputs['WebsocketDisconnectHandlerArn'] = {
                'Value': {'Fn::GetAtt': ['WebsocketDisconnect', 'Arn']}
            }  # There is not a lot of green in here.
            outputs['WebsocketDisconnectHandlerName'] = {
                'Value': {'Ref': 'WebsocketDisconnect'}
            }
        outputs['WebsocketConnectEndpointURL'] = {
            'Value': {
                'Fn::Sub': (
                    'wss://${WebsocketAPI}.execute-api.${AWS::Region}'
                    # The api_gateway_stage is filled in when
                    # the template is built.
                    '.amazonaws.com/%s/'
                ) % stage_name
            }
        }

    # The various IAM roles/policies are handled in the
    # Lambda function generation.  We're creating these
    # noop methods to indicate we've accounted for these
    # resources.

    def _generate_managediamrole(self, resource, template):
        # type: (models.ManagedIAMRole, Dict[str, Any]) -> None
        role_cfn_name = self._register_cfn_resource_name(
            resource.resource_name)
        template['Resources'][role_cfn_name] = {
            'Type': 'AWS::IAM::Role',
            'Properties': {
                'AssumeRolePolicyDocument': resource.trust_policy,
                'Policies': [
                    {'PolicyDocument': resource.policy.document,
                     'PolicyName': role_cfn_name + 'Policy'},
                ],
            }
        }

    def _generate_filebasediampolicy(self, resource, template):
        # type: (models.FileBasedIAMPolicy, Dict[str, Any]) -> None
        pass

    def _generate_autogeniampolicy(self, resource, template):
        # type: (models.AutoGenIAMPolicy, Dict[str, Any]) -> None
        pass

    def _generate_deploymentpackage(self, resource, template):
        # type: (models.DeploymentPackage, Dict[str, Any]) -> None
        pass

    def _generate_precreatediamrole(self, resource, template):
        # type: (models.PreCreatedIAMRole, Dict[str, Any]) -> None
        pass

    def _generate_s3bucketnotification(self, resource, template):
        # type: (models.S3BucketNotification, Dict[str, Any]) -> None
        message = (
            "Unable to package chalice apps that @app.on_s3_event decorator. "
            "CloudFormation does not support modifying the event "
            "notifications of existing buckets. "
            "You can deploy this app using `chalice deploy`."
        )
        raise NotImplementedError(message)

    def _generate_snslambdasubscription(self, resource, template):
        # type: (models.SNSLambdaSubscription, Dict[str, Any]) -> None
        function_cfn_name = to_cfn_resource_name(
            resource.lambda_function.resource_name)
        function_cfn = template['Resources'][function_cfn_name]
        sns_cfn_name = self._register_cfn_resource_name(
            resource.resource_name)

        if resource.topic.startswith('arn:aws:sns:'):
            topic_arn = resource.topic  # type: Union[str, Dict[str, str]]
        else:
            topic_arn = {
                'Fn::Sub': (
                    'arn:aws:sns:${AWS::Region}:${AWS::AccountId}:%s' %
                    resource.topic
                )
            }
        function_cfn['Properties']['Events'] = {
            sns_cfn_name: {
                'Type': 'SNS',
                'Properties': {
                    'Topic': topic_arn,
                }
            }
        }

    def _generate_sqseventsource(self, resource, template):
        # type: (models.SQSEventSource, Dict[str, Any]) -> None
        function_cfn_name = to_cfn_resource_name(
            resource.lambda_function.resource_name)
        function_cfn = template['Resources'][function_cfn_name]
        sns_cfn_name = self._register_cfn_resource_name(
            resource.resource_name)
        function_cfn['Properties']['Events'] = {
            sns_cfn_name: {
                'Type': 'SQS',
                'Properties': {
                    'Queue': {
                        'Fn::Sub': (
                            'arn:aws:sqs:${AWS::Region}:${AWS::AccountId}:%s' %
                            resource.queue
                        )
                    },
                    'BatchSize': resource.batch_size,
                }
            }
        }

    def _default(self, resource, template):
        # type: (models.Model, Dict[str, Any]) -> None
        raise NotImplementedError(resource)

    def _register_cfn_resource_name(self, name):
        # type: (str) -> str
        cfn_name = to_cfn_resource_name(name)
        if cfn_name in self._seen_names:
            raise DuplicateResourceNameError(
                'A duplicate resource name was generated for '
                'the SAM template: %s' % cfn_name,
            )
        self._seen_names.add(cfn_name)
        return cfn_name


class AppPackager(object):
    def __init__(self,
                 sam_templater,     # type: SAMTemplateGenerator
                 resource_builder,  # type: ResourceBuilder
                 post_processor,    # type: TemplatePostProcessor
                 osutils,           # type: OSUtils
                 ):
        # type: (...) -> None
        self._sam_templater = sam_templater
        self._resource_builder = resource_builder
        self._template_post_processor = post_processor
        self._osutils = osutils

    def _to_json(self, doc):
        # type: (Any) -> str
        return serialize_to_json(doc)

    def package_app(self, config, outdir, chalice_stage_name):
        # type: (Config, str, str) -> None
        # Deployment package
        resources = self._resource_builder.construct_resources(
            config, chalice_stage_name)

        # SAM template
        sam_template = self._sam_templater.generate_sam_template(
            resources)
        if not self._osutils.directory_exists(outdir):
            self._osutils.makedirs(outdir)
        self._template_post_processor.process(
            sam_template, config, outdir, chalice_stage_name)
        self._osutils.set_file_contents(
            filename=os.path.join(outdir, 'sam.json'),
            contents=self._to_json(sam_template),
            binary=False
        )


class TemplatePostProcessor(object):
    def __init__(self, osutils):
        # type: (OSUtils) -> None
        self._osutils = osutils

    def process(self, template, config, outdir, chalice_stage_name):
        # type: (Dict[str, Any], Config, str, str) -> None
        raise NotImplementedError('process')


class ReplaceCodeLocationPostProcessor(TemplatePostProcessor):
    def process(self, template, config, outdir, chalice_stage_name):
        # type: (Dict[str, Any], Config, str, str) -> None
        self._fixup_deployment_package(template, outdir)

    def _fixup_deployment_package(self, template, outdir):
        # type: (Dict[str, Any], str) -> None
        # NOTE: This isn't my ideal way to do this.  I'd like
        # to move this into the build step where something
        # copies the DeploymentPackage.filename over to the
        # outdir.  That would require plumbing through user
        # provided params such as "outdir" into the build stage
        # somehow, which isn't currently possible.
        copied = False
        for resource in template['Resources'].values():
            if resource['Type'] != 'AWS::Serverless::Function':
                continue
            original_location = resource['Properties']['CodeUri']
            new_location = os.path.join(outdir, 'deployment.zip')
            if not copied:
                self._osutils.copy(original_location, new_location)
                copied = True
            resource['Properties']['CodeUri'] = './deployment.zip'


class TemplateMergePostProcessor(TemplatePostProcessor):
    def __init__(self, osutils, merger, merge_template=None):
        # type: (OSUtils, TemplateMerger, Optional[str]) -> None
        super(TemplateMergePostProcessor, self).__init__(osutils)
        self._merger = merger
        self._merge_template = merge_template

    def process(self, template, config, outdir, chalice_stage_name):
        # type: (Dict[str, Any], Config, str, str) -> None
        if self._merge_template is None:
            return
        loaded_template = self._load_template_to_merge()
        merged = self._merger.merge(loaded_template, template)
        template.clear()
        template.update(merged)

    def _load_template_to_merge(self):
        # type: () -> Dict[str, Any]
        template_name = cast(str, self._merge_template)
        filepath = os.path.abspath(template_name)
        if not self._osutils.file_exists(filepath):
            raise RuntimeError('Cannot find template file: %s' % filepath)
        template_data = self._osutils.get_file_contents(filepath, binary=False)
        try:
            loaded_template = json.loads(template_data)
        except ValueError:
            raise RuntimeError(
                'Expected %s to be valid JSON template.' % filepath)
        return loaded_template


class CompositePostProcessor(TemplatePostProcessor):
    def __init__(self, processors):
        # type: (List[TemplatePostProcessor]) -> None
        self._processors = processors

    def process(self, template, config, outdir, chalice_stage_name):
        # type: (Dict[str, Any], Config, str, str) -> None
        for processor in self._processors:
            processor.process(template, config, outdir, chalice_stage_name)


class TemplateMerger(object):
    def merge(self, file_template, chalice_template):
        # type: (Dict[str, Any], Dict[str, Any]) -> Dict[str, Any]
        raise NotImplementedError('merge')


class TemplateDeepMerger(TemplateMerger):
    def merge(self, file_template, chalice_template):
        # type: (Dict[str, Any], Dict[str, Any]) -> Dict[str, Any]
        return self._merge(file_template, chalice_template)

    def _merge(self, file_template, chalice_template):
        # type: (Any, Any) -> Any
        if isinstance(file_template, dict) and \
           isinstance(chalice_template, dict):
            return self._merge_dict(file_template, chalice_template)
        return file_template

    def _merge_dict(self, file_template, chalice_template):
        # type: (Dict[str, Any], Dict[str, Any]) -> Dict[str, Any]
        merged = chalice_template.copy()
        for key, value in file_template.items():
            merged[key] = self._merge(value, chalice_template.get(key))
        return merged
