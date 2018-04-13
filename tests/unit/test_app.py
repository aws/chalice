import sys
import base64
import logging
import json

import pytest
from pytest import fixture
import hypothesis.strategies as st
from hypothesis import given, assume
import six


from chalice import app
from chalice import NotFoundError
from chalice.app import APIGateway, Request, Response, handle_decimals
from chalice import __version__ as chalice_version


# These are used to generate sample data for hypothesis tests.
STR_MAP = st.dictionaries(st.text(), st.text())
HTTP_METHOD = st.sampled_from(['GET', 'POST', 'PUT', 'PATCH',
                               'OPTIONS', 'HEAD', 'DELETE'])
HTTP_BODY = st.none() | st.text()
HTTP_REQUEST = st.fixed_dictionaries({
    'query_params': STR_MAP,
    'headers': STR_MAP,
    'uri_params': STR_MAP,
    'method': HTTP_METHOD,
    'body': HTTP_BODY,
    'context': STR_MAP,
    'stage_vars': STR_MAP,
    'is_base64_encoded': st.booleans(),
})
BINARY_TYPES = APIGateway().binary_types


class FakeLambdaContextIdentity(object):
    def __init__(self, cognito_identity_id, cognito_identity_pool_id):
        self.cognito_identity_id = cognito_identity_id
        self.cognito_identity_pool_id = cognito_identity_pool_id


class FakeLambdaContext(object):
    def __init__(self):
        self.function_name = 'test_name'
        self.function_version = 'version'
        self.invoked_function_arn = 'arn'
        self.memory_limit_in_mb = 256
        self.aws_request_id = 'id'
        self.log_group_name = 'log_group_name'
        self.log_stream_name = 'log_stream_name'
        self.identity = FakeLambdaContextIdentity('id', 'id_pool')
        # client_context is set by the mobile SDK and wont be set for chalice
        self.client_context = None

    def get_remaining_time_in_millis(self):
        return 500

    def serialize(self):
        serialized = {}
        serialized.update(vars(self))
        serialized['identity'] = vars(self.identity)
        return serialized


@pytest.fixture
def view_function():
    def _func():
        return {"hello": "world"}


def create_request_with_content_type(content_type):
    body = '{"json": "body"}'
    return app.Request(
        {}, {'Content-Type': content_type}, {}, 'GET',
        body, {}, {}, False
    )


def assert_response_body_is(response, body):
    assert json.loads(response['body']) == body


def json_response_body(response):
    return json.loads(response['body'])


@fixture
def sample_app():
    demo = app.Chalice('demo-app')

    @demo.route('/index', methods=['GET'])
    def index():
        return {'hello': 'world'}

    @demo.route('/name/{name}', methods=['GET'])
    def name(name):
        return {'provided-name': name}

    return demo


@fixture
def sample_app_with_cors():
    demo = app.Chalice('demo-app')

    @demo.route('/image', methods=['POST'], cors=True,
                content_types=['image/gif'])
    def image():
        return {'image': True}

    return demo


@fixture
def auth_request():
    method_arn = (
        "arn:aws:execute-api:us-west-2:123:rest-api-id/dev/GET/needs/auth")
    request = app.AuthRequest('TOKEN', 'authtoken', method_arn)
    return request


@pytest.mark.skipif(sys.version[0] == '2',
                    reason=('Test is irrelevant under python 2, since str and '
                            'bytes are interchangable.'))
def test_invalid_binary_response_body_throws_value_error(sample_app):
    response = app.Response(
        status_code=200,
        body={'foo': 'bar'},
        headers={'Content-Type': 'application/octet-stream'}
    )
    with pytest.raises(ValueError):
        response.to_dict(sample_app.api.binary_types)


def test_can_encode_binary_body_as_base64(sample_app):
    response = app.Response(
        status_code=200,
        body=b'foobar',
        headers={'Content-Type': 'application/octet-stream'}
    )
    encoded_response = response.to_dict(sample_app.api.binary_types)
    assert encoded_response['body'] == 'Zm9vYmFy'


def test_can_return_unicode_body(sample_app):
    unicode_data = u'\u2713'
    response = app.Response(
        status_code=200,
        body=unicode_data
    )
    encoded_response = response.to_dict()
    assert encoded_response['body'] == unicode_data


def test_can_encode_binary_body_with_header_charset(sample_app):
    response = app.Response(
        status_code=200,
        body=b'foobar',
        headers={'Content-Type': 'application/octet-stream; charset=binary'}
    )
    encoded_response = response.to_dict(sample_app.api.binary_types)
    assert encoded_response['body'] == 'Zm9vYmFy'


def test_can_encode_binary_json(sample_app):
    sample_app.api.binary_types.extend(['application/json'])
    response = app.Response(
        status_code=200,
        body={'foo': 'bar'},
        headers={'Content-Type': 'application/json'}
    )
    encoded_response = response.to_dict(sample_app.api.binary_types)
    assert encoded_response['body'] == 'eyJmb28iOiAiYmFyIn0='


def test_can_parse_route_view_args():
    entry = app.RouteEntry(lambda: {"foo": "bar"}, 'view-name',
                           '/foo/{bar}/baz/{qux}', method='GET')
    assert entry.view_args == ['bar', 'qux']


def test_can_route_single_view():
    demo = app.Chalice('app-name')

    @demo.route('/index')
    def index_view():
        return {}

    assert demo.routes['/index']['GET'] == app.RouteEntry(
        index_view, 'index_view', '/index', 'GET',
        content_types=['application/json'])


