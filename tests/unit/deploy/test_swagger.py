from chalice.deploy.swagger import SwaggerGenerator, CFNSwaggerGenerator
from chalice import CORSConfig
from chalice.app import CustomAuthorizer, CognitoUserPoolAuthorizer
from chalice.app import IAMAuthorizer, Chalice

import mock
from pytest import fixture


@fixture
def swagger_gen():
    return SwaggerGenerator(
        region='us-west-2',
        deployed_resources={'api_handler_arn': 'lambda_arn'})


def test_can_add_binary_media_types(swagger_gen):
    app = Chalice('test-binary')
    doc = swagger_gen.generate_swagger(app)
    media_types = doc.get('x-amazon-apigateway-binary-media-types')
    assert sorted(media_types) == sorted(app.api.binary_types)


def test_can_produce_swagger_top_level_keys(sample_app, swagger_gen):
    swagger_doc = swagger_gen.generate_swagger(sample_app)
    assert swagger_doc['swagger'] == '2.0'
    assert swagger_doc['info']['title'] == 'sample'
    assert swagger_doc['schemes'] == ['https']
    assert '/' in swagger_doc['paths'], swagger_doc['paths']
    index_config = swagger_doc['paths']['/']
    assert 'get' in index_config


def test_can_produce_doc_for_method(sample_app, swagger_gen):
    doc = swagger_gen.generate_swagger(sample_app)
    single_method = doc['paths']['/']['get']
    assert single_method['consumes'] == ['application/json']
    assert single_method['produces'] == ['application/json']
    # 'responses' is validated in a separate test,
    # it's all boilerplate anyways.
    # Same for x-amazon-apigateway-integration.


def test_apigateway_integration_generation(sample_app, swagger_gen):
    doc = swagger_gen.generate_swagger(sample_app)
    single_method = doc['paths']['/']['get']
    apig_integ = single_method['x-amazon-apigateway-integration']
    assert apig_integ['passthroughBehavior'] == 'when_no_match'
    assert apig_integ['httpMethod'] == 'POST'
    assert apig_integ['type'] == 'aws_proxy'
    assert apig_integ['uri'] == (
        "arn:aws:apigateway:us-west-2:lambda:path"
        "/2015-03-31/functions/lambda_arn/invocations"
    )
    assert 'responses' in apig_integ
    responses = apig_integ['responses']
    assert responses['default'] == {'statusCode': '200'}


def test_can_add_url_captures_to_params(sample_app, swagger_gen):
    @sample_app.route('/path/{capture}')
    def foo(name):
        return {}

    doc = swagger_gen.generate_swagger(sample_app)
    single_method = doc['paths']['/path/{capture}']['get']
    assert 'parameters' in single_method
    assert single_method['parameters'] == [
        {'name': "capture", "in": "path", "required": True, "type": "string"}
    ]


def test_can_add_multiple_http_methods(sample_app, swagger_gen):
    @sample_app.route('/multimethod', methods=['GET', 'POST'])
    def multiple_methods():
        pass

    doc = swagger_gen.generate_swagger(sample_app)
    view_config = doc['paths']['/multimethod']
    assert 'get' in view_config
    assert 'post' in view_config
    assert view_config['get'] == view_config['post']


def test_can_use_same_route_with_diff_http_methods(sample_app, swagger_gen):
    @sample_app.route('/multimethod', methods=['GET'])
    def multiple_methods_get():
        pass

    @sample_app.route('/multimethod', methods=['POST'])
    def multiple_methods_post():
        pass

    doc = swagger_gen.generate_swagger(sample_app)
    view_config = doc['paths']['/multimethod']
    assert 'get' in view_config
    assert 'post' in view_config
    assert view_config['get'] == view_config['post']


