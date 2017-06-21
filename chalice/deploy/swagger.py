import copy

from typing import Any, List, Dict, Optional  # noqa

from chalice.app import Chalice, RouteEntry, Authorizer, CORSConfig  # noqa
from chalice.app import ChaliceAuthorizer


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

    def generate_swagger(self, app):
        # type: (Chalice) -> Dict[str, Any]
        api = copy.deepcopy(self._BASE_TEMPLATE)
        api['info']['title'] = app.app_name
        self._add_binary_types(api, app)
        self._add_route_paths(api, app)
        return api

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
                        current['security'], api, app.authorizers, view)
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
            function_name = '%s-%s' % (
                self._deployed_resources['api_handler_name'],
                authorizer.config.name
            )
            arn = self._deployed_resources['lambda_functions'][function_name]
            auth_config = authorizer.config
            config = {
                'in': 'header',
                'type': 'apiKey',
                'name': 'Authorization',
                'x-amazon-apigateway-authtype': 'custom',
                'x-amazon-apigateway-authorizer': {
                    'type': 'token',
                    'authorizerCredentials': auth_config.execution_role,
                    'authorizerUri': self._uri(arn),
                    'authorizerResultTtlInSeconds': auth_config.ttl_seconds,
                }
            }
        else:
            config = authorizer.to_swagger()
        api_config.setdefault(
            'securityDefinitions', {})[authorizer.name] = config

    def _add_to_security_definition(self, security,
                                    api_config, authorizers, view):
        # type: (Any, Dict[str, Any], Dict[str, Any], RouteEntry) -> None
        if view.authorizer is not None:
            self._generate_security_from_auth_obj(api_config, view.authorizer)
            return
        for auth in security:
            name = list(auth.keys())[0]
            if name == 'api_key':
                # This is just the api_key_required=True config
                swagger_snippet = {
                    'type': 'apiKey',
                    'name': 'x-api-key',
                    'in': 'header',
                }  # type: Dict[str, Any]
            else:
                # This whole section is deprecated and will
                # eventually be removed.  This handles the
                # authorizers that come in via app.define_authorizer(...)
                # The only supported type in this method is
                # 'cognito_user_pools'.  Everything else goes through the
                # preferred ``view.authorizer``.
                if name not in authorizers:
                    error_msg = (
                        "The authorizer '%s' is not defined.  "
                        "Use app.define_authorizer(...) to define an "
                        "authorizer." % (name)
                    )
                    if authorizers:
                        error_msg += (
                            '  Defined authorizers in this app: %s' %
                            ', '.join(authorizers))
                    raise ValueError(error_msg)
                authorizer_config = authorizers[name]
                auth_type = authorizer_config['auth_type']
                if auth_type != 'cognito_user_pools':
                    raise ValueError(
                        "Unknown auth type: '%s',  must be "
                        "'cognito_user_pools'" % (auth_type,))
                swagger_snippet = {
                    'in': 'header',
                    'type': 'apiKey',
                    'name': authorizer_config['header'],
                    'x-amazon-apigateway-authtype': auth_type,
                    'x-amazon-apigateway-authorizer': {
                        'type': auth_type,
                        'providerARNs': authorizer_config['provider_arns'],
                    }
                }
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
        if view.api_key_required:
            # When this happens we also have to add the relevant portions
            # to the security definitions.  We have to someone indicate
            # this because this neeeds to be added to the global config
            # file.
            current['security'] = [{'api_key': []}]
        if view.authorizer_name:
            current['security'] = [{view.authorizer_name: []}]
        if view.authorizer:
            current['security'] = [{view.authorizer.name: []}]
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
        return ('arn:aws:apigateway:{region}:lambda:path/2015-03-31'
                '/functions/{lambda_arn}/invocations').format(
                    region=self._region, lambda_arn=lambda_arn)

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
        if view.view_args:
            self._add_view_args(apig_integ, view.view_args)
        return apig_integ

    def _add_view_args(self, apig_integ, view_args):
        # type: (Dict[str, Any], List[str]) -> None
        apig_integ['parameters'] = [
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
                "type": "mock"
            }
        }
        swagger_for_path['options'] = options_request


class CFNSwaggerGenerator(SwaggerGenerator):
    def _uri(self, lambda_arn=None):
        # type: (Optional[str]) -> Any
        # TODO: Does this have to be return type Any?
        return {
            'Fn::Sub': (
                'arn:aws:apigateway:${AWS::Region}:lambda:path/2015-03-31'
                '/functions/${APIHandler.Arn}/invocations'
            )
        }