def test_can_handle_multiple_routes():
    demo = app.Chalice('app-name')

    @demo.route('/index')
    def index_view():
        return {}

    @demo.route('/other')
    def other_view():
        return {}

    assert len(demo.routes) == 2, demo.routes
    assert '/index' in demo.routes, demo.routes
    assert '/other' in demo.routes, demo.routes
    assert demo.routes['/index']['GET'].view_function == index_view
    assert demo.routes['/other']['GET'].view_function == other_view


def test_error_on_unknown_event(sample_app):
    bad_event = {'random': 'event'}
    raw_response = sample_app(bad_event, context=None)
    assert raw_response['statusCode'] == 500
    assert json_response_body(raw_response)['Code'] == 'InternalServerError'


def test_can_route_api_call_to_view_function(sample_app, create_event):
    event = create_event('/index', 'GET', {})
    response = sample_app(event, context=None)
    assert_response_body_is(response, {'hello': 'world'})


def test_can_call_to_dict_on_current_request(sample_app, create_event):
    @sample_app.route('/todict')
    def todict():
        return sample_app.current_request.to_dict()
    event = create_event('/todict', 'GET', {})
    response = json_response_body(sample_app(event, context=None))
    assert isinstance(response, dict)
    # The dict can change over time so we'll just pick
    # out a few keys as a basic sanity test.
    assert response['method'] == 'GET'
    # We also want to verify that to_dict() is always
    # JSON serializable so we check we can roundtrip
    # the data to/from JSON.
    assert isinstance(json.loads(json.dumps(response)), dict)


def test_request_to_dict_does_not_contain_internal_attrs(sample_app,
                                                         create_event):
    @sample_app.route('/todict')
    def todict():
        return sample_app.current_request.to_dict()
    event = create_event('/todict', 'GET', {})
    response = json_response_body(sample_app(event, context=None))
    internal_attrs = [key for key in response if key.startswith('_')]
    assert not internal_attrs


def test_will_pass_captured_params_to_view(sample_app, create_event):
    event = create_event('/name/{name}', 'GET', {'name': 'james'})
    response = sample_app(event, context=None)
    response = json_response_body(response)
    assert response == {'provided-name': 'james'}


def test_error_on_unsupported_method(sample_app, create_event):
    event = create_event('/name/{name}', 'POST', {'name': 'james'})
    raw_response = sample_app(event, context=None)
    assert raw_response['statusCode'] == 405
    assert json_response_body(raw_response)['Code'] == 'MethodNotAllowedError'


def test_error_on_unsupported_method_gives_feedback_on_method(sample_app,
                                                              create_event):
    method = 'POST'
    event = create_event('/name/{name}', method, {'name': 'james'})
    raw_response = sample_app(event, context=None)
    assert 'POST' in json_response_body(raw_response)['Message']


def test_error_contains_cors_headers(sample_app_with_cors, create_event):
    event = create_event('/image', 'POST', {'not': 'image'})
    raw_response = sample_app_with_cors(event, context=None)
    assert raw_response['statusCode'] == 415
    assert 'Access-Control-Allow-Origin' in raw_response['headers']


def test_no_view_function_found(sample_app, create_event):
    bad_path = create_event('/noexist', 'GET', {})
    with pytest.raises(app.ChaliceError):
        sample_app(bad_path, context=None)


def test_can_access_context(create_event):
    demo = app.Chalice('app-name')

    @demo.route('/index')
    def index_view():
        serialized = demo.lambda_context.serialize()
        return serialized

    event = create_event('/index', 'GET', {})
    lambda_context = FakeLambdaContext()
    result = demo(event, lambda_context)
    result = json_response_body(result)
    serialized_lambda_context = lambda_context.serialize()
    assert result == serialized_lambda_context


def test_can_access_raw_body(create_event):
    demo = app.Chalice('app-name')

    @demo.route('/index')
    def index_view():
        return {'rawbody': demo.current_request.raw_body.decode('utf-8')}

    event = create_event('/index', 'GET', {})
    event['body'] = '{"hello": "world"}'
    result = demo(event, context=None)
    result = json_response_body(result)
    assert result == {'rawbody': '{"hello": "world"}'}


def test_raw_body_cache_returns_same_result(create_event):
    demo = app.Chalice('app-name')

    @demo.route('/index')
    def index_view():
        # The first raw_body decodes base64,
        # the second value should return the cached value.
        # Both should be the same value
        return {'rawbody': demo.current_request.raw_body.decode('utf-8'),
                'rawbody2': demo.current_request.raw_body.decode('utf-8')}

    event = create_event('/index', 'GET', {})
    event['base64-body'] = base64.b64encode(
        b'{"hello": "world"}').decode('ascii')

    result = demo(event, context=None)
    result = json_response_body(result)
    assert result['rawbody'] == result['rawbody2']


def test_can_have_views_of_same_route_but_different_methods(create_event):
    demo = app.Chalice('app-name')

    @demo.route('/index', methods=['GET'])
    def get_view():
        return {'method': 'GET'}

    @demo.route('/index', methods=['PUT'])
    def put_view():
        return {'method': 'PUT'}

    assert demo.routes['/index']['GET'].view_function == get_view
    assert demo.routes['/index']['PUT'].view_function == put_view

    event = create_event('/index', 'GET', {})
    result = demo(event, context=None)
    assert json_response_body(result) == {'method': 'GET'}

    event = create_event('/index', 'PUT', {})
    result = demo(event, context=None)
    assert json_response_body(result) == {'method': 'PUT'}


