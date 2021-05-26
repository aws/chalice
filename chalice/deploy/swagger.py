import copy
import inspect

from typing import Any, List, Dict, Optional, Union  # noqa

from chalice.app import Chalice, RouteEntry, Authorizer, CORSConfig  # noqa
from chalice.app import ChaliceAuthorizer
from chalice.deploy.planner import StringFormat
from chalice.deploy.models import RestAPI  # noqa
from chalice.utils import to_cfn_resource_name


class SwaggerGenerator(object):

    _BASE_TEMPLATE = {
        'swagger': '2.0',
        'info': {
            'version': '1.0',
            'title': ''
        },
        'schemes': ['https'],
        'paths': {},
        'definitions': {
            'Empty': {
                'type': 'object',
                'title': 'Empty Schema',
            }
        }
    }  # type: Dict[str, Any]

    def __init__(self, region, deployed_resources):
        # type: (str, Dict[str, Any]) -> None
        self._region = region
        self._deployed_resources = deployed_resources

    def generate_swagger(self, app, rest_api=None):
        # type: (Chalice, Optional[RestAPI]) -> Dict[str, Any]
        api = copy.deepcopy(self._BASE_TEMPLATE)
        api['info']['title'] = app.app_name
        self._add_binary_types(api, app)
        self._add_route_paths(api, app)
        self._add_resource_policy(api, rest_api)
        self._add_vpc_endpoint(api, rest_api)
        return api

    def _add_resource_policy(self, api, rest_api):
        # type: (Dict[str, Any], Optional[RestAPI]) -> None
        if rest_api and rest_api.policy:
            api['x-amazon-apigateway-policy'] = rest_api.policy.document

    def _add_vpc_endpoint(self, api, rest_api):
        # type: (Dict[str, Any], Optional[RestAPI]) -> None
        if rest_api and rest_api.vpce_ids:
            api['x-amazon-apigateway-endpoint-configuration'] = {
                "vpcEndpointIds": rest_api.vpce_ids
            }

    def _add_binary_types(self, api, app):
        # type: (Dict[str, Any], Chalice) -> None
        api['x-amazon-apigateway-binary-media-types'] = app.api.binary_types

    def _add_route_paths(self, api, app):
        # type: (Dict[str, Any], Chalice) -> None
        for path, methods in app.routes.items():
            swagger_for_path = {}  # type: Dict[str, Any]
            api['paths'][path] = swagger_for_path

            cors_config = None
            methods_with_cors = []
            for http_method, view in methods.items():
                current = self._generate_route_method(view)
                if 'security' in current:
                    self._add_to_security_definition(
                        current['security'], api, view)
                swagger_for_path[http_method.lower()] = current
                if view.cors is not None:
                    cors_config = view.cors
                    methods_with_cors.append(http_method)

            # Chalice ensures that routes with multiple views have the same
            # CORS configuration. So if any entry has CORS enabled, use that
            # entry's CORS configuration for the preflight setup.
            if cors_config is not None:
                self._add_preflight_request(
                    cors_config, methods_with_cors, swagger_for_path)

    def _generate_security_from_auth_obj(self, api_config, authorizer):
        # type: (Dict[str, Any], Authorizer) -> None
        if isinstance(authorizer, ChaliceAuthorizer):
            auth_config = authorizer.config
            config = {
                'in': 'header',
                'type': 'apiKey',
                'name': auth_config.header,
                'x-amazon-apigateway-authtype': 'custom'
            }
            api_gateway_authorizer = {
                'type': 'token',
                'authorizerUri': self._auth_uri(authorizer)
            }
            if auth_config.execution_role is not None:
                api_gateway_authorizer['authorizerCredentials'] = \
                    auth_config.execution_role
            if auth_config.ttl_seconds is not None:
                api_gateway_authorizer['authorizerResultTtlInSeconds'] = \
                    auth_config.ttl_seconds
            config['x-amazon-apigateway-authorizer'] = api_gateway_authorizer
        else:
            config = authorizer.to_swagger()
        api_config.setdefault(
            'securityDefinitions', {})[authorizer.name] = config

    def _auth_uri(self, authorizer):
        # type: (ChaliceAuthorizer) -> str
        function_name = '%s-%s' % (
            self._deployed_resources['api_handler_name'],
            authorizer.config.name
        )
        return self._uri(
            self._deployed_resources['lambda_functions'][function_name]['arn'])

    def _add_to_security_definition(self, security,
                                    api_config, view):
        # type: (Any, Dict[str, Any], RouteEntry) -> None
        if view.authorizer is not None:
            self._generate_security_from_auth_obj(api_config, view.authorizer)
        for auth in security:
            name = list(auth.keys())[0]
            if name == 'api_key':
                # This is just the api_key_required=True config
                swagger_snippet = {
                    'type': 'apiKey',
                    'name': 'x-api-key',
                    'in': 'header',
                }  # type: Dict[str, Any]
                api_config.setdefault(
                    'securityDefinitions', {})[name] = swagger_snippet

    def _generate_route_method(self, view):
        # type: (RouteEntry) -> Dict[str, Any]
        current = {
            'consumes': view.content_types,
            'produces': ['application/json'],
            'responses': self._generate_precanned_responses(),
            'x-amazon-apigateway-integration': self._generate_apig_integ(
                view),
        }  # type: Dict[str, Any]
        docstring = inspect.getdoc(view.view_function)
        if docstring:
            doc_lines = docstring.splitlines()
            current['summary'] = doc_lines[0]
            if len(doc_lines) > 1:
                current['description'] = '\n'.join(doc_lines[1:]).strip('\n')
        if view.api_key_required:
            # When this happens we also have to add the relevant portions
            # to the security definitions.  We have to someone indicate
            # this because this neeeds to be added to the global config
            # file.
            current.setdefault('security', []).append({'api_key': []})
        if view.authorizer:
            current.setdefault('security', []).append(
                {view.authorizer.name: view.authorizer.scopes})
        if view.view_args:
            self._add_view_args(current, view.view_args)
        return current

    def _generate_precanned_responses(self):
        # type: () -> Dict[str, Any]
        responses = {
            '200': {
                'description': '200 response',
                'schema': {
                    '$ref': '#/definitions/Empty',
                }
            }
        }
        return responses

    def _uri(self, lambda_arn=None):
        # type: (Optional[str]) -> Any
        if lambda_arn is None:
            lambda_arn = self._deployed_resources['api_handler_arn']
        partition = lambda_arn.split(':')[1]
        return ('arn:{partition}:apigateway:{region}:lambda:path/2015-03-31'
                '/functions/{lambda_arn}/invocations').format(
                    partition=partition, region=self._region,
                    lambda_arn=lambda_arn)

    def _generate_apig_integ(self, view):
        # type: (RouteEntry) -> Dict[str, Any]
        apig_integ = {
            'responses': {
                'default': {
                    'statusCode': "200",
                }
            },
            'uri': self._uri(),
            'passthroughBehavior': 'when_no_match',
            'httpMethod': 'POST',
            'contentHandling': 'CONVERT_TO_TEXT',
            'type': 'aws_proxy',
        }
        return apig_integ

    def _add_view_args(self, single_method, view_args):
        # type: (Dict[str, Any], List[str]) -> None
        single_method['parameters'] = [
            {'name': name, 'in': 'path', 'required': True, 'type': 'string'}
            for name in view_args
        ]

    def _add_preflight_request(self, cors, methods, swagger_for_path):
        # type: (CORSConfig, List[str], Dict[str, Any]) -> None
        methods = methods + ['OPTIONS']
        allowed_methods = ','.join(methods)

        response_params = {
            'Access-Control-Allow-Methods': '%s' % allowed_methods
        }
        response_params.update(cors.get_access_control_headers())

        headers = {k: {'type': 'string'} for k, _ in response_params.items()}
        response_params = {'method.response.header.%s' % k: "'%s'" % v for k, v
                           in response_params.items()}

        options_request = {
            "consumes": ["application/json"],
            "produces": ["application/json"],
            "responses": {
                "200": {
                    "description": "200 response",
                    "schema": {"$ref": "#/definitions/Empty"},
                    "headers": headers
                }
            },
            "x-amazon-apigateway-integration": {
                "responses": {
                    "default": {
                        "statusCode": "200",
                        "responseParameters": response_params,
                    }
                },
                "requestTemplates": {
                    "application/json": "{\"statusCode\": 200}"
                },
                "passthroughBehavior": "when_no_match",
                "type": "mock",
                "contentHandling": "CONVERT_TO_TEXT"
            }
        }
        swagger_for_path['options'] = options_request


