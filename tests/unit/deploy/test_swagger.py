from chalice.deploy.swagger import SwaggerGenerator
from chalice import CORSConfig

from pytest import fixture

@fixture
def swagger_gen():
    return SwaggerGenerator(region='us-west-2',
                            lambda_arn='lambda_arn')


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
    apig_integ = single_method['x-amazon-apigateway-integration']
    assert 'parameters' in apig_integ
    assert apig_integ['parameters'] == [
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


def test_can_add_preflight_cors(sample_app, swagger_gen):
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
        'method.response.header.Access-Control-Allow-Methods': (
            "'GET,POST,OPTIONS'"),
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


def test_can_add_preflight_custom_cors(sample_app, swagger_gen):
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
        'method.response.header.Access-Control-Allow-Methods': (
            "'GET,POST,OPTIONS'"),
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


def test_can_add_authorizers(sample_app, swagger_gen):
    @sample_app.route('/api-key-required',
                      authorizer_name='MyUserPool')
    def foo(name):
        return {}

    # Doesn't matter if you define the authorizer before
    # it's referenced.
    sample_app.define_authorizer(
        name='MyUserPool',
        header='Authorization',
        auth_type='cognito_user_pools',
        provider_arns=['arn:aws:cog:r:1:userpool/name']
    )

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
            'providerARNs': ['arn:aws:cog:r:1:userpool/name']
        }
    }


def test_can_add_binary_media_types(sample_app, swagger_gen):
    sample_app.add_binary_media_types(['image/png'])

    doc = swagger_gen.generate_swagger(sample_app)
    binary_media_types = doc['x-amazon-apigateway-binary-media-types']
    assert binary_media_types == ['image/png']