def test_error_on_duplicate_route_methods():
    demo = app.Chalice('app-name')

    @demo.route('/index', methods=['PUT'])
    def index_view():
        return {'foo': 'bar'}

    with pytest.raises(ValueError):
        @demo.route('/index', methods=['PUT'])
        def index_view_dup():
            return {'foo': 'bar'}


def test_json_body_available_with_right_content_type(create_event):
    demo = app.Chalice('demo-app')

    @demo.route('/', methods=['POST'])
    def index():
        return demo.current_request.json_body

    event = create_event('/', 'POST', {})
    event['body'] = json.dumps({'foo': 'bar'})

    result = demo(event, context=None)
    result = json_response_body(result)
    assert result == {'foo': 'bar'}


def test_json_body_none_with_malformed_json(create_event):
    demo = app.Chalice('demo-app')

    @demo.route('/', methods=['POST'])
    def index():
        return demo.current_request.json_body

    event = create_event('/', 'POST', {})
    event['body'] = '{"foo": "bar"'

    result = demo(event, context=None)
    assert result['statusCode'] == 400
    assert json_response_body(result)['Code'] == 'BadRequestError'


def test_cant_access_json_body_with_wrong_content_type(create_event):
    demo = app.Chalice('demo-app')

    @demo.route('/', methods=['POST'], content_types=['application/xml'])
    def index():
        return (demo.current_request.json_body,
                demo.current_request.raw_body.decode('utf-8'))

    event = create_event('/', 'POST', {}, content_type='application/xml')
    event['body'] = '<Message>hello</Message>'

    response = json_response_body(demo(event, context=None))
    json_body, raw_body = response
    assert json_body is None
    assert raw_body == '<Message>hello</Message>'


def test_json_body_available_on_multiple_content_types(create_event_with_body):
    demo = app.Chalice('demo-app')

    @demo.route('/', methods=['POST'],
                content_types=['application/xml', 'application/json'])
    def index():
        return (demo.current_request.json_body,
                demo.current_request.raw_body.decode('utf-8'))

    event = create_event_with_body('<Message>hello</Message>',
                                   content_type='application/xml')

    response = json_response_body(demo(event, context=None))
    json_body, raw_body = response
    assert json_body is None
    assert raw_body == '<Message>hello</Message>'

    # Now if we create an event with JSON, we should be able
    # to access .json_body as well.
    event = create_event_with_body({'foo': 'bar'},
                                   content_type='application/json')
    response = json_response_body(demo(event, context=None))
    json_body, raw_body = response
    assert json_body == {'foo': 'bar'}
    assert raw_body == '{"foo": "bar"}'


def test_json_body_available_with_lowercase_content_type_key(
        create_event_with_body):
    demo = app.Chalice('demo-app')

    @demo.route('/', methods=['POST'])
    def index():
        return (demo.current_request.json_body,
                demo.current_request.raw_body.decode('utf-8'))

    event = create_event_with_body({'foo': 'bar'})
    del event['headers']['Content-Type']
    event['headers']['content-type'] = 'application/json'

    json_body, raw_body = json_response_body(demo(event, context=None))
    assert json_body == {'foo': 'bar'}
    assert raw_body == '{"foo": "bar"}'


def test_content_types_must_be_lists():
    demo = app.Chalice('app-name')

    with pytest.raises(ValueError):
        @demo.route('/index', content_types='application/not-a-list')
        def index_post():
            return {'foo': 'bar'}


def test_content_type_validation_raises_error_on_unknown_types(create_event):
    demo = app.Chalice('demo-app')

    @demo.route('/', methods=['POST'], content_types=['application/xml'])
    def index():
        return "success"

    bad_content_type = 'application/bad-xml'
    event = create_event('/', 'POST', {}, content_type=bad_content_type)
    event['body'] = 'Request body'

    json_response = json_response_body(demo(event, context=None))
    assert json_response['Code'] == 'UnsupportedMediaType'
    assert 'application/bad-xml' in json_response['Message']


def test_content_type_with_charset(create_event):
    demo = app.Chalice('demo-app')

    @demo.route('/', content_types=['application/json'])
    def index():
        return {'foo': 'bar'}

    event = create_event('/', 'GET', {}, 'application/json; charset=utf-8')
    response = json_response_body(demo(event, context=None))
    assert response == {'foo': 'bar'}


def test_can_return_response_object(create_event):
    demo = app.Chalice('app-name')

    @demo.route('/index')
    def index_view():
        return app.Response(status_code=200, body={'foo': 'bar'},
                            headers={'Content-Type': 'application/json'})

    event = create_event('/index', 'GET', {})
    response = demo(event, context=None)
    assert response == {'statusCode': 200, 'body': '{"foo": "bar"}',
                        'headers': {'Content-Type': 'application/json'}}


def test_headers_have_basic_validation(create_event):
    demo = app.Chalice('app-name')

    @demo.route('/index')
    def index_view():
        return app.Response(
            status_code=200, body='{}',
            headers={'Invalid-Header': 'foo\nbar'})

    event = create_event('/index', 'GET', {})
    response = demo(event, context=None)
    assert response['statusCode'] == 500
    assert 'Invalid-Header' not in response['headers']
    assert json.loads(response['body'])['Code'] == 'InternalServerError'


def test_empty_headers_have_basic_validation(create_empty_header_event):
    demo = app.Chalice('app-name')

    @demo.route('/index')
    def index_view():
        return app.Response(
            status_code=200, body='{}', headers={})

    event = create_empty_header_event('/index', 'GET', {})
    response = demo(event, context=None)
    assert response['statusCode'] == 200