class CFNSwaggerGenerator(SwaggerGenerator):
    def __init__(self):
        # type: () -> None
        pass

    def _uri(self, lambda_arn=None):
        # type: (Optional[str]) -> Any
        return {
            'Fn::Sub': (
                'arn:${AWS::Partition}:apigateway:${AWS::Region}'
                ':lambda:path/2015-03-31'
                '/functions/${APIHandler.Arn}/invocations'
            )
        }

    def _auth_uri(self, authorizer):
        # type: (ChaliceAuthorizer) -> Any
        return {
            'Fn::Sub': (
                'arn:${AWS::Partition}:apigateway:${AWS::Region}'
                ':lambda:path/2015-03-31'
                '/functions/${%s.Arn}/invocations' % to_cfn_resource_name(
                    authorizer.name)
            )
        }


class TemplatedSwaggerGenerator(SwaggerGenerator):
    def __init__(self):
        # type: () -> None
        pass

    def _uri(self, lambda_arn=None):
        # type: (Optional[str]) -> Any
        return StringFormat(
            'arn:{partition}:apigateway:{region_name}:lambda:path/2015-03-31'
            '/functions/{api_handler_lambda_arn}/invocations',
            ['partition', 'region_name', 'api_handler_lambda_arn'],
        )

    def _auth_uri(self, authorizer):
        # type: (ChaliceAuthorizer) -> Any
        varname = '%s_lambda_arn' % authorizer.name
        return StringFormat(
            'arn:{partition}:apigateway:{region_name}:lambda:path/2015-03-31'
            '/functions/{%s}/invocations' % varname,
            ['partition', 'region_name', varname],
        )


class TerraformSwaggerGenerator(SwaggerGenerator):

    def __init__(self):
        # type: () -> None
        pass

    def _uri(self, lambda_arn=None):
        # type: (Optional[str]) -> Any
        return '${aws_lambda_function.api_handler.invoke_arn}'

    def _auth_uri(self, authorizer):
        # type: (ChaliceAuthorizer) -> Any
        return '${aws_lambda_function.%s.invoke_arn}' % (authorizer.name)
