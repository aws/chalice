import os
import copy
import json
import hashlib
import re

from typing import Any, Dict  # noqa

from chalice.deploy.swagger import CFNSwaggerGenerator
from chalice.deploy.swagger import SwaggerGenerator  # noqa
from chalice.deploy.packager import LambdaDeploymentPackager
from chalice.deploy.packager import DependencyBuilder
from chalice.deploy.deployer import ApplicationPolicyHandler
from chalice.constants import DEFAULT_LAMBDA_TIMEOUT
from chalice.constants import DEFAULT_LAMBDA_MEMORY_SIZE
from chalice.utils import OSUtils, UI
from chalice.config import Config  # noqa
from chalice.app import Chalice, Rate  # noqa
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
            PreconfiguredPolicyGenerator(
                config,
                ApplicationPolicyHandler(
                    osutils, AppPolicyGenerator(osutils)))),
        LambdaDeploymentPackager(
            osutils=osutils,
            dependency_builder=DependencyBuilder(osutils),
            ui=ui,
        )
    )


class UnsupportedFeatureError(Exception):
    pass


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
        self._check_for_unsupported_features(config)
        template = copy.deepcopy(self._BASE_TEMPLATE)
        chalice_app = config.chalice_app
        resources = {
            'APIHandler': self._generate_serverless_function(config, code_uri),
            'RestAPI': self._generate_rest_api(
                chalice_app, config.api_gateway_stage),
        }

        # Generate resources for pure_lambda functions
        self._generate_additional_functions(code_uri,
                                            config,
                                            chalice_app.pure_lambda_functions,
                                            resources,
                                            'pure_lambda')

        # Generate resources for schedule events functions
        self._generate_additional_functions(code_uri,
                                            config,
                                            chalice_app.event_sources,
                                            resources,
                                            'event')

        template['Resources'] = resources
        self._update_endpoint_url_output(template, config)
        return template

    def _generate_additional_functions(self, code_uri, config,
                                       funcs, resources, event_type):
        for func in funcs:
            gen_func = self._generate_serverless_function(
                config=config,
                code_uri=code_uri,
                handler=func.handler_string,
                event_type=event_type)

            # CFN doesn't allow special characters.
            # If function name has '_', remove it
            resource_key = re.sub(r'[^A-Za-z0-9]+', '', func.name)
            resources[resource_key] = gen_func

    def _check_for_unsupported_features(self, config):
        # type: (Config) -> None
        if config.chalice_app.builtin_auth_handlers:
            # It doesn't look like SAM templates support everything
            # we need to fully support built in authorizers.
            # See: awslabs/serverless-application-model#49
            # and: https://forums.aws.amazon.com/thread.jspa?messageID=787920
            #
            # We might need to switch to low level cfn to fix this.
            raise UnsupportedFeatureError(
                "SAM templates do not currently support these "
                "built-in auth handlers: %s" % ', '.join(
                    [c.name for c in
                     config.chalice_app.builtin_auth_handlers]))

    def _update_endpoint_url_output(self, template, config):
        # type: (Dict[str, Any], Config) -> None
        url = template['Outputs']['EndpointURL']['Value']['Fn::Sub']
        template['Outputs']['EndpointURL']['Value']['Fn::Sub'] = (
            url % config.api_gateway_stage)

    def _generate_serverless_function(self, config,
                                      code_uri,
                                      handler='app.app',
                                      event_type='api'):

        # type: (Config, str) -> Dict[str, Any]
        properties = {
            'Runtime': config.lambda_python_version,
            'Handler': handler,
            'CodeUri': code_uri,
            'Tags': config.tags,
            'Timeout': DEFAULT_LAMBDA_TIMEOUT,
            'MemorySize': DEFAULT_LAMBDA_MEMORY_SIZE
        }

        func_events = self._generate_function_events(config.chalice_app,
                                                     event_type=event_type)

        # For pure_lambda functions there will be no events
        if func_events:
            properties['Events'] = func_events

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
            properties['Policies'] = [self._generate_iam_policy()]
        return {
            'Type': 'AWS::Serverless::Function',
            'Properties': properties,
        }

    def _generate_function_events(self, app, event_type='api'):
        # type: (Chalice) -> Dict[str, Any]
        events = {}

        if event_type == 'pure_lambda':
            return events

        if event_type == 'api':
            for methods in app.routes.values():
                for http_method, view in methods.items():
                    mod_vname = re.sub(r'[^A-Za-z0-9]+', '', view.view_name)
                    key_name = ''.join([
                        mod_vname, http_method.lower(),
                        hashlib.md5(
                            view.view_name.encode('utf-8')).hexdigest()[:4],
                    ])
                    events[key_name] = {
                        'Type': 'Api',
                        'Properties': {
                            'Path': view.uri_pattern,
                            'RestApiId': {'Ref': 'RestAPI'},
                            'Method': http_method.lower(),
                        }
                    }
        else:
            for es in app.event_sources:
                key_name = 'schduleEvent%s' % es.name
                # Remove underscores and other special characters
                mod_key_name = re.sub(r'[^A-Za-z0-9]+', '', key_name)
                events[mod_key_name] = {
                    'Type': 'Schedule',
                    'Properties': {
                        'Schedule': self._convert_schedule_expression(
                            es.schedule_expression)
                    }
                }

        return events

    def _convert_schedule_expression(self, schedule_expression):
        if isinstance(schedule_expression, Rate):
            return schedule_expression.to_string()

        return schedule_expression

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
            config.project_dir, config.lambda_python_version, zip_file)

        # SAM template
        sam_template = self._sam_templater.generate_sam_template(
            config, './deployment.zip')
        if not os.path.isdir(outdir):
            os.makedirs(outdir)
        with open(os.path.join(outdir, 'sam.json'), 'w') as f:
            f.write(self._to_json(sam_template))