def test_no_content_type_is_still_allowed(create_event):
    # When the content type validation happens in API gateway, it appears
    # to assume a default of application/json, so the chalice handler needs
    # to emulate that behavior.

    demo = app.Chalice('demo-app')

    @demo.route('/', methods=['POST'], content_types=['application/json'])
    def index():
        return {'success': True}

    event = create_event('/', 'POST', {})
    del event['headers']['Content-Type']

    json_response = json_response_body(demo(event, context=None))
    assert json_response == {'success': True}


def test_can_base64_encode_binary_media_types_bytes(create_event):
    demo = app.Chalice('demo-app')

    @demo.route('/index')
    def index_view():
        return app.Response(
            status_code=200,
            body=b'\u2713',
            headers={'Content-Type': 'application/octet-stream'})

    event = create_event('/index', 'GET', {})
    event['headers']['Accept'] = 'application/octet-stream'
    response = demo(event, context=None)
    assert response['statusCode'] == 200
    assert response['isBase64Encoded'] is True
    assert response['body'] == 'XHUyNzEz'
    assert response['headers']['Content-Type'] == 'application/octet-stream'


def test_can_return_text_even_with_binary_content_type_configured(
        create_event):
    demo = app.Chalice('demo-app')

    @demo.route('/index')
    def index_view():
        return app.Response(
            status_code=200,
            body='Plain text',
            headers={'Content-Type': 'text/plain'})

    event = create_event('/index', 'GET', {})
    event['headers']['Accept'] = 'application/octet-stream'
    response = demo(event, context=None)
    assert response['statusCode'] == 200
    assert response['body'] == 'Plain text'
    assert response['headers']['Content-Type'] == 'text/plain'


def test_route_equality(view_function):
    a = app.RouteEntry(
        view_function,
        view_name='myview', path='/',
        method='GET',
        api_key_required=True,
        content_types=['application/json'],
    )
    b = app.RouteEntry(
        view_function,
        view_name='myview', path='/',
        method='GET',
        api_key_required=True,
        content_types=['application/json'],
    )
    assert a == b


def test_route_inequality(view_function):
    a = app.RouteEntry(
        view_function,
        view_name='myview', path='/',
        method='GET',
        api_key_required=True,
        content_types=['application/json'],
    )
    b = app.RouteEntry(
        view_function,
        view_name='myview', path='/',
        method='GET',
        api_key_required=True,
        # Different content types
        content_types=['application/xml'],
    )
    assert not a == b


def test_exceptions_raised_as_chalice_errors(sample_app, create_event):

    @sample_app.route('/error')
    def raise_error():
        raise TypeError("Raising arbitrary error, should never see.")

    event = create_event('/error', 'GET', {})
    # This is intentional behavior.  If we're not in debug mode
    # we don't want to surface internal errors that get raised.
    # We should reply with a general internal server error.
    raw_response = sample_app(event, context=None)
    response = json_response_body(raw_response)
    assert response['Code'] == 'InternalServerError'
    assert raw_response['statusCode'] == 500


def test_original_exception_raised_in_debug_mode(sample_app, create_event):
    sample_app.debug = True

    @sample_app.route('/error')
    def raise_error():
        raise ValueError("You will see this error")

    event = create_event('/error', 'GET', {})
    response = sample_app(event, context=None)
    # In debug mode, we let the original exception propagate.
    # This includes the original type as well as the message.
    assert response['statusCode'] == 500
    assert 'ValueError' in response['body']
    assert 'You will see this error' in response['body']


def test_chalice_view_errors_propagate_in_non_debug_mode(sample_app,
                                                         create_event):
    @sample_app.route('/notfound')
    def notfound():
        raise NotFoundError("resource not found")

    event = create_event('/notfound', 'GET', {})
    raw_response = sample_app(event, context=None)
    assert raw_response['statusCode'] == 404
    assert json_response_body(raw_response)['Code'] == 'NotFoundError'


def test_chalice_view_errors_propagate_in_debug_mode(sample_app, create_event):
    @sample_app.route('/notfound')
    def notfound():
        raise NotFoundError("resource not found")
    sample_app.debug = True

    event = create_event('/notfound', 'GET', {})
    raw_response = sample_app(event, context=None)
    assert raw_response['statusCode'] == 404
    assert json_response_body(raw_response)['Code'] == 'NotFoundError'


def test_case_insensitive_mapping():
    mapping = app.CaseInsensitiveMapping({'HEADER': 'Value'})

    assert mapping['hEAdEr']
    assert mapping.get('hEAdEr')
    assert 'hEAdEr' in mapping
    assert repr({'header': 'Value'}) in repr(mapping)


def test_unknown_kwargs_raise_error(sample_app, create_event):
    with pytest.raises(TypeError):
        @sample_app.route('/foo', unknown_kwargs='foo')
        def badkwargs():
            pass


def test_default_logging_handlers_created():
    handlers_before = logging.getLogger('log_app').handlers[:]
    # configure_logs = True is the default, but we're
    # being explicit here.
    app.Chalice('log_app', configure_logs=True)
    handlers_after = logging.getLogger('log_app').handlers[:]
    new_handlers = set(handlers_after) - set(handlers_before)
    # Should have added a new handler
    assert len(new_handlers) == 1


def test_default_logging_only_added_once():
    # And creating the same app object means we shouldn't
    # configure logging again.
    handlers_before = logging.getLogger('added_once').handlers[:]
    app.Chalice('added_once', configure_logs=True)
    # The same app name, we should still only configure logs
    # once.
    app.Chalice('added_once', configure_logs=True)
    handlers_after = logging.getLogger('added_once').handlers[:]
    new_handlers = set(handlers_after) - set(handlers_before)
    # Should have added a new handler
    assert len(new_handlers) == 1


