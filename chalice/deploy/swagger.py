import copy

from typing import Any, List, Dict  # noqa

from chalice.app import Chalice, RouteEntry  # noqa


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

    _KNOWN_AUTH_TYPES = ['cognito_user_pools', 'custom']

    def __init__(self, region, lambda_arn):
        # type: (str, str) -> None
        self._region = region
        self._lambda_arn = lambda_arn

    def generate_swagger(self, app):
        # type: (Chalice) -> Dict[str, Any]
        api = copy.deepcopy(self._BASE_TEMPLATE)
        api['info']['title'] = app.app_name
        self._add_route_paths(api, app)
        return api

    def _add_route_paths(self, api, app):
        # type: (Dict[str, Any], Chalice) -> None
        for path, view in app.routes.items():
            swagger_for_path = {}  # type: Dict[str, Any]
            api['paths'][path] = swagger_for_path
            for http_method in view.methods:
                current = self._generate_route_method(view)
                if 'security' in current:
                    self._add_to_security_definition(
                        current['security'], api, app.authorizers)
                swagger_for_path[http_method.lower()] = current
            if view.cors is not None:
                self._add_preflight_request(view, swagger_for_path)

    def _add_to_security_definition(self, security, api_config, authorizers):
        # type: (Any, Dict[str, Any], Dict[str, Any]) -> None
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
                if auth_type not in self._KNOWN_AUTH_TYPES:
                    raise ValueError(
                        "Unknown auth type: '%s',  must be one of: %s" %
                        (auth_type, ', '.join(self._KNOWN_AUTH_TYPES)))
                swagger_snippet = {
                    'in': 'header',
                    'type': 'apiKey',
                    'name': authorizer_config['header'],
                    'x-amazon-apigateway-authtype': auth_type,
                    'x-amazon-apigateway-authorizer': {
                    }
                }
                if auth_type == 'custom':
                    auth_config = {
                        'type': auth_type,
                        'authorizerUri': authorizer_config['authorizer_uri'],
                        'authorizerResultTtlInSeconds': 300,
                        'type': 'token',
                    }
                elif auth_type == 'cognito_user_pools':
                    auth_config = {
                        'type': auth_type,
                        'providerARNs': authorizer_config['provider_arns'],
                    }
                swagger_snippet['x-amazon-apigateway-authorizer'] = auth_config
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

    def _uri(self):
        # type: () -> Any
        return ('arn:aws:apigateway:{region}:lambda:path/2015-03-31'
                '/functions/{lambda_arn}/invocations').format(
                    region=self._region, lambda_arn=self._lambda_arn)

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

    def _add_preflight_request(self, view, swagger_for_path):
        # type: (RouteEntry, Dict[str, Any]) -> None
        cors = view.cors
        methods = view.methods + ['OPTIONS']
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
    def _uri(self):
        # type: () -> Any
        # TODO: Does this have to be return type Any?
        return {
            'Fn::Sub': (
                'arn:aws:apigateway:${AWS::Region}:lambda:path/2015-03-31'
                '/functions/${APIHandler.Arn}/invocations'
            )
        }
