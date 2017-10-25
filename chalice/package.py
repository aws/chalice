import os
import copy

from typing import Any, Dict  # noqa

from chalice.deploy.swagger import CFNSwaggerGenerator
from chalice.deploy.swagger import SwaggerGenerator  # noqa
from chalice.deploy.packager import LambdaDeploymentPackager
from chalice.deploy.packager import DependencyBuilder
from chalice.deploy.deployer import ApplicationPolicyHandler
from chalice.constants import DEFAULT_LAMBDA_TIMEOUT
from chalice.constants import DEFAULT_LAMBDA_MEMORY_SIZE
from chalice.utils import OSUtils, UI, serialize_to_json, to_cfn_resource_name
from chalice.config import Config  # noqa
from chalice.app import Chalice  # noqa
from chalice.policy import AppPolicyGenerator


def create_app_packager(config):
    # type: (Config) -> AppPackager
    osutils = OSUtils()
    ui = UI()
    # The config object does not handle a default value
    # for autogen'ing a policy so we need to handle this here.
    return AppPackager(
        # We're add place holder values that will be filled in once the
        # lambda function is deployed.
        SAMTemplateGenerator(
            CFNSwaggerGenerator('{region}', {}),
            ApplicationPolicyHandler(
                osutils, AppPolicyGenerator(osutils))),
        LambdaDeploymentPackager(
            osutils=osutils,
            dependency_builder=DependencyBuilder(osutils),
            ui=ui,
        )
    )


class UnsupportedFeatureError(Exception):
    pass