def test_logs_can_be_disabled():
    handlers_before = logging.getLogger('log_app').handlers[:]
    app.Chalice('log_app', configure_logs=False)
    handlers_after = logging.getLogger('log_app').handlers[:]
    new_handlers = set(handlers_after) - set(handlers_before)
    assert len(new_handlers) == 0


@pytest.mark.parametrize('content_type,is_json', [
    ('application/json', True),
    ('application/json;charset=UTF-8', True),
    ('application/notjson', False),
])
def test_json_body_available_when_content_type_matches(content_type, is_json):
    request = create_request_with_content_type(content_type)
    if is_json:
        assert request.json_body == {'json': 'body'}
    else:
        assert request.json_body is None


def test_can_receive_binary_data(create_event_with_body):
    content_type = 'application/octet-stream'
    demo = app.Chalice('demo-app')

    @demo.route('/bincat', methods=['POST'], content_types=[content_type])
    def bincat():
        raw_body = demo.current_request.raw_body
        return app.Response(
            raw_body,
            headers={'Content-Type': content_type},
            status_code=200)

    body = 'L3UyNzEz'
    event = create_event_with_body(body, '/bincat', 'POST', content_type)
    event['headers']['Accept'] = content_type
    event['isBase64Encoded'] = True
    response = demo(event, context=None)

    assert response['statusCode'] == 200
    assert response['body'] == body


def test_cannot_receive_base64_string_with_binary_response(
        create_event_with_body):
    content_type = 'application/octet-stream'
    demo = app.Chalice('demo-app')

    @demo.route('/bincat', methods=['GET'], content_types=[content_type])
    def bincat():
        return app.Response(
            status_code=200,
            body=b'\u2713',
            headers={'Content-Type': content_type})

    event = create_event_with_body('', '/bincat', 'GET', content_type)
    response = demo(event, context=None)

    assert response['statusCode'] == 400


def test_can_serialize_cognito_auth():
    auth = app.CognitoUserPoolAuthorizer(
        'Name', provider_arns=['Foo'], header='Authorization')
    assert auth.to_swagger() == {
        'in': 'header',
        'type': 'apiKey',
        'name': 'Authorization',
        'x-amazon-apigateway-authtype': 'cognito_user_pools',
        'x-amazon-apigateway-authorizer': {
            'type': 'cognito_user_pools',
            'providerARNs': ['Foo'],
        }
    }


def test_can_serialize_iam_auth():
    auth = app.IAMAuthorizer()
    assert auth.to_swagger() == {
            'in': 'header',
            'type': 'apiKey',
            'name': 'Authorization',
            'x-amazon-apigateway-authtype': 'awsSigv4',
        }


def test_typecheck_list_type():
    with pytest.raises(TypeError):
        app.CognitoUserPoolAuthorizer('Name', 'Authorization',
                                      provider_arns='foo')


def test_can_serialize_custom_authorizer():
    auth = app.CustomAuthorizer(
        'Name', 'myuri', ttl_seconds=10, header='NotAuth'
    )
    assert auth.to_swagger() == {
        'in': 'header',
        'type': 'apiKey',
        'name': 'NotAuth',
        'x-amazon-apigateway-authtype': 'custom',
        'x-amazon-apigateway-authorizer': {
            'type': 'token',
            'authorizerUri': 'myuri',
            'authorizerResultTtlInSeconds': 10,
        }
    }


class TestCORSConfig(object):
    def test_eq(self):
        cors_config = app.CORSConfig()
        other_cors_config = app.CORSConfig()
        assert cors_config == other_cors_config

    def test_not_eq_different_type(self):
        cors_config = app.CORSConfig()
        different_type_obj = object()
        assert cors_config != different_type_obj

    def test_not_eq_differing_configurations(self):
        cors_config = app.CORSConfig()
        differing_cors_config = app.CORSConfig(
            allow_origin='https://foo.example.com')
        assert cors_config != differing_cors_config

    def test_eq_non_default_configurations(self):
        custom_cors = app.CORSConfig(
            allow_origin='https://foo.example.com',
            allow_headers=['X-Special-Header'],
            max_age=600,
            expose_headers=['X-Special-Header'],
            allow_credentials=True
        )
        same_custom_cors = app.CORSConfig(
            allow_origin='https://foo.example.com',
            allow_headers=['X-Special-Header'],
            max_age=600,
            expose_headers=['X-Special-Header'],
            allow_credentials=True
        )
        assert custom_cors == same_custom_cors


def test_can_handle_builtin_auth():
    demo = app.Chalice('builtin-auth')

    @demo.authorizer()
    def my_auth(auth_request):
        pass

    @demo.route('/', authorizer=my_auth)
    def index_view():
        return {}

    assert len(demo.builtin_auth_handlers) == 1
    authorizer = demo.builtin_auth_handlers[0]
    assert isinstance(authorizer, app.BuiltinAuthConfig)
    assert authorizer.name == 'my_auth'
    assert authorizer.handler_string == 'app.my_auth'
    assert my_auth.name == 'my_auth'