class TestPreflightCORS(object):
    def get_access_control_methods(self, view_config):
        return view_config['options'][
            'x-amazon-apigateway-integration']['responses']['default'][
                'responseParameters'][
                    'method.response.header.Access-Control-Allow-Methods']

    def test_can_add_preflight_cors(self, sample_app, swagger_gen):
        @sample_app.route('/cors', methods=['GET', 'POST'], cors=CORSConfig(
            allow_origin='http://foo.com',
            allow_headers=['X-ZZ-Top', 'X-Special-Header'],
            expose_headers=['X-Exposed', 'X-Special'],
            max_age=600,
            allow_credentials=True))
        def cors_request():
            pass

        doc = swagger_gen.generate_swagger(sample_app)
        view_config = doc['paths']['/cors']
        # We should add an OPTIONS preflight request automatically.
        assert 'options' in view_config, (
            'Preflight OPTIONS method not added to CORS view')
        options = view_config['options']
        expected_response_params = {
            'method.response.header.Access-Control-Allow-Methods': mock.ANY,
            'method.response.header.Access-Control-Allow-Headers': (
                "'Authorization,Content-Type,X-Amz-Date,X-Amz-Security-Token,"
                "X-Api-Key,X-Special-Header,X-ZZ-Top'"),
            'method.response.header.Access-Control-Allow-Origin': (
                "'http://foo.com'"),
            'method.response.header.Access-Control-Expose-Headers': (
                "'X-Exposed,X-Special'"),
            'method.response.header.Access-Control-Max-Age': (
                "'600'"),
            'method.response.header.Access-Control-Allow-Credentials': (
                "'true'"),

        }
        assert options == {
            'consumes': ['application/json'],
            'produces': ['application/json'],
            'responses': {
                '200': {
                    'description': '200 response',
                    'schema': {
                        '$ref': '#/definitions/Empty'
                    },
                    'headers': {
                        'Access-Control-Allow-Origin': {'type': 'string'},
                        'Access-Control-Allow-Methods': {'type': 'string'},
                        'Access-Control-Allow-Headers': {'type': 'string'},
                        'Access-Control-Expose-Headers': {'type': 'string'},
                        'Access-Control-Max-Age': {'type': 'string'},
                        'Access-Control-Allow-Credentials': {'type': 'string'},
                    }
                }
            },
            'x-amazon-apigateway-integration': {
                'responses': {
                    'default': {
                        'statusCode': '200',
                        'responseParameters': expected_response_params,
                    }
                },
                'requestTemplates': {
                    'application/json': '{"statusCode": 200}'
                },
                'passthroughBehavior': 'when_no_match',
                'type': 'mock',
            },
        }

        allow_methods = self.get_access_control_methods(view_config)
        # Typically the header will follow the form of:
        # "METHOD,METHOD,...OPTIONS"
        # The individual assertions is needed because there is no guarantee
        # on the order of these methods in the string because the order is
        # derived from iterating through a dictionary, which is not ordered
        # in python 2.7. So instead assert the correct methods are present in
        # the string.
        assert 'GET' in allow_methods
        assert 'POST' in allow_methods
        assert 'OPTIONS' in allow_methods

    def test_can_add_preflight_custom_cors(self, sample_app, swagger_gen):
        @sample_app.route('/cors', methods=['GET', 'POST'], cors=True)
        def cors_request():
            pass

        doc = swagger_gen.generate_swagger(sample_app)
        view_config = doc['paths']['/cors']
        # We should add an OPTIONS preflight request automatically.
        assert 'options' in view_config, (
            'Preflight OPTIONS method not added to CORS view')
        options = view_config['options']
        expected_response_params = {
            'method.response.header.Access-Control-Allow-Methods': mock.ANY,
            'method.response.header.Access-Control-Allow-Headers': (
                "'Authorization,Content-Type,X-Amz-Date,X-Amz-Security-Token,"
                "X-Api-Key'"),
            'method.response.header.Access-Control-Allow-Origin': "'*'",
        }
        assert options == {
            'consumes': ['application/json'],
            'produces': ['application/json'],
            'responses': {
                '200': {
                    'description': '200 response',
                    'schema': {
                        '$ref': '#/definitions/Empty'
                    },
                    'headers': {
                        'Access-Control-Allow-Origin': {'type': 'string'},
                        'Access-Control-Allow-Methods': {'type': 'string'},
                        'Access-Control-Allow-Headers': {'type': 'string'},
                    }
                }
            },
            'x-amazon-apigateway-integration': {
                'responses': {
                    'default': {
                        'statusCode': '200',
                        'responseParameters': expected_response_params,
                    }
                },
                'requestTemplates': {
                    'application/json': '{"statusCode": 200}'
                },
                'passthroughBehavior': 'when_no_match',
                'type': 'mock',
            },
        }

        allow_methods = self.get_access_control_methods(view_config)
        # Typically the header will follow the form of:
        # "METHOD,METHOD,...OPTIONS"
        # The individual assertions is needed because there is no guarantee
        # on the order of these methods in the string because the order is
        # derived from iterating through a dictionary, which is not ordered
        # in python 2.7. So instead assert the correct methods are present in
        # the string.
        assert 'GET' in allow_methods
        assert 'POST' in allow_methods
        assert 'OPTIONS' in allow_methods

    def test_can_add_preflight_cors_for_shared_routes(
            self, sample_app, swagger_gen):

        @sample_app.route('/cors', methods=['GET'], cors=True)
        def cors_request():
            pass

        @sample_app.route('/cors', methods=['PUT'])
        def non_cors_request():
            pass

        doc = swagger_gen.generate_swagger(sample_app)
        view_config = doc['paths']['/cors']
        # We should add an OPTIONS preflight request automatically.
        assert 'options' in view_config, (
            'Preflight OPTIONS method not added to CORS view')
        allow_methods = self.get_access_control_methods(view_config)
        # PUT should not be included in allowed methods as it was not enabled
        # for CORS.
        assert allow_methods == "'GET,OPTIONS'"


