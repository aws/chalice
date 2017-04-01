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
                ApplicationPolicyHandler(osutils))),
        LambdaDeploymentPackager(),
        ApplicationPolicyHandler(osutils),
        config.chalice_app,
        config.project_dir,
        config.autogen_policy)


class PreconfiguredPolicyGenerator(object):
    def __init__(self, config, policy_gen):
        # type: (Config, ApplicationPolicyHandler) -> None
        self._config = config
        self._policy_gen = policy_gen

    def generate_policy_from_app_source(self):
        # type: () -> Dict[str, Any]
        return self._policy_gen.generate_policy_from_app_source(self._config)


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
                        '.amazonaws.com/dev/'
                    )
                }
            }
        }
    }  # type: Dict[str, Any]

    def __init__(self, swagger_generator, policy_generator):
        # type: (SwaggerGenerator, PreconfiguredPolicyGenerator) -> None
        self._swagger_generator = swagger_generator
        self._policy_generator = policy_generator

    def generate_sam_template(self, app, code_uri='<placeholder>',
                              api_gateway_stage='dev'):
        # type: (Chalice, str, str) -> Dict[str, Any]
        template = copy.deepcopy(self._BASE_TEMPLATE)
        resources = {
            'APIHandler': self._generate_serverless_function(app, code_uri),
            'RestAPI': self._generate_rest_api(app, api_gateway_stage),
        }
        template['Resources'] = resources
        return template

    def _generate_serverless_function(self, app, code_uri):
        # type: (Chalice, str) -> Dict[str, Any]
        properties = {
            'Runtime': 'python2.7',
            'Handler': 'app.app',
            'CodeUri': code_uri,
            'Events': self._generate_function_events(app),
            'Policies': [self._generate_iam_policy()],
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
                 policy_gen,          # type: ApplicationPolicyHandler
                 app,                 # type: Chalice
                 project_dir,         # type: str
                 autogen_policy=True  # type: bool
                 ):
        # type: (...) -> None
        self._sam_templater = sam_templater
        self._lambda_packaager = lambda_packager
        self._app = app
        self._policy_gen = policy_gen
        self._project_dir = project_dir
        self._autogen_policy = autogen_policy

    def _to_json(self, doc):
        # type: (Any) -> str
        return json.dumps(doc, indent=2, separators=(',', ': '))

    def package_app(self, outdir):
        # type: (str) -> None
        # Deployment package
        zip_file = os.path.join(outdir, 'deployment.zip')
        self._lambda_packaager.create_deployment_package(
            self._project_dir, zip_file)

        # SAM template
        sam_template = self._sam_templater.generate_sam_template(
            self._app, './deployment.zip')
        if not os.path.isdir(outdir):
            os.makedirs(outdir)
        with open(os.path.join(outdir, 'sam.json'), 'w') as f:
            f.write(self._to_json(sam_template))