def test_builtin_auth_can_transform_event():
    event = {
        'type': 'TOKEN',
        'authorizationToken': 'authtoken',
        'methodArn': 'arn:aws:execute-api:...:foo',
    }
    auth_app = app.Chalice('builtin-auth')

    request = []

    @auth_app.authorizer()
    def builtin_auth(auth_request):
        request.append(auth_request)

    builtin_auth(event, None)

    assert len(request) == 1
    transformed = request[0]
    assert transformed.auth_type == 'TOKEN'
    assert transformed.token == 'authtoken'
    assert transformed.method_arn == 'arn:aws:execute-api:...:foo'


def test_can_return_auth_dict_directly():
    # A user can bypass our AuthResponse and return the auth response
    # dict that API gateway expects.
    event = {
        'type': 'TOKEN',
        'authorizationToken': 'authtoken',
        'methodArn': 'arn:aws:execute-api:...:foo',
    }
    auth_app = app.Chalice('builtin-auth')

    response = {
        'context': {'foo': 'bar'},
        'principalId': 'user',
        'policyDocument': {
            'Version': '2012-10-17',
            'Statement': []
        }
    }

    @auth_app.authorizer()
    def builtin_auth(auth_request):
        return response

    actual = builtin_auth(event, None)
    assert actual == response


def test_can_specify_extra_auth_attributes():
    auth_app = app.Chalice('builtin-auth')

    @auth_app.authorizer(ttl_seconds=10, execution_role='arn:my-role')
    def builtin_auth(auth_request):
        pass

    handler = auth_app.builtin_auth_handlers[0]
    assert handler.ttl_seconds == 10
    assert handler.execution_role == 'arn:my-role'


def test_validation_raised_on_unknown_kwargs():
    auth_app = app.Chalice('builtin-auth')

    with pytest.raises(TypeError):
        @auth_app.authorizer(this_is_an_unknown_kwarg=True)
        def builtin_auth(auth_request):
            pass


def test_can_return_auth_response():
    event = {
        'type': 'TOKEN',
        'authorizationToken': 'authtoken',
        'methodArn': 'arn:aws:execute-api:us-west-2:1:id/dev/GET/a',
    }
    auth_app = app.Chalice('builtin-auth')

    response = {
        'context': {},
        'principalId': 'principal',
        'policyDocument': {
            'Version': '2012-10-17',
            'Statement': [
                {'Action': 'execute-api:Invoke',
                 'Effect': 'Allow',
                 'Resource': [
                     'arn:aws:execute-api:us-west-2:1:id/dev/*/a'
                 ]}
            ]
        }
    }

    @auth_app.authorizer()
    def builtin_auth(auth_request):
        return app.AuthResponse(['/a'], 'principal')

    actual = builtin_auth(event, None)
    assert actual == response


def test_auth_response_serialization():
    method_arn = (
        "arn:aws:execute-api:us-west-2:123:rest-api-id/dev/GET/needs/auth")
    request = app.AuthRequest('TOKEN', 'authtoken', method_arn)
    response = app.AuthResponse(routes=['/needs/auth'], principal_id='foo')
    response_dict = response.to_dict(request)
    expected = [method_arn.replace('GET', '*')]
    assert response_dict == {
        'policyDocument': {
            'Version': '2012-10-17',
            'Statement': [
                {
                    'Action': 'execute-api:Invoke',
                    'Resource': expected,
                    'Effect': 'Allow'
                }
            ]
        },
        'context': {},
        'principalId': 'foo',
    }


def test_auth_response_can_include_context(auth_request):
    response = app.AuthResponse(['/foo'], 'principal', {'foo': 'bar'})
    serialized = response.to_dict(auth_request)
    assert serialized['context'] == {'foo': 'bar'}


def test_can_use_auth_routes_instead_of_strings(auth_request):
    expected = [
        "arn:aws:execute-api:us-west-2:123:rest-api-id/dev/GET/a",
        "arn:aws:execute-api:us-west-2:123:rest-api-id/dev/GET/a/b",
        "arn:aws:execute-api:us-west-2:123:rest-api-id/dev/POST/a/b",
    ]
    response = app.AuthResponse(
        [app.AuthRoute('/a', ['GET']),
         app.AuthRoute('/a/b', ['GET', 'POST'])],
        'principal')
    serialized = response.to_dict(auth_request)
    assert serialized['policyDocument'] == {
        'Version': '2012-10-17',
        'Statement': [{
            'Action': 'execute-api:Invoke',
            'Effect': 'Allow',
            'Resource': expected,
        }]
    }


def test_auth_response_wildcard(auth_request):
    response = app.AuthResponse(
        routes=[app.AuthRoute(path='*', methods=['*'])],
        principal_id='user')
    serialized = response.to_dict(auth_request)
    assert serialized['policyDocument'] == {
        'Statement': [
            {'Action': 'execute-api:Invoke',
             'Effect': 'Allow',
             'Resource': [
                 'arn:aws:execute-api:us-west-2:123:rest-api-id/dev/*/*']}],
        'Version': '2012-10-17'
    }


def test_auth_response_wildcard_string(auth_request):
    response = app.AuthResponse(
        routes=['*'], principal_id='user')
    serialized = response.to_dict(auth_request)
    assert serialized['policyDocument'] == {
        'Statement': [
            {'Action': 'execute-api:Invoke',
             'Effect': 'Allow',
             'Resource': [
                 'arn:aws:execute-api:us-west-2:123:rest-api-id/dev/*/*']}],
        'Version': '2012-10-17'
    }