class SAMTemplateGenerator(object):
    _BASE_TEMPLATE = {
        'AWSTemplateFormatVersion': '2010-09-09',
        'Transform': 'AWS::Serverless-2016-10-31',
        'Outputs': {
            'RestAPIId': {
                'Value': {'Ref': 'RestAPI'},
            },
            'APIHandlerName': {
                'Value': {'Ref': 'APIHandler'},
            },
            'APIHandlerArn': {
                'Value': {'Fn::GetAtt': ['APIHandler', 'Arn']}
            },
            'EndpointURL': {
                'Value': {
                    'Fn::Sub': (
                        'https://${RestAPI}.execute-api.${AWS::Region}'
                        # The api_gateway_stage is filled in when
                        # the template is built.
                        '.amazonaws.com/%s/'
                    )
                }
            }
        }
    }  # type: Dict[str, Any]

    def __init__(self, swagger_generator, policy_generator):
        # type: (SwaggerGenerator, ApplicationPolicyHandler) -> None
        self._swagger_generator = swagger_generator
        self._policy_generator = policy_generator

    def generate_sam_template(self, config, code_uri='<placeholder>'):
        # type: (Config, str) -> Dict[str, Any]
        template = copy.deepcopy(self._BASE_TEMPLATE)
        resources = {
            'APIHandler': self._generate_serverless_function(
                config, code_uri, 'app.app', 'api'),
            'RestAPI': self._generate_rest_api(
                config.chalice_app, config.api_gateway_stage),
        }
        self._add_auth_handlers(resources, config, code_uri)
        template['Resources'] = resources
        self._update_endpoint_url_output(template, config)
        return template

    def _add_auth_handlers(self, resources, config, code_uri):
        # type: (Dict[str, Any], Config, str) -> None
        for auth_config in config.chalice_app.builtin_auth_handlers:
            auth_resource_name = to_cfn_resource_name(auth_config.name)
            new_config = config.scope(chalice_stage=config.chalice_stage,
                                      function_name=auth_config.name)
            resources[auth_resource_name] = self._generate_serverless_function(
                new_config, code_uri, auth_config.handler_string, 'authorizer')
            resources[auth_resource_name + 'InvokePermission'] = \
                self._generate_lambda_permission(auth_resource_name)

    def _generate_lambda_permission(self, lambda_ref):
        # type: (str) -> Dict[str, Any]
        return {
            'Type': 'AWS::Lambda::Permission',
            'Properties': {
                'FunctionName': {'Fn::GetAtt': [lambda_ref, 'Arn']},
                'Action': 'lambda:InvokeFunction',
                'Principal': 'apigateway.amazonaws.com'
            }
        }

    def _update_endpoint_url_output(self, template, config):
        # type: (Dict[str, Any], Config) -> None
        url = template['Outputs']['EndpointURL']['Value']['Fn::Sub']
        template['Outputs']['EndpointURL']['Value']['Fn::Sub'] = (
            url % config.api_gateway_stage)

    def _generate_serverless_function(self, config, code_uri, handler_string,
                                      function_type):
        # type: (Config, str, str, str) -> Dict[str, Any]
        properties = {
            'Runtime': config.lambda_python_version,
            'Handler': handler_string,
            'CodeUri': code_uri,
            'Events': self._generate_function_events(
                config.chalice_app, function_type),
            'Tags': config.tags,
            'Timeout': DEFAULT_LAMBDA_TIMEOUT,
            'MemorySize': DEFAULT_LAMBDA_MEMORY_SIZE
        }
        if config.environment_variables:
            properties['Environment'] = {
                'Variables': config.environment_variables
            }
        if config.lambda_timeout is not None:
            properties['Timeout'] = config.lambda_timeout
        if config.lambda_memory_size is not None:
            properties['MemorySize'] = config.lambda_memory_size
        if not config.manage_iam_role:
            properties['Role'] = config.iam_role_arn
        else:
            properties['Policies'] = [self._generate_iam_policy(config)]
        return {
            'Type': 'AWS::Serverless::Function',
            'Properties': properties,
        }

    def _generate_function_events(self, app, function_type):
        # type: (Chalice, str) -> Dict[str, Any]
        return getattr(
            self, '_generate_' + function_type + '_function_events')(app)

    def _generate_api_function_events(self, app):
        # type: (Chalice) -> Dict[str, Any]
        events = {}
        for methods in app.routes.values():
            for http_method, view in methods.items():
                key_name = to_cfn_resource_name(
                    view.view_name + http_method.lower())
                events[key_name] = {
                    'Type': 'Api',
                    'Properties': {
                        'Path': view.uri_pattern,
                        'RestApiId': {'Ref': 'RestAPI'},
                        'Method': http_method.lower(),
                    }
                }
        return events

    def _generate_authorizer_function_events(self, app):
        # type: (Chalice) -> Dict[str, Any]
        return {}

    def _generate_rest_api(self, app, api_gateway_stage):
        # type: (Chalice, str) -> Dict[str, Any]
        swagger_definition = self._swagger_generator.generate_swagger(app)
        properties = {
            'StageName': api_gateway_stage,
            'DefinitionBody': swagger_definition,
        }
        return {
            'Type': 'AWS::Serverless::Api',
            'Properties': properties,
        }

    def _generate_iam_policy(self, config):
        # type: (Config) -> Dict[str, Any]
        return self._policy_generator.generate_policy_from_app_source(config)


class AppPackager(object):
    def __init__(self,
                 sam_templater,       # type: SAMTemplateGenerator
                 lambda_packager,     # type: LambdaDeploymentPackager
                 ):
        # type: (...) -> None
        self._sam_templater = sam_templater
        self._lambda_packaager = lambda_packager

    def _to_json(self, doc):
        # type: (Any) -> str
        return serialize_to_json(doc)

    def package_app(self, config, outdir):
        # type: (Config, str) -> None
        # Deployment package
        zip_file = os.path.join(outdir, 'deployment.zip')
        self._lambda_packaager.create_deployment_package(
            config.project_dir, config.lambda_python_version, zip_file)

        # SAM template
        sam_template = self._sam_templater.generate_sam_template(
            config, './deployment.zip')
        if not os.path.isdir(outdir):
            os.makedirs(outdir)
        with open(os.path.join(outdir, 'sam.json'), 'w') as f:
            f.write(self._to_json(sam_template))