def test_can_add_api_key(sample_app, swagger_gen):
    @sample_app.route('/api-key-required', api_key_required=True)
    def foo(name):
        return {}
    doc = swagger_gen.generate_swagger(sample_app)
    single_method = doc['paths']['/api-key-required']['get']
    assert 'security' in single_method
    assert single_method['security'] == [{
        'api_key': []
    }]
    # Also need to add in the api_key definition in the top level
    # security definitions.
    assert 'securityDefinitions' in doc
    assert 'api_key' in doc['securityDefinitions']
    assert doc['securityDefinitions']['api_key'] == {
        'type': 'apiKey',
        'name': 'x-api-key',
        'in': 'header'
    }


def test_can_use_authorizer_object(sample_app, swagger_gen):
    authorizer = CustomAuthorizer(
        'MyAuth', authorizer_uri='auth-uri', header='Authorization')

    @sample_app.route('/auth', authorizer=authorizer)
    def auth():
        return {'foo': 'bar'}

    doc = swagger_gen.generate_swagger(sample_app)
    single_method = doc['paths']['/auth']['get']
    assert single_method.get('security') == [{'MyAuth': []}]
    security_definitions = doc['securityDefinitions']
    assert 'MyAuth' in security_definitions
    assert security_definitions['MyAuth'] == {
        'type': 'apiKey',
        'name': 'Authorization',
        'in': 'header',
        'x-amazon-apigateway-authtype': 'custom',
        'x-amazon-apigateway-authorizer': {
            'authorizerUri': 'auth-uri',
            'type': 'token',
            'authorizerResultTtlInSeconds': 300
        }
    }


def test_can_use_api_key_and_authorizers(sample_app, swagger_gen):
    authorizer = CustomAuthorizer(
        'MyAuth', authorizer_uri='auth-uri', header='Authorization')

    @sample_app.route('/auth', authorizer=authorizer, api_key_required=True)
    def auth():
        return {'foo': 'bar'}

    doc = swagger_gen.generate_swagger(sample_app)
    single_method = doc['paths']['/auth']['get']
    assert single_method.get('security') == [
        {'api_key': []},
        {'MyAuth': []},
    ]


def test_can_use_iam_authorizer_object(sample_app, swagger_gen):
    authorizer = IAMAuthorizer()

    @sample_app.route('/auth', authorizer=authorizer)
    def auth():
        return {'foo': 'bar'}

    doc = swagger_gen.generate_swagger(sample_app)
    single_method = doc['paths']['/auth']['get']
    assert single_method.get('security') == [{'sigv4': []}]
    security_definitions = doc['securityDefinitions']
    assert 'sigv4' in security_definitions
    assert security_definitions['sigv4'] == {
          "in": "header",
          "type": "apiKey",
          "name": "Authorization",
          "x-amazon-apigateway-authtype": "awsSigv4"
    }


def test_can_use_cognito_auth_object(sample_app, swagger_gen):
    authorizer = CognitoUserPoolAuthorizer('MyUserPool',
                                           header='Authorization',
                                           provider_arns=['myarn'])

    @sample_app.route('/api-key-required', authorizer=authorizer)
    def foo():
        return {}

    doc = swagger_gen.generate_swagger(sample_app)
    single_method = doc['paths']['/api-key-required']['get']
    assert single_method.get('security') == [{'MyUserPool': []}]
    assert 'securityDefinitions' in doc
    assert doc['securityDefinitions'].get('MyUserPool') == {
        'in': 'header',
        'type': 'apiKey',
        'name': 'Authorization',
        'x-amazon-apigateway-authtype': 'cognito_user_pools',
        'x-amazon-apigateway-authorizer': {
            'type': 'cognito_user_pools',
            'providerARNs': ['myarn']
        }
    }