def test_can_mix_auth_routes_and_strings(auth_request):
    expected = [
        'arn:aws:execute-api:us-west-2:123:rest-api-id/dev/*/a',
        'arn:aws:execute-api:us-west-2:123:rest-api-id/dev/GET/a/b',
    ]
    response = app.AuthResponse(
        ['/a', app.AuthRoute('/a/b', ['GET'])],
        'principal')
    serialized = response.to_dict(auth_request)
    assert serialized['policyDocument'] == {
        'Version': '2012-10-17',
        'Statement': [{
            'Action': 'execute-api:Invoke',
            'Effect': 'Allow',
            'Resource': expected,
        }]
    }


def test_special_cased_root_resource(auth_request):
    # Not sure why, but API gateway uses `//` for the root
    # resource.  I've confirmed it doesn't do this for non-root
    # URLs.  We don't to let that leak out to the APIs we expose.
    auth_request.method_arn = (
        "arn:aws:execute-api:us-west-2:123:rest-api-id/dev/GET//")
    expected = [
        "arn:aws:execute-api:us-west-2:123:rest-api-id/dev/GET//"
    ]
    response = app.AuthResponse(
        [app.AuthRoute('/', ['GET'])],
        'principal')
    serialized = response.to_dict(auth_request)
    assert serialized['policyDocument'] == {
        'Version': '2012-10-17',
        'Statement': [{
            'Action': 'execute-api:Invoke',
            'Effect': 'Allow',
            'Resource': expected,
        }]
    }


def test_can_register_scheduled_event_with_str(sample_app):
    @sample_app.schedule('rate(1 minute)')
    def foo(event):
        pass

    assert len(sample_app.event_sources) == 1
    event_source = sample_app.event_sources[0]
    assert event_source.name == 'foo'
    assert event_source.schedule_expression == 'rate(1 minute)'
    assert event_source.handler_string == 'app.foo'


def test_can_register_scheduled_event_with_rate(sample_app):
    @sample_app.schedule(app.Rate(value=2, unit=app.Rate.HOURS))
    def foo(event):
        pass

    # We don't convert the rate down to its string form until
    # we actually deploy.
    assert len(sample_app.event_sources) == 1
    expression = sample_app.event_sources[0].schedule_expression
    # We already check the event source in the test above, so we're
    # only interested in the schedule expression here.
    assert expression.value == 2
    assert expression.unit == app.Rate.HOURS


def test_can_register_scheduled_event_with_event(sample_app):
    @sample_app.schedule(app.Cron(0, 10, '*', '*', '?', '*'))
    def foo(event):
        pass

    assert len(sample_app.event_sources) == 1
    expression = sample_app.event_sources[0].schedule_expression
    assert expression.minutes == 0
    assert expression.hours == 10
    assert expression.day_of_month == '*'
    assert expression.month == '*'
    assert expression.day_of_week == '?'
    assert expression.year == '*'


@pytest.mark.parametrize('value,unit,expected', [
    (1, app.Rate.MINUTES, 'rate(1 minute)'),
    (2, app.Rate.MINUTES, 'rate(2 minutes)'),
    (1, app.Rate.HOURS, 'rate(1 hour)'),
    (2, app.Rate.HOURS, 'rate(2 hours)'),
    (1, app.Rate.DAYS, 'rate(1 day)'),
    (2, app.Rate.DAYS, 'rate(2 days)'),
])
def test_rule_object_converts_to_str(value, unit, expected):
    assert app.Rate(value=value, unit=unit).to_string() == expected


@pytest.mark.parametrize(('minutes,hours,day_of_month,month,'
                          'day_of_week,year,expected'), [
    # These are taken from the scheduled events docs page.
    # Invoke a Lambda function at 10:00am (UTC) everyday
    (0, 10, '*', '*', '?', '*', 'cron(0 10 * * ? *)'),
    # Invoke a Lambda function 12:15pm (UTC) everyday
    (15, 12, '*', '*', '?', '*', 'cron(15 12 * * ? *)'),
    # Invoke a Lambda function at 06:00pm (UTC) every Mon-Fri
    (0, 18, '?', '*', 'MON-FRI', '*', 'cron(0 18 ? * MON-FRI *)'),
    # Invoke a Lambda function at 8:00am (UTC) every first day of the month
    (0, 8, 1, '*', '?', '*', 'cron(0 8 1 * ? *)'),
    # Invoke a Lambda function every 10 min Mon-Fri
    ('0/10', '*', '?', '*', 'MON-FRI', '*', 'cron(0/10 * ? * MON-FRI *)'),
    # Invoke a Lambda function every 5 minutes Mon-Fri between 8:00am and
    # 5:55pm (UTC)
    ('0/5', '8-17', '?', '*', 'MON-FRI', '*', 'cron(0/5 8-17 ? * MON-FRI *)'),
    # Invoke a Lambda function at 9 a.m. (UTC) the first Monday of each month
    (0, 9, '?', '*', '2#1', '*', 'cron(0 9 ? * 2#1 *)'),
])
def test_cron_expression_converts_to_str(minutes, hours, day_of_month, month,
                                         day_of_week, year, expected):
    assert app.Cron(
        minutes=minutes,
        hours=hours,
        day_of_month=day_of_month,
        month=month,
        day_of_week=day_of_week,
        year=year,
    ).to_string() == expected


