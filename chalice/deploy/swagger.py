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
            if view.cors:
                self._add_preflight_request(view, swagger_for_path)

    def _add_to_security_definition(self, security, api_config, authorizers):
        # type: (Any, Dict[str, Any], Dict[str, Any]) -> None
        if 'api_key' in security:
            # This is just the api_key_required=True config
            swagger_snippet = {
                'type': 'apiKey',
                'name': 'x-api-key',
                'in': 'header',
            }  # type: Dict[str, Any]
            api_config.setdefault(
                'securityDefinitions', {})['api_key'] = swagger_snippet
        elif isinstance(security, list):
            for auth in security:
                # TODO: Add validation checks for unknown auth references.
                name = auth.keys()[0]
                authorizer_config = authorizers[name]
                auth_type = authorizer_config['auth_type']
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
            current['security'] = {'api_key': []}
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

    def _generate_apig_integ(self, view):
        # type: (RouteEntry) -> Dict[str, Any]
        apig_integ = {
            'responses': {
                'default': {
                    'statusCode': "200",
                }
            },
            'uri': (
                'arn:aws:apigateway:{region}:lambda:path/2015-03-31'
                '/functions/{lambda_arn}/invocations').format(
                    region=self._region, lambda_arn=self._lambda_arn),
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
        methods = view.methods + ['OPTIONS']
        allowed_methods = ','.join(methods)
        response_params = {
            "method.response.header.Access-Control-Allow-Methods": (
                "'%s'" % allowed_methods),
            "method.response.header.Access-Control-Allow-Headers": (
                "'Content-Type,X-Amz-Date,Authorization,X-Api-Key,"
                "X-Amz-Security-Token'"),
            "method.response.header.Access-Control-Allow-Origin": "'*'"
        }

        options_request = {
            "consumes": ["application/json"],
            "produces": ["application/json"],
            "responses": {
                "200": {
                    "description": "200 response",
                    "schema": {"$ref": "#/definitions/Empty"},
                    "headers": {
                        "Access-Control-Allow-Origin": {"type": "string"},
                        "Access-Control-Allow-Methods": {"type": "string"},
                        "Access-Control-Allow-Headers": {"type": "string"},
                    }
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
