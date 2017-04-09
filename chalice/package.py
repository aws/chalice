import os
import copy
import json
import hashlib

from typing import Any, Dict  # noqa

from chalice.deploy.swagger import CFNSwaggerGenerator
from chalice.deploy.swagger import SwaggerGenerator  # noqa
from chalice.deploy.packager import LambdaDeploymentPackager
from chalice.deploy.deployer import ApplicationPolicyHandler
from chalice.utils import OSUtils
from chalice.config import Config  # noqa
from chalice.app import Chalice  # noqa
from chalice.policy import AppPolicyGenerator


def create_app_packager(config):
    # type: (Config) -> AppPackager
    osutils = OSUtils()
    # The config object does not handle a default value
    # for autogen'ing a policy so we need to handle this here.
    return AppPackager(
        # We're add place holder values that will be filled in once the
        # lambda function is deployed.
        SAMTemplateGenerator(
            CFNSwaggerGenerator('{region}', '{lambda_arn}'),
            PreconfiguredPolicyGenerator(
                config,
                ApplicationPolicyHandler(
                    osutils, AppPolicyGenerator(osutils)))),
        LambdaDeploymentPackager()
    )


class PreconfiguredPolicyGenerator(object):
    def __init__(self, config, policy_gen):
        # type: (Config, ApplicationPolicyHandler) -> None
        self._config = config
        self._policy_gen = policy_gen

    def generate_policy_from_app_source(self):
        # type: () -> Dict[str, Any]
        return self._policy_gen.generate_policy_from_app_source(
            self._config)


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
        # type: (SwaggerGenerator, PreconfiguredPolicyGenerator) -> None
        self._swagger_generator = swagger_generator
        self._policy_generator = policy_generator

    def generate_sam_template(self, config, code_uri='<placeholder>'):
        # type: (Config, str) -> Dict[str, Any]
        template = copy.deepcopy(self._BASE_TEMPLATE)
        resources = {
            'APIHandler': self._generate_serverless_function(config, code_uri),
            'RestAPI': self._generate_rest_api(
                config.chalice_app, config.api_gateway_stage),
        }
        template['Resources'] = resources
        self._update_endpoint_url_output(template, config)
        return template

    def _update_endpoint_url_output(self, template, config):
        # type: (Dict[str, Any], Config) -> None
        url = template['Outputs']['EndpointURL']['Value']['Fn::Sub']
        template['Outputs']['EndpointURL']['Value']['Fn::Sub'] = (
            url % config.api_gateway_stage)

    def _generate_serverless_function(self, config, code_uri):
        # type: (Config, str) -> Dict[str, Any]
        properties = {
            'Runtime': 'python2.7',
            'Handler': 'app.app',
            'CodeUri': code_uri,
            'Events': self._generate_function_events(config.chalice_app),
            'Policies': [self._generate_iam_policy()],
        }
        if config.environment_variables:
            properties['Environment'] = {
                'Variables': config.environment_variables
            }
        return {
            'Type': 'AWS::Serverless::Function',
            'Properties': properties,
        }

    def _generate_function_events(self, app):
        # type: (Chalice) -> Dict[str, Any]
        events = {}
        for path, view in app.routes.items():
            for http_method in view.methods:
                key_name = ''.join([
                    view.view_name, http_method.lower(),
                    hashlib.md5(view.view_name).hexdigest()[:4],
                ])
                events[key_name] = {
                    'Type': 'Api',
                    'Properties': {
                        'Path': view.uri_pattern,
                        'RestApiId': {'Ref': 'RestAPI'},
                        'Method': http_method.lower(),
                    }
                }
        return events

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

    def _generate_iam_policy(self):
        # type: () -> Dict[str, Any]
        return self._policy_generator.generate_policy_from_app_source()


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
        return json.dumps(doc, indent=2, separators=(',', ': '))

    def package_app(self, config, outdir):
        # type: (Config, str) -> None
        # Deployment package
        zip_file = os.path.join(outdir, 'deployment.zip')
        self._lambda_packaager.create_deployment_package(
            config.project_dir, zip_file)

        # SAM template
        sam_template = self._sam_templater.generate_sam_template(
            config, './deployment.zip')
        if not os.path.isdir(outdir):
            os.makedirs(outdir)
        with open(os.path.join(outdir, 'sam.json'), 'w') as f:
            f.write(self._to_json(sam_template))