def test_can_map_event_dict_to_object(sample_app):

    @sample_app.schedule('rate(1 hour)')
    def handler(event):
        return event

    # This is the event dict that lambda provides
    # to the lambda handler
    lambda_event = {
        "version": "0",
        "account": "123456789012",
        "region": "us-west-2",
        "detail": {},
        "detail-type": "Scheduled Event",
        "source": "aws.events",
        "time": "1970-01-01T00:00:00Z",
        "id": "event-id",
        "resources": [
          "arn:aws:events:us-west-2:123456789012:rule/my-schedule"
        ]
    }

    event_object = handler(lambda_event, context=None)
    assert event_object.version == '0'
    assert event_object.event_id == 'event-id'
    assert event_object.source == 'aws.events'
    assert event_object.account == '123456789012'
    assert event_object.time == '1970-01-01T00:00:00Z'
    assert event_object.region == 'us-west-2'
    assert event_object.resources == [
        "arn:aws:events:us-west-2:123456789012:rule/my-schedule"
    ]
    assert event_object.detail == {}
    assert event_object.detail_type == "Scheduled Event"
    # This is meant as a fall back in case you need access to
    # the raw lambda event dict.
    assert event_object.to_dict() == lambda_event


def test_pure_lambda_function_direct_mapping(sample_app):
    @sample_app.lambda_function()
    def handler(event, context):
        return event, context

    return_value = handler({'fake': 'event'}, {'fake': 'context'})
    assert return_value[0] == {'fake': 'event'}
    assert return_value[1] == {'fake': 'context'}


def test_pure_lambda_functions_are_registered_in_app(sample_app):
    @sample_app.lambda_function()
    def handler(event, context):
        pass

    assert len(sample_app.pure_lambda_functions) == 1
    lambda_function = sample_app.pure_lambda_functions[0]
    assert lambda_function.name == 'handler'
    assert lambda_function.handler_string == 'app.handler'


def test_aws_execution_env_set():
    env = {'AWS_EXECUTION_ENV': 'AWS_Lambda_python2.7'}
    app.Chalice('app-name', env=env)
    assert env['AWS_EXECUTION_ENV'] == (
        'AWS_Lambda_python2.7 aws-chalice/%s' % chalice_version
    )


def test_can_use_out_of_order_args(create_event):
    demo = app.Chalice('demo-app')

    # Note how the url params and function args are out of order.
    @demo.route('/{a}/{b}', methods=['GET'])
    def index(b, a):
        return {'a': a, 'b': b}
    event = create_event('/{a}/{b}', 'GET', {'a': 'first', 'b': 'second'})
    response = demo(event, context=None)
    response = json_response_body(response)
    assert response == {'a': 'first', 'b': 'second'}


def test_ensure_debug_mode_is_false_by_default():
    # These logger tests need to each have a unique name because the Chalice
    # app creates a logger with it's name. If these tests are run in a batch
    # the logger names will overlap in the logging module and cause test
    # failures.
    test_app = app.Chalice('logger-test-1')
    assert test_app.debug is False
    assert test_app.log.getEffectiveLevel() == logging.ERROR


def test_can_explicitly_set_debug_false_in_initializer():
    test_app = app.Chalice('logger-test-2', debug=False)
    assert test_app.debug is False
    assert test_app.log.getEffectiveLevel() == logging.ERROR


def test_can_set_debug_mode_in_initialzier():
    test_app = app.Chalice('logger-test-3', debug=True)
    assert test_app.debug is True
    assert test_app.log.getEffectiveLevel() == logging.DEBUG


def test_debug_mode_changes_log_level():
    test_app = app.Chalice('logger-test-4', debug=False)
    test_app.debug = True
    assert test_app.debug is True
    assert test_app.log.getEffectiveLevel() == logging.DEBUG


def test_raw_body_is_none_if_body_is_none():
    misc_kwargs = {
        'query_params': {},
        'headers': {},
        'uri_params': {},
        'method': 'GET',
        'context': {},
        'stage_vars': {},
        'is_base64_encoded': False,
    }
    request = app.Request(body=None, **misc_kwargs)
    assert request.raw_body == b''


@given(http_request_kwargs=HTTP_REQUEST)
def test_http_request_to_dict_is_json_serializable(http_request_kwargs):
    # We have to do some slight pre-preocessing here
    # to maintain preconditions.  If the
    # is_base64_encoded arg is True, we'll
    # base64 encode the body.  We assume API Gateway
    # upholds this precondition.
    is_base64_encoded = http_request_kwargs['is_base64_encoded']
    if is_base64_encoded:
        # Confirmed that if you send an empty body,
        # API Gateway will always say the body is *not*
        # base64 encoded.
        assume(http_request_kwargs['body'] is not None)
        body = base64.b64encode(
            http_request_kwargs['body'].encode('utf-8'))
        http_request_kwargs['body'] = body.decode('ascii')

    request = Request(**http_request_kwargs)
    assert isinstance(request.raw_body, bytes)
    request_dict = request.to_dict()
    # We should always be able to dump the request dict
    # to JSON.
    assert json.dumps(request_dict, default=handle_decimals)


@given(body=st.text(), headers=STR_MAP,
       status_code=st.integers(min_value=200, max_value=599))
def test_http_response_to_dict(body, headers, status_code):
    r = Response(body=body, headers=headers, status_code=status_code)
    serialized = r.to_dict()
    assert 'headers' in serialized
    assert 'statusCode' in serialized
    assert 'body' in serialized
    assert isinstance(serialized['body'], six.string_types)


@given(body=st.binary(), content_type=st.sampled_from(BINARY_TYPES))
def test_handles_binary_responses(body, content_type):
    r = Response(body=body, headers={'Content-Type': content_type})
    serialized = r.to_dict(BINARY_TYPES)
    # A binary response should always result in the
    # response being base64 encoded.
    assert serialized['isBase64Encoded']
    assert isinstance(serialized['body'], six.string_types)
    assert isinstance(base64.b64decode(serialized['body']), bytes)