def test_auth_defined_for_multiple_methods(sample_app, swagger_gen):
    authorizer = CognitoUserPoolAuthorizer('MyUserPool',
                                           header='Authorization',
                                           provider_arns=['myarn'])

    @sample_app.route('/pool1', authorizer=authorizer)
    def foo():
        return {}

    @sample_app.route('/pool2', authorizer=authorizer)
    def bar():
        return {}

    doc = swagger_gen.generate_swagger(sample_app)
    assert 'securityDefinitions' in doc
    assert len(doc['securityDefinitions']) == 1


def test_builtin_auth(sample_app):
    swagger_gen = SwaggerGenerator(
        region='us-west-2',
        deployed_resources={
            'api_handler_arn': 'lambda_arn',
            'api_handler_name': 'api-dev',
            'lambda_functions': {
                'api-dev-myauth': {
                    'arn': 'auth_arn',
                    'type': 'authorizer',
                }
            }
        }
    )

    @sample_app.authorizer(name='myauth',
                           ttl_seconds=10,
                           execution_role='arn:role')
    def auth(auth_request):
        pass

    @sample_app.route('/auth', authorizer=auth)
    def foo():
        pass

    doc = swagger_gen.generate_swagger(sample_app)
    assert 'securityDefinitions' in doc
    assert doc['securityDefinitions']['myauth'] == {
        'in': 'header',
        'name': 'Authorization',
        'type': 'apiKey',
        'x-amazon-apigateway-authtype': 'custom',
        'x-amazon-apigateway-authorizer': {
            'type': 'token',
            'authorizerCredentials': 'arn:role',
            'authorizerResultTtlInSeconds': 10,
            'authorizerUri': ('arn:aws:apigateway:us-west-2:lambda:path'
                              '/2015-03-31/functions/auth_arn/invocations'),
        }
    }


def test_will_default_to_function_name_for_auth(sample_app):
    swagger_gen = SwaggerGenerator(
        region='us-west-2',
        deployed_resources={
            'api_handler_arn': 'lambda_arn',
            'api_handler_name': 'api-dev',
            'lambda_functions': {
                'api-dev-auth': {
                    'arn': 'auth_arn',
                    'type': 'authorizer',
                }
            }
        }
    )

    # No "name=" kwarg provided should default
    # to a name of "auth".
    @sample_app.authorizer(ttl_seconds=10, execution_role='arn:role')
    def auth(auth_request):
        pass

    @sample_app.route('/auth', authorizer=auth)
    def foo():
        pass

    doc = swagger_gen.generate_swagger(sample_app)
    assert 'securityDefinitions' in doc
    assert doc['securityDefinitions']['auth'] == {
        'in': 'header',
        'name': 'Authorization',
        'type': 'apiKey',
        'x-amazon-apigateway-authtype': 'custom',
        'x-amazon-apigateway-authorizer': {
            'type': 'token',
            'authorizerCredentials': 'arn:role',
            'authorizerResultTtlInSeconds': 10,
            'authorizerUri': ('arn:aws:apigateway:us-west-2:lambda:path'
                              '/2015-03-31/functions/auth_arn/invocations'),
        }
    }


def test_will_custom_auth_with_cfn(sample_app):
    swagger_gen = CFNSwaggerGenerator()

    # No "name=" kwarg provided should default
    # to a name of "auth".
    @sample_app.authorizer(ttl_seconds=10, execution_role='arn:role')
    def auth(auth_request):
        pass

    @sample_app.route('/auth', authorizer=auth)
    def foo():
        pass

    doc = swagger_gen.generate_swagger(sample_app)
    assert 'securityDefinitions' in doc
    assert doc['securityDefinitions']['auth'] == {
        'in': 'header',
        'name': 'Authorization',
        'type': 'apiKey',
        'x-amazon-apigateway-authtype': 'custom',
        'x-amazon-apigateway-authorizer': {
            'type': 'token',
            'authorizerCredentials': 'arn:role',
            'authorizerResultTtlInSeconds': 10,
            'authorizerUri': {
                'Fn::Sub': (
                    'arn:aws:apigateway:${AWS::Region}:lambda:path'
                    '/2015-03-31/functions/${Auth.Arn}/invocations'
                )
            }
        }
    }
