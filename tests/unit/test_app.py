import sys
import base64
import logging
import json
import gzip
import inspect
import collections
from copy import deepcopy
from datetime import datetime

import pytest
from pytest import fixture
import hypothesis.strategies as st
from hypothesis import given, assume
import six

from chalice import app
from chalice import NotFoundError
from chalice.test import Client
from chalice.app import (
    APIGateway,
    Request,
    Response,
    handle_extra_types,
    MultiDict,
    WebsocketEvent,
    BadRequestError,
    WebsocketDisconnectedError,
    WebsocketEventSourceHandler,
    ConvertToMiddleware,
    WebsocketAPI,
    ChaliceUnhandledError,
)
from chalice import __version__ as chalice_version
from chalice.deploy.validate import ExperimentalFeatureError
from chalice.deploy.validate import validate_feature_flags


# These are used to generate sample data for hypothesis tests.
STR_MAP = st.dictionaries(st.text(), st.text())
STR_TO_LIST_MAP = st.dictionaries(
    st.text(),
    st.lists(elements=st.text(), min_size=1, max_size=5)
)
HTTP_METHOD = st.sampled_from(['GET', 'POST', 'PUT', 'PATCH',
                               'OPTIONS', 'HEAD', 'DELETE'])
PATHS = st.sampled_from(['/', '/foo/bar'])
HTTP_BODY = st.none() | st.text()
HTTP_REQUEST = st.fixed_dictionaries({
    'query_params': STR_TO_LIST_MAP,
    'headers': STR_MAP,
    'uri_params': STR_MAP,
    'method': HTTP_METHOD,
    'body': HTTP_BODY,
    'context': STR_MAP,
    'stage_vars': STR_MAP,
    'is_base64_encoded': st.booleans(),
    'path': PATHS,
})
HTTP_REQUEST = st.fixed_dictionaries({
    'multiValueQueryStringParameters': st.fixed_dictionaries({}),
    'headers': STR_MAP,
    'pathParameters': STR_MAP,
    'requestContext': st.fixed_dictionaries({
        'httpMethod': HTTP_METHOD,
        'resourcePath': PATHS,
    }),
    'body': HTTP_BODY,
    'stageVariables': STR_MAP,
    'isBase64Encoded': st.booleans(),
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


class FakeGoneException(Exception):
    pass


class FakeExceptionFactory(object):
    def __init__(self):
        self.GoneException = FakeGoneException


class FakeClient(object):
    def __init__(self, errors=None, infos=None):
        if errors is None:
            errors = []
        if infos is None:
            infos = []
        self._errors = errors
        self._infos = infos
        self.calls = collections.defaultdict(lambda: [])
        self.exceptions = FakeExceptionFactory()

    def post_to_connection(self, ConnectionId, Data):
        self._call('post_to_connection', ConnectionId, Data)

    def delete_connection(self, ConnectionId):
        self._call('close', ConnectionId)

    def get_connection(self, ConnectionId):
        self._call('info', ConnectionId)
        if self._infos is not None:
            info = self._infos.pop()
            return info

    def _call(self, name, *args):
        self.calls[name].append(tuple(args))
        if self._errors:
            error = self._errors.pop()
            raise error


class FakeSession(object):
    def __init__(self, client=None, region_name='us-west-2'):
        self.calls = []
        self._client = client
        self.region_name = region_name

    def client(self, name, endpoint_url=None):
        self.calls.append((name, endpoint_url))
        return self._client


@pytest.fixture
def view_function():
    def _func():
        return {"hello": "world"}


def create_request_with_content_type(content_type):
    body = '{"json": "body"}'
    event = {
        'multiValueQueryStringParameters': '',
        'headers': {'Content-Type': content_type},
        'pathParameters': {},
        'requestContext': {
            'httpMethod': 'GET',
            'resourcePath': '/',
        },
        'body': body,
        'stageVariables': {},
        'isBase64Encoded': False,
    }
    return app.Request(event, FakeLambdaContext())


def assert_response_body_is(response, body):
    assert json.loads(response['body']) == body


def json_response_body(response):
    return json.loads(response['body'])


def assert_requires_opt_in(app, flag):
    with pytest.raises(ExperimentalFeatureError):
        validate_feature_flags(app)
    # Now ensure if we opt in to the feature, we don't
    # raise an exception.
    app.experimental_feature_flags.add(flag)
    try:
        validate_feature_flags(app)
    except ExperimentalFeatureError:
        raise AssertionError(
            "Opting in to feature %s still raises an "
            "ExperimentalFeatureError." % flag
        )


def websocket_handler_for_route(route, app):
    fn = app.websocket_handlers[route].handler_function
    handler = WebsocketEventSourceHandler(
        fn, WebsocketEvent, app.websocket_api)
    return handler


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
def sample_app_with_default_cors():
    demo = app.Chalice('demo-app')
    demo.api.cors = True

    @demo.route('/on', methods=['POST'],
                content_types=['image/gif'])
    def on():
        return {'image': True}

    @demo.route('/off', methods=['POST'], cors=False,
                content_types=['image/gif'])
    def off():
        return {'image': True}

    @demo.route('/default', methods=['POST'], cors=None,
                content_types=['image/gif'])
    def default():
        return {'image': True}

    return demo


@fixture
def sample_websocket_app():
    demo = app.Chalice('app-name')
    demo.websocket_api.session = FakeSession()

    calls = []

    @demo.on_ws_connect()
    def connect(event):
        demo.websocket_api.send(event.connection_id, 'connected')
        calls.append(('connect', event))

    @demo.on_ws_disconnect()
    def disconnect(event):
        demo.websocket_api.send(event.connection_id, 'message')
        calls.append(('disconnect', event))

    @demo.on_ws_message()
    def message(event):
        demo.websocket_api.send(event.connection_id, 'disconnected')
        calls.append(('default', event))

    return demo, calls


@fixture
def sample_middleware_app():
    demo = app.Chalice('app-name')
    demo.calls = []

    @demo.middleware('all')
    def mymiddleware(event, get_response):
        demo.calls.append({'type': 'all',
                           'event': event.__class__.__name__})
        return get_response(event)

    @demo.middleware('s3')
    def mymiddleware_s3(event, get_response):
        demo.calls.append({'type': 's3',
                           'event': event.__class__.__name__})
        return get_response(event)

    @demo.middleware('sns')
    def mymiddleware_sns(event, get_response):
        demo.calls.append({'type': 'sns',
                           'event': event.__class__.__name__})
        return get_response(event)

    @demo.middleware('http')
    def mymiddleware_http(event, get_response):
        demo.calls.append({'type': 'http',
                           'event': event.__class__.__name__})
        return get_response(event)

    @demo.middleware('websocket')
    def mymiddleware_websocket(event, get_response):
        demo.calls.append({'type': 'websocket',
                           'event': event.__class__.__name__})
        return get_response(event)

    @demo.middleware('pure_lambda')
    def mymiddleware_pure_lambda(event, get_response):
        demo.calls.append({'type': 'pure_lambda',
                           'event': event.__class__.__name__})
        return get_response(event)

    @demo.route('/')
    def index():
        return {}

    @demo.on_s3_event(bucket='foo')
    def s3_handler(event):
        pass

    @demo.on_sns_message(topic='foo')
    def sns_handler(event):
        pass

    @demo.on_sqs_message(queue='foo')
    def sqs_handler(event):
        pass

    @demo.lambda_function()
    def lambda_handler(event, context):
        pass

    @demo.on_ws_message()
    def ws_handler(event):
        pass

    return demo


@fixture
def auth_request():
    method_arn = (
        "arn:aws:execute-api:us-west-2:123:rest-api-id/dev/GET/needs/auth")
    request = app.AuthRequest('TOKEN', 'authtoken', method_arn)
    return request


@pytest.mark.skipif(sys.version[0] == '2',
                    reason=('Test is irrelevant under python 2, since str and '
                            'bytes are interchangeable.'))
def test_invalid_binary_response_body_throws_value_error(sample_app):
    response = app.Response(
        status_code=200,
        body={'foo': 'bar'},
        headers={'Content-Type': 'application/octet-stream'}
    )
    with pytest.raises(ValueError):
        response.to_dict(sample_app.api.binary_types)


def test_invalid_JSON_response_body_throws_type_error(sample_app):
    response = app.Response(
        status_code=200,
        body={'foo': object()},
        headers={'Content-Type': 'application/json'}
    )
    with pytest.raises(TypeError):
        response.to_dict()


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
    assert encoded_response['body'] == 'eyJmb28iOiJiYXIifQ=='


def test_wildcard_accepts_with_native_python_types_serializes_json(
        sample_app, create_event):
    sample_app.api.binary_types = ['*/*']

    @sample_app.route('/py-dict')
    def py_dict():
        return {'foo': 'bar'}

    event = create_event('/py-dict', 'GET', {})
    event['headers']['Accept'] = '*/*'
    response = sample_app(event, context=None)
    # In this case, they've return a native python dict type, which should
    # be serialized to JSON and returned back to the user as JSON.  Because
    # we also have ``*/*`` as a binary type, we'll return the response
    # as a binary response type.
    assert base64.b64decode(response['body']) == b'{"foo":"bar"}'
    assert response['isBase64Encoded']


def test_wildcard_accepts_with_response_class(
        sample_app, create_event):
    sample_app.api.binary_types = ['*/*']

    @sample_app.route('/py-dict')
    def py_dict():
        return Response(body=json.dumps({'foo': 'bar'}).encode('utf-8'),
                        headers={'Content-Type': 'application/json'},
                        status_code=200)

    event = create_event('/py-dict', 'GET', {})
    event['headers']['Accept'] = '*/*'
    response = sample_app(event, context=None)
    # Because our binary types is '*/*' we should be returning this
    # content as binary.
    assert base64.b64decode(response['body']) == b'{"foo": "bar"}'
    assert response['isBase64Encoded']


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


def test_can_call_to_dict_on_request_with_querystring(sample_app,
                                                      create_event):
    @sample_app.route('/todict')
    def todict():
        return sample_app.current_request.to_dict()

    event = create_event('/todict', 'GET', {})
    event['multiValueQueryStringParameters'] = {
        'key': ['val1', 'val2'],
        'key2': ['val']
    }
    response = json_response_body(sample_app(event, context=None))
    assert isinstance(response, dict)
    # The dict can change over time so we'll just pick
    # out a few keys as a basic sanity test.
    assert response['method'] == 'GET'
    assert response['query_params'] is not None
    assert response['query_params']['key'] == 'val2'
    assert response['query_params']['key2'] == 'val'
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
    assert raw_response['headers']['Allow'] == 'GET'
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


class TestDefaultCORS(object):
    def test_cors_enabled(self, sample_app_with_default_cors, create_event):
        event = create_event('/on', 'POST', {'not': 'image'})
        raw_response = sample_app_with_default_cors(event, context=None)
        assert raw_response['statusCode'] == 415
        assert 'Access-Control-Allow-Origin' in raw_response['headers']

    def test_cors_none(self, sample_app_with_default_cors, create_event):
        event = create_event('/default', 'POST', {'not': 'image'})
        raw_response = sample_app_with_default_cors(event, context=None)
        assert raw_response['statusCode'] == 415
        assert 'Access-Control-Allow-Origin' in raw_response['headers']

    def test_cors_disabled(self, sample_app_with_default_cors, create_event):
        event = create_event('/off', 'POST', {'not': 'image'})
        raw_response = sample_app_with_default_cors(event, context=None)
        assert raw_response['statusCode'] == 415
        assert 'Access-Control-Allow-Origin' not in raw_response['headers']


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
        return app.Response(
            status_code=200,
            body={'foo': 'bar'},
            headers={
                'Content-Type': 'application/json',
                'Set-Cookie': ['key=value', 'foo=bar'],
            },
        )

    event = create_event('/index', 'GET', {})
    response = demo(event, context=None)
    assert response == {
        'statusCode': 200,
        'body': '{"foo":"bar"}',

        'headers': {'Content-Type': 'application/json'},
        'multiValueHeaders': {'Set-Cookie': ['key=value', 'foo=bar']},
    }


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


@pytest.mark.parametrize('content_type,accept', [
    ('application/octet-stream', 'application/octet-stream'),
    (
        'application/octet-stream', (
            'text/html,application/xhtml+xml,application/xml'
            ';q=0.9,image/webp,*/*;q=0.8'
        )
    ),
    ('image/gif', 'text/html,image/gif'),
    ('image/gif', 'text/html ,image/gif'),
    ('image/gif', 'text/html, image/gif'),
    ('image/gif', 'text/html;q=0.8, image/gif ;q=0.5'),
    ('image/gif', 'text/html,image/png'),
    ('image/png', 'text/html,image/gif'),
])
def test_can_base64_encode_binary_multiple_media_types(
        create_event, content_type, accept):
    demo = app.Chalice('demo-app')

    @demo.route('/index')
    def index_view():
        return app.Response(
            status_code=200,
            body=u'\u2713'.encode('utf-8'),
            headers={'Content-Type': content_type})

    event = create_event('/index', 'GET', {})
    event['headers']['Accept'] = accept
    response = demo(event, context=None)
    assert response['statusCode'] == 200
    assert response['isBase64Encoded'] is True
    assert response['body'] == '4pyT'
    assert response['headers']['Content-Type'] == content_type


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


def test_name_kwargs_does_not_raise_error(sample_app):
    try:
        @sample_app.route('/foo', name='foo')
        def name_kwarg():
            pass
    except TypeError:
        pytest.fail('route name kwarg should not raise TypeError.')


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
            body=u'\u2713'.encode('utf-8'),
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
        'Name', 'myuri', ttl_seconds=10, header='NotAuth',
        invoke_role_arn='role-arn'
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
            'authorizerCredentials': 'role-arn',
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
        assert not cors_config == different_type_obj

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


def test_root_resource(auth_request):
    auth_request.method_arn = (
        "arn:aws:execute-api:us-west-2:123:rest-api-id/dev/GET/")
    expected = [
        "arn:aws:execute-api:us-west-2:123:rest-api-id/dev/GET/"
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


def test_can_map_schedule_event_dict_to_object(sample_app):

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


def test_can_create_cwe_event_handler(sample_app):

    @sample_app.on_cw_event({'source': ['aws.ec2']})
    def handler(event):
        pass

    assert len(sample_app.event_sources) == 1
    event = sample_app.event_sources[0]
    assert event.name == 'handler'
    assert event.event_pattern == {'source': ['aws.ec2']}
    assert event.handler_string == 'app.handler'


def test_can_map_cwe_event_dict_to_object(sample_app):

    @sample_app.on_cw_event({'source': ['aws.ec2']})
    def handler(event):
        return event

    lambda_event = {
        "version": 0,
        "id": "7bf73129-1428-4cd3-a780-95db273d1602",
        "detail-type": "EC2 Instance State-change Notification",
        "source": "aws.ec2",
        "account": "123456789012",
        "time": "2015-11-11T21:29:54Z",
        "region": "us-east-1",
        "resources": [
            "arn:aws:ec2:us-east-1:123456789012:instance/i-abcd1111"
        ],
        "detail": {
            "instance-id": "i-abcd1111",
            "state": "pending"
        }
    }

    event_object = handler(lambda_event, context=None)
    assert event_object.detail_type == "EC2 Instance State-change Notification"
    assert event_object.account == '123456789012'
    assert event_object.region == 'us-east-1'
    assert event_object.detail == {
        'instance-id': 'i-abcd1111',
        'state': 'pending'
    }


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


def test_internal_exception_debug_false(capsys, create_event):
    test_app = app.Chalice('logger-test-5', debug=False)

    @test_app.route('/error')
    def error():
        raise Exception('Something bad happened')

    event = create_event('/error', 'GET', {})
    test_app(event, context=None)
    out, err = capsys.readouterr()
    assert 'logger-test-5' in out
    assert 'Caught exception' in out
    assert 'Something bad happened' in out


def test_raw_body_is_none_if_body_is_none():
    event = {
        'body': None,
        'multiValueQueryStringParameters': '',
        'headers': {},
        'pathParameters': {},
        'requestContext': {
            'httpMethod': 'GET',
            'resourcePath': '/',
        },
        'stageVariables': {},
        'isBase64Encoded': False,
    }
    request = app.Request(event, FakeLambdaContext())
    assert request.raw_body == b''


@given(http_request_event=HTTP_REQUEST)
def test_http_request_to_dict_is_json_serializable(http_request_event):
    # We have to do some slight pre-preprocessing here
    # to maintain preconditions.  If the
    # is_base64_encoded arg is True, we'll
    # base64 encode the body.  We assume API Gateway
    # upholds this precondition.
    is_base64_encoded = http_request_event['isBase64Encoded']
    if is_base64_encoded:
        # Confirmed that if you send an empty body,
        # API Gateway will always say the body is *not*
        # base64 encoded.
        assume(http_request_event['body'] is not None)
        body = base64.b64encode(
            http_request_event['body'].encode('utf-8'))
        http_request_event['body'] = body.decode('ascii')

    request = Request(http_request_event, FakeLambdaContext())
    assert isinstance(request.raw_body, bytes)
    request_dict = request.to_dict()
    # We should always be able to dump the request dict
    # to JSON.
    assert json.dumps(request_dict, default=handle_extra_types)


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


def test_can_create_s3_event_handler(sample_app):
    @sample_app.on_s3_event(bucket='mybucket')
    def handler(event):
        pass

    assert len(sample_app.event_sources) == 1
    event = sample_app.event_sources[0]
    assert event.name == 'handler'
    assert event.bucket == 'mybucket'
    assert event.events == ['s3:ObjectCreated:*']
    assert event.handler_string == 'app.handler'


def test_can_map_to_s3_event_object(sample_app):
    @sample_app.on_s3_event(bucket='mybucket')
    def handler(event):
        return event

    s3_event = {
        'Records': [
            {'awsRegion': 'us-west-2',
             'eventName': 'ObjectCreated:Put',
             'eventSource': 'aws:s3',
             'eventTime': '2018-05-22T04:41:23.823Z',
             'eventVersion': '2.0',
             'requestParameters': {'sourceIPAddress': '174.127.235.55'},
             'responseElements': {
                'x-amz-id-2': 'request-id-2',
                'x-amz-request-id': 'request-id-1'},
             's3': {
                 'bucket': {
                     'arn': 'arn:aws:s3:::mybucket',
                     'name': 'mybucket',
                     'ownerIdentity': {
                         'principalId': 'ABCD'
                     }
                 },
                 'configurationId': 'config-id',
                 'object': {
                     'eTag': 'd41d8cd98f00b204e9800998ecf8427e',
                     'key': 'hello-world.txt',
                     'sequencer': '005B039F73C627CE8B',
                     'size': 0
                 },
                 's3SchemaVersion': '1.0'
             },
             'userIdentity': {'principalId': 'AWS:XYZ'}
             }
        ]
    }
    actual_event = handler(s3_event, context=None)
    assert actual_event.bucket == 'mybucket'
    assert actual_event.key == 'hello-world.txt'
    assert actual_event.to_dict() == s3_event


def test_s3_event_urldecodes_keys():
    s3_event = {
        'Records': [
            {'s3': {
                 'bucket': {
                     'arn': 'arn:aws:s3:::mybucket',
                     'name': 'mybucket',
                 },
                 'object': {
                     'key': 'file+with+spaces',
                     'sequencer': '005B039F73C627CE8B',
                     'size': 0
                 },
            }},
        ]
    }
    event = app.S3Event(s3_event, FakeLambdaContext())
    # We should urldecode the key name.
    assert event.key == 'file with spaces'
    # But the key should remain unchanged in to_dict().
    assert event.to_dict() == s3_event


def test_s3_event_urldecodes_unicode_keys():
    s3_event = {
        'Records': [
            {'s3': {
                 'bucket': {
                     'arn': 'arn:aws:s3:::mybucket',
                     'name': 'mybucket',
                 },
                 'object': {
                     # This is u'\u2713'
                     'key': '%E2%9C%93',
                     'sequencer': '005B039F73C627CE8B',
                     'size': 0
                 },
            }},
        ]
    }
    event = app.S3Event(s3_event, FakeLambdaContext())
    # We should urldecode the key name.
    assert event.key == u'\u2713'
    assert event.bucket == u'mybucket'
    # But the key should remain unchanged in to_dict().
    assert event.to_dict() == s3_event


def test_can_create_sns_handler(sample_app):
    @sample_app.on_sns_message(topic='MyTopic')
    def handler(event):
        pass

    assert len(sample_app.event_sources) == 1
    event = sample_app.event_sources[0]
    assert event.name == 'handler'
    assert event.topic == 'MyTopic'
    assert event.handler_string == 'app.handler'


def test_can_map_sns_event(sample_app):
    @sample_app.on_sns_message(topic='MyTopic')
    def handler(event):
        return event

    sns_event = {'Records': [{
        'EventSource': 'aws:sns',
        'EventSubscriptionArn': 'arn:subscription-arn',
        'EventVersion': '1.0',
        'Sns': {
            'Message': 'This is a raw message',
            'MessageAttributes': {
                'AttributeKey': {
                    'Type': 'String',
                    'Value': 'AttributeValue'
                }
            },
            'MessageId': 'abcdefgh-51e4-5ae2-9964-b296c8d65d1a',
            'Signature': 'signature',
            'SignatureVersion': '1',
            'SigningCertUrl': 'https://sns.us-west-2.amazonaws.com/cert.pen',
            'Subject': 'ThisIsTheSubject',
            'Timestamp': '2018-06-26T19:41:38.695Z',
            'TopicArn': 'arn:aws:sns:us-west-2:12345:ConsoleTestTopic',
            'Type': 'Notification',
            'UnsubscribeUrl': 'https://unsubscribe-url/'}}]}
    lambda_context = FakeLambdaContext()
    actual_event = handler(sns_event, context=lambda_context)
    assert actual_event.message == 'This is a raw message'
    assert actual_event.subject == 'ThisIsTheSubject'
    assert actual_event.to_dict() == sns_event
    assert actual_event.context == lambda_context


def test_can_create_sqs_handler(sample_app):
    @sample_app.on_sqs_message(queue='MyQueue', batch_size=200)
    def handler(event):
        pass

    assert len(sample_app.event_sources) == 1
    event = sample_app.event_sources[0]
    assert event.queue == 'MyQueue'
    assert event.batch_size == 200
    assert event.handler_string == 'app.handler'


def test_can_set_sqs_handler_name(sample_app):
    @sample_app.on_sqs_message(queue='MyQueue', name='sqs_handler')
    def handler(event):
        pass

    assert len(sample_app.event_sources) == 1
    event = sample_app.event_sources[0]
    assert event.name == 'sqs_handler'


def test_can_map_sqs_event(sample_app):
    @sample_app.on_sqs_message(queue='queue-name')
    def handler(event):
        return event

    sqs_event = {'Records': [{
        'attributes': {
            'ApproximateFirstReceiveTimestamp': '1530576251596',
            'ApproximateReceiveCount': '1',
            'SenderId': 'sender-id',
            'SentTimestamp': '1530576251595'
        },
        'awsRegion': 'us-west-2',
        'body': 'queue message body',
        'eventSource': 'aws:sqs',
        'eventSourceARN': 'arn:aws:sqs:us-west-2:12345:queue-name',
        'md5OfBody': '754ac2f7a12df38320e0c5eafd060145',
        'messageAttributes': {},
        'messageId': 'message-id',
        'receiptHandle': 'receipt-handle'
    }]}
    lambda_context = FakeLambdaContext()
    actual_event = handler(sqs_event, context=lambda_context)
    records = list(actual_event)
    assert len(records) == 1
    first_record = records[0]
    assert first_record.body == 'queue message body'
    assert first_record.receipt_handle == 'receipt-handle'
    assert first_record.to_dict() == sqs_event['Records'][0]
    assert actual_event.to_dict() == sqs_event
    assert actual_event.context == lambda_context


def test_can_create_kinesis_handler(sample_app):
    @sample_app.on_kinesis_record(stream='MyStream',
                                  batch_size=1,
                                  starting_position='TRIM_HORIZON')
    def handler(event):
        pass

    assert len(sample_app.event_sources) == 1
    config = sample_app.event_sources[0]
    assert config.stream == 'MyStream'
    assert config.batch_size == 1
    assert config.starting_position == 'TRIM_HORIZON'


def test_can_map_kinesis_event(sample_app):
    @sample_app.on_kinesis_record(stream='MyStream')
    def handler(event):
        return event

    kinesis_event = {
        "Records": [
            {
                "kinesis": {
                    "kinesisSchemaVersion": "1.0",
                    "partitionKey": "1",
                    "sequenceNumber": "12345",
                    "data": "SGVsbG8sIHRoaXMgaXMgYSB0ZXN0Lg==",
                    "approximateArrivalTimestamp": 1545084650.987
                },
                "eventSource": "aws:kinesis",
                "eventVersion": "1.0",
                "eventID": "shardId-000000000006:12345",
                "eventName": "aws:kinesis:record",
                "invokeIdentityArn": "arn:aws:iam::123:role/lambda-role",
                "awsRegion": "us-east-2",
                "eventSourceARN": (
                    "arn:aws:kinesis:us-east-2:123:stream/lambda-stream"
                )
            },
            {
                "kinesis": {
                    "kinesisSchemaVersion": "1.0",
                    "partitionKey": "1",
                    "sequenceNumber": "12346",
                    "data": "VGhpcyBpcyBvbmx5IGEgdGVzdC4=",
                    "approximateArrivalTimestamp": 1545084711.166
                },
                "eventSource": "aws:kinesis",
                "eventVersion": "1.0",
                "eventID": "shardId-000000000006:12346",
                "eventName": "aws:kinesis:record",
                "invokeIdentityArn": "arn:aws:iam::123:role/lambda-role",
                "awsRegion": "us-east-2",
                "eventSourceARN": (
                    "arn:aws:kinesis:us-east-2:123:stream/lambda-stream"
                )
            }
        ]
    }
    lambda_context = FakeLambdaContext()
    actual_event = handler(kinesis_event, context=lambda_context)
    records = list(actual_event)
    assert len(records) == 2
    assert records[0].data == b'Hello, this is a test.'
    assert records[0].sequence_number == "12345"
    assert records[0].partition_key == "1"
    assert records[0].schema_version == "1.0"
    assert records[0].timestamp == datetime(2018, 12, 17, 22, 10, 50, 987000)
    assert records[1].data == b'This is only a test.'


def test_can_create_ddb_handler(sample_app):
    @sample_app.on_dynamodb_record(
        stream_arn='arn:aws:dynamodb:...:stream', batch_size=10,
        starting_position='TRIM_HORIZON')
    def handler(event):
        pass

    assert len(sample_app.event_sources) == 1
    config = sample_app.event_sources[0]
    assert config.stream_arn == 'arn:aws:dynamodb:...:stream'
    assert config.batch_size == 10
    assert config.starting_position == 'TRIM_HORIZON'


def test_can_map_ddb_event(sample_app):
    @sample_app.on_dynamodb_record(stream_arn='arn:aws:...:stream')
    def handler(event):
        return event

    ddb_event = {
        'Records': [
            {'awsRegion': 'us-west-2',
             'dynamodb': {'ApproximateCreationDateTime': 1601317140.0,
                          'Keys': {'PK': {'S': 'foo'}, 'SK': {'S': 'bar'}},
                          'NewImage': {'PK': {'S': 'foo'}, 'SK': {'S': 'bar'}},
                          'SequenceNumber': '1700000000020701978607',
                          'SizeBytes': 20,
                          'StreamViewType': 'NEW_AND_OLD_IMAGES'},
             'eventID': 'da037887f71a88a1f6f4cfd149709d5a',
             'eventName': 'INSERT',
             'eventSource': 'aws:dynamodb',
             'eventSourceARN': (
                 'arn:aws:dynamodb:us-west-2:12345:table/MyTable/stream/'
                 '2020-09-28T16:49:14.209'
             ),
             'eventVersion': '1.1'}
        ]
    }
    lambda_context = FakeLambdaContext()
    actual_event = handler(ddb_event, context=lambda_context)
    records = list(actual_event)
    assert len(records) == 1
    assert records[0].timestamp == datetime(2020, 9, 28, 18, 19)
    assert records[0].keys == {'PK': {'S': 'foo'}, 'SK': {'S': 'bar'}}
    assert records[0].new_image == {'PK': {'S': 'foo'}, 'SK': {'S': 'bar'}}
    assert records[0].old_image is None
    assert records[0].sequence_number == '1700000000020701978607'
    assert records[0].size_bytes == 20
    assert records[0].stream_view_type == 'NEW_AND_OLD_IMAGES'
    # Mapping from top level keys in a record.
    assert records[0].aws_region == 'us-west-2'
    assert records[0].event_id == 'da037887f71a88a1f6f4cfd149709d5a'
    assert records[0].event_name == 'INSERT'
    assert records[0].event_source_arn == (
        'arn:aws:dynamodb:us-west-2:12345:table/MyTable/stream/'
        '2020-09-28T16:49:14.209')
    # Computed value.
    assert records[0].table_name == 'MyTable'


def test_bytes_when_binary_type_is_application_json():
    demo = app.Chalice('demo-app')
    demo.api.binary_types.append('application/json')

    @demo.route('/compress_response')
    def index():
        blob = json.dumps({'hello': 'world'}).encode('utf-8')
        payload = gzip.compress(blob)
        custom_headers = {
            'Content-Type': 'application/json',
            'Content-Encoding': 'gzip'
        }
        return Response(body=payload, status_code=200, headers=custom_headers)

    return demo


def test_can_register_blueprint_on_app():
    myapp = app.Chalice('myapp')
    foo = app.Blueprint('foo')

    @foo.route('/foo')
    def first():
        pass

    myapp.register_blueprint(foo)
    assert sorted(list(myapp.routes.keys())) == ['/foo']


def test_can_combine_multiple_blueprints_in_single_app():
    myapp = app.Chalice('myapp')
    foo = app.Blueprint('foo')
    bar = app.Blueprint('bar')

    @foo.route('/foo')
    def myfoo():
        pass

    @bar.route('/bar')
    def mybar():
        pass

    myapp.register_blueprint(foo)
    myapp.register_blueprint(bar)

    assert sorted(list(myapp.routes)) == ['/bar', '/foo']


def test_can_preserve_signature_on_blueprint():
    myapp = app.Chalice('myapp')
    foo = app.Blueprint('foo')

    @foo.lambda_function()
    def first(event, context):
        return {'foo': 'bar'}

    myapp.register_blueprint(foo)

    # The handler string given to a blueprint
    # is the "module.function_name" so we have
    # to ensure we can continue to invoke the
    # function with its expected signature.
    assert first({}, None) == {'foo': 'bar'}


def test_doc_saved_on_route():
    myapp = app.Chalice('myapp')

    @myapp.route('/')
    def index():
        """My index docstring."""
        pass

    assert index.__doc__ == 'My index docstring.'


def test_blueprint_docstring_is_preserved():
    foo = app.Blueprint('foo')

    @foo.route('/foo')
    def first():
        """Blueprint docstring."""

    assert first.__doc__ == 'Blueprint docstring.'


def test_can_mount_apis_at_url_prefix():
    myapp = app.Chalice('myapp')
    foo = app.Blueprint('foo')

    @foo.route('/foo')
    def myfoo():
        pass

    @foo.route('/bar')
    def mybar():
        pass

    myapp.register_blueprint(foo, url_prefix='/myprefix')
    assert list(sorted(myapp.routes)) == ['/myprefix/bar', '/myprefix/foo']


def test_can_mount_root_url_in_blueprint():
    myapp = app.Chalice('myapp')
    foo = app.Blueprint('foo')
    root = app.Blueprint('root')

    @root.route('/')
    def myroot():
        pass

    @foo.route('/')
    def myfoo():
        pass

    @foo.route('/bar')
    def mybar():
        pass

    myapp.register_blueprint(foo, url_prefix='/foo')
    myapp.register_blueprint(root)
    assert list(sorted(myapp.routes)) == ['/', '/foo', '/foo/bar']


def test_can_combine_lambda_functions_and_routes_in_blueprints():
    myapp = app.Chalice('myapp')

    foo = app.Blueprint('app.chalicelib.blueprints.foo')

    @foo.route('/foo')
    def myfoo():
        pass

    @foo.lambda_function()
    def myfunction(event, context):
        pass

    myapp.register_blueprint(foo)
    assert len(myapp.pure_lambda_functions) == 1
    lambda_function = myapp.pure_lambda_functions[0]
    assert lambda_function.name == 'myfunction'
    assert lambda_function.handler_string == (
        'app.chalicelib.blueprints.foo.myfunction')

    assert list(myapp.routes) == ['/foo']


def test_can_mount_lambda_functions_with_name_prefix():
    myapp = app.Chalice('myapp')
    foo = app.Blueprint('app.chalicelib.blueprints.foo')

    @foo.lambda_function()
    def myfunction(event, context):
        return event

    myapp.register_blueprint(foo, name_prefix='myprefix_')
    assert len(myapp.pure_lambda_functions) == 1
    lambda_function = myapp.pure_lambda_functions[0]
    assert lambda_function.name == 'myprefix_myfunction'
    assert lambda_function.handler_string == (
        'app.chalicelib.blueprints.foo.myfunction')

    with Client(myapp) as c:
        response = c.lambda_.invoke(
            'myprefix_myfunction', {'foo': 'bar'}
        )
    assert response.payload == {'foo': 'bar'}


def test_can_mount_event_sources_with_blueprint():
    myapp = app.Chalice('myapp')
    foo = app.Blueprint('app.chalicelib.blueprints.foo')

    @foo.schedule('rate(5 minutes)')
    def myfunction(event):
        return event

    myapp.register_blueprint(foo, name_prefix='myprefix_')
    assert len(myapp.event_sources) == 1
    event_source = myapp.event_sources[0]
    assert event_source.name == 'myprefix_myfunction'
    assert event_source.schedule_expression == 'rate(5 minutes)'
    assert event_source.handler_string == (
        'app.chalicelib.blueprints.foo.myfunction')


def test_can_mount_all_decorators_in_blueprint():
    myapp = app.Chalice('myapp')
    foo = app.Blueprint('app.chalicelib.blueprints.foo')

    @foo.route('/foo')
    def routefoo():
        pass

    @foo.lambda_function(name='mylambdafunction')
    def mylambda(event, context):
        pass

    @foo.schedule('rate(5 minutes)')
    def bar(event):
        pass

    @foo.on_s3_event('MyBucket')
    def on_s3(event):
        pass

    @foo.on_sns_message('MyTopic')
    def on_sns(event):
        pass

    @foo.on_sqs_message('MyQueue')
    def on_sqs(event):
        pass

    myapp.register_blueprint(foo, name_prefix='myprefix_', url_prefix='/bar')
    event_sources = myapp.event_sources
    assert len(event_sources) == 4
    lambda_functions = myapp.pure_lambda_functions
    assert len(lambda_functions) == 1
    # Handles the name prefix and the name='' override in the decorator.
    assert lambda_functions[0].name == 'myprefix_mylambdafunction'
    assert list(myapp.routes) == ['/bar/foo']


def test_can_call_current_request_on_blueprint_when_mounted(create_event):
    myapp = app.Chalice('myapp')
    bp = app.Blueprint('app.chalicelib.blueprints.foo')

    @bp.route('/todict')
    def todict():
        return bp.current_request.to_dict()

    myapp.register_blueprint(bp)
    event = create_event('/todict', 'GET', {})
    response = json_response_body(myapp(event, context=None))
    assert isinstance(response, dict)
    assert response['method'] == 'GET'


def test_can_call_current_app_on_blueprint_when_mounted(create_event):
    myapp = app.Chalice('myapp')
    bp = app.Blueprint('app.chalicelib.blueprints.foo')

    @bp.route('/appname')
    def appname():
        return {'name': bp.current_app.app_name}

    myapp.register_blueprint(bp)
    event = create_event('/appname', 'GET', {})
    response = json_response_body(myapp(event, context=None))
    assert response == {'name': 'myapp'}


def test_can_call_lambda_context_on_blueprint_when_mounted(create_event):
    myapp = app.Chalice('myapp')
    bp = app.Blueprint('app.chalicelib.blueprints.foo')

    @bp.route('/context')
    def context():
        return bp.lambda_context

    myapp.register_blueprint(bp)
    event = create_event('/context', 'GET', {})
    response = json_response_body(myapp(event, context={'context': 'foo'}))
    assert response == {'context': 'foo'}


def test_can_add_authorizer_with_url_prefix_and_routes():
    myapp = app.Chalice('myapp')
    foo = app.Blueprint('app.chalicelib.blueprints.foo')

    @foo.authorizer()
    def myauth(event):
        pass

    @foo.route('/foo', authorizer=myauth)
    def routefoo():
        pass

    myapp.register_blueprint(foo, url_prefix='/bar')
    assert len(myapp.builtin_auth_handlers) == 1
    authorizer = myapp.builtin_auth_handlers[0]
    assert isinstance(authorizer, app.BuiltinAuthConfig)
    assert authorizer.name == 'myauth'
    assert authorizer.handler_string == 'app.chalicelib.blueprints.foo.myauth'


def test_runtime_error_if_current_request_access_on_non_registered_blueprint():
    bp = app.Blueprint('app.chalicelib.blueprints.foo')
    with pytest.raises(RuntimeError):
        bp.current_request


def test_every_decorator_added_to_blueprint():
    def is_public_method(obj):
        return inspect.isfunction(obj) and not obj.__name__.startswith('_')
    public_api = inspect.getmembers(
        app.DecoratorAPI,
        predicate=is_public_method
    )
    blueprint_api = [
        i[0] for i in
        inspect.getmembers(app.Blueprint, predicate=is_public_method)
    ]
    for method_name, _ in public_api:
        assert method_name in blueprint_api


@pytest.mark.parametrize('input_dict', [
    {},
    {'key': []}
])
def test_multidict_raises_keyerror(input_dict):
    d = MultiDict(input_dict)
    with pytest.raises(KeyError):
        val = d['key']
        assert val is val


def test_multidict_pop_raises_del_error():
    d = MultiDict({})
    with pytest.raises(KeyError):
        del d['key']


def test_multidict_getlist_does_raise_keyerror():
    d = MultiDict({})
    with pytest.raises(KeyError):
        d.getlist('key')


@pytest.mark.parametrize('input_dict', [
    {'key': ['value']},
    {'key': ['']},
    {'key': ['value1', 'value2', 'value3']},
    {'key': ['value1', 'value2', None]}
])
def test_multidict_returns_lastvalue(input_dict):
    d = MultiDict(input_dict)
    assert d['key'] == input_dict['key'][-1]


@pytest.mark.parametrize('input_dict', [
    {'key': ['value']},
    {'key': ['']},
    {'key': ['value1', 'value2', 'value3']},
    {'key': ['value1', 'value2', None]}
])
def test_multidict_returns_all_values(input_dict):
    d = MultiDict(input_dict)
    assert d.getlist('key') == input_dict['key']


@pytest.mark.parametrize('input_dict', [
    {'key': ['value']},
    {'key': ['']},
    {'key': ['value1', 'value2', 'value3']},
    {'key': ['value1', 'value2', None]}
])
def test_multidict_list_wont_change_source(input_dict):
    d = MultiDict(input_dict)
    dict_copy = deepcopy(input_dict)
    d.getlist('key')[0] = 'othervalue'
    assert d.getlist('key') == dict_copy['key']


@pytest.mark.parametrize('input_dict,key,popped,leftover', [
    (
        {'key': ['value'], 'key2': [[]]},
        'key',
        'value',
        {'key2': []},
    ),
    (
        {'key': [''], 'key2': [[]]},
        'key',
        '',
        {'key2': []},
    ),
    (
        {'key': ['value1', 'value2', 'value3'],
         'key2': [[]]},
        'key',
        'value3',
        {'key2': []},
    ),
])
def test_multidict_list_can_pop_value(input_dict, key, popped, leftover):
    d = MultiDict(input_dict)
    pop_result = d.pop(key)
    assert popped == pop_result
    assert leftover == {key: d[key] for key in d}


def test_multidict_assignment():
    d = MultiDict({})
    d['key'] = 'value'
    assert d['key'] == 'value'


def test_multidict_get_reassigned_value():
    d = MultiDict({})
    d['key'] = 'value'
    assert d['key'] == 'value'
    assert d.get('key') == 'value'
    assert d.getlist('key') == ['value']


def test_multidict_get_list_wraps_key():
    d = MultiDict({})
    d['key'] = ['value']
    assert d.getlist('key') == [['value']]


def test_multidict_repr():
    d = MultiDict({
        'foo': ['bar', 'baz'],
        'buz': ['qux'],
    })
    rep = repr(d)
    assert rep.startswith('MultiDict({')
    assert "'foo': ['bar', 'baz']" in rep
    assert "'buz': ['qux']" in rep


def test_multidict_str():
    d = MultiDict({
        'foo': ['bar', 'baz'],
        'buz': ['qux'],
    })
    rep = str(d)
    assert rep.startswith('MultiDict({')
    assert "'foo': ['bar', 'baz']" in rep
    assert "'buz': ['qux']" in rep


def test_can_configure_websockets(sample_websocket_app):
    demo, _ = sample_websocket_app

    assert len(demo.websocket_handlers) == 3, demo.websocket_handlers
    assert '$connect' in demo.websocket_handlers, demo.websocket_handlers
    assert '$disconnect' in demo.websocket_handlers, demo.websocket_handlers
    assert '$default' in demo.websocket_handlers, demo.websocket_handlers


def test_websocket_event_json_body_available(sample_websocket_app,
                                             create_websocket_event):
    demo = app.Chalice('demo-app')
    called = {'wascalled': False}

    @demo.on_ws_message()
    def message(event):
        called['wascalled'] = True
        assert event.json_body == {'foo': 'bar'}
        # Second access hits the cache. Test that that works as well.
        assert event.json_body == {'foo': 'bar'}

    event = create_websocket_event('$default', body='{"foo": "bar"}')
    handler = websocket_handler_for_route('$default', demo)

    handler(event, context=None)
    assert called['wascalled'] is True


def test_websocket_event_json_body_can_raise_error(sample_websocket_app,
                                                   create_websocket_event):
    demo = app.Chalice('demo-app')
    called = {'wascalled': False}

    @demo.on_ws_message()
    def message(event):
        called['wascalled'] = True
        with pytest.raises(BadRequestError):
            event.json_body

    event = create_websocket_event('$default', body='{"foo": "bar"')
    handler = websocket_handler_for_route('$default', demo)

    handler(event, context=None)
    assert called['wascalled'] is True


def test_can_route_websocket_connect_message(sample_websocket_app,
                                             create_websocket_event):
    demo, calls = sample_websocket_app
    client = FakeClient()
    demo.websocket_api.session = FakeSession(client)
    event = create_websocket_event('$connect')
    handler = websocket_handler_for_route('$connect', demo)
    response = handler(event, context=None)

    assert response == {'statusCode': 200}
    assert len(calls) == 1
    assert calls[0][0] == 'connect'
    event = calls[0][1]
    assert isinstance(event, WebsocketEvent)
    assert event.domain_name == 'abcd1234.execute-api.us-west-2.amazonaws.com'
    assert event.stage == 'api'
    assert event.connection_id == 'ABCD1234='


def test_can_route_websocket_disconnect_message(sample_websocket_app,
                                                create_websocket_event):
    demo, calls = sample_websocket_app
    client = FakeClient()
    demo.websocket_api.session = FakeSession(client)
    event = create_websocket_event('$disconnect')
    handler = websocket_handler_for_route('$disconnect', demo)
    response = handler(event, context=None)

    assert response == {'statusCode': 200}
    assert len(calls) == 1
    assert calls[0][0] == 'disconnect'
    event = calls[0][1]
    assert isinstance(event, WebsocketEvent)
    assert event.domain_name == 'abcd1234.execute-api.us-west-2.amazonaws.com'
    assert event.stage == 'api'
    assert event.connection_id == 'ABCD1234='


def test_can_route_websocket_default_message(sample_websocket_app,
                                             create_websocket_event):
    demo, calls = sample_websocket_app
    client = FakeClient()
    demo.websocket_api.session = FakeSession(client)
    event = create_websocket_event('$default', body='foo bar')
    handler = websocket_handler_for_route('$default', demo)
    response = handler(event, context=None)

    assert response == {'statusCode': 200}
    assert len(calls) == 1
    assert calls[0][0] == 'default'
    event = calls[0][1]
    assert isinstance(event, WebsocketEvent)
    assert event.domain_name == 'abcd1234.execute-api.us-west-2.amazonaws.com'
    assert event.stage == 'api'
    assert event.connection_id == 'ABCD1234='
    assert event.body == 'foo bar'


def test_can_configure_client_on_connect(sample_websocket_app,
                                         create_websocket_event):
    demo, calls = sample_websocket_app
    client = FakeClient()
    demo.websocket_api.session = FakeSession(client)
    event = create_websocket_event('$connect')
    handler = websocket_handler_for_route('$connect', demo)
    handler(event, context=None)

    assert demo.websocket_api.session.calls == [
        ('apigatewaymanagementapi',
         'https://abcd1234.execute-api.us-west-2.amazonaws.com/api'),
    ]


def test_uses_api_id_not_domain_name(sample_websocket_app,
                                     create_websocket_event):
    demo, calls = sample_websocket_app
    client = FakeClient()
    demo.websocket_api.session = FakeSession(client)
    event = create_websocket_event('$connect')
    # If you configure a custom domain name, we should still use the
    # original domainName generated from API gateway when configuring
    # the apigatewaymanagementapi client.
    event['requestContext']['domainName'] = 'api.custom-domain-name.com'
    handler = websocket_handler_for_route('$connect', demo)
    handler(event, context=None)
    assert demo.websocket_api.session.calls == [
        ('apigatewaymanagementapi',
         'https://abcd1234.execute-api.us-west-2.amazonaws.com/api'),
    ]


def test_fallsback_to_session_if_needed(sample_websocket_app,
                                        create_websocket_event):
    demo, calls = sample_websocket_app
    client = FakeClient()
    demo.websocket_api = WebsocketAPI(env={})
    demo.websocket_api.session = FakeSession(client, region_name='us-east-2')
    event = create_websocket_event('$connect')
    # If you configure a custom domain name, we should still use the
    # original domainName generated from API gateway when configuring
    # the apigatewaymanagementapi client.
    event['requestContext']['domainName'] = 'api.custom-domain-name.com'
    handler = websocket_handler_for_route('$connect', demo)
    handler(event, context=None)
    assert demo.websocket_api.session.calls == [
        ('apigatewaymanagementapi',
         'https://abcd1234.execute-api.us-east-2.amazonaws.com/api'),
    ]


def test_can_configure_client_on_disconnect(sample_websocket_app,
                                            create_websocket_event):
    demo, calls = sample_websocket_app
    client = FakeClient()
    demo.websocket_api.session = FakeSession(client)
    event = create_websocket_event('$disconnect')
    handler = websocket_handler_for_route('$disconnect', demo)
    handler(event, context=None)

    assert demo.websocket_api.session.calls == [
        ('apigatewaymanagementapi',
         'https://abcd1234.execute-api.us-west-2.amazonaws.com/api'),
    ]


def test_can_configure_client_on_message(sample_websocket_app,
                                         create_websocket_event):
    demo, calls = sample_websocket_app
    client = FakeClient()
    demo.websocket_api.session = FakeSession(client)
    event = create_websocket_event('$default', body='foo bar')
    handler = websocket_handler_for_route('$default', demo)

    handler(event, context=None)

    assert demo.websocket_api.session.calls == [
        ('apigatewaymanagementapi',
         'https://abcd1234.execute-api.us-west-2.amazonaws.com/api'),
    ]


def test_does_only_configure_client_once(sample_websocket_app,
                                         create_websocket_event):
    demo, calls = sample_websocket_app
    client = FakeClient()
    demo.websocket_api.session = FakeSession(client)
    event = create_websocket_event('$default', body='foo bar')
    handler = websocket_handler_for_route('$default', demo)

    handler(event, context=None)
    handler(event, context=None)

    assert demo.websocket_api.session.calls == [
        ('apigatewaymanagementapi',
         'https://abcd1234.execute-api.us-west-2.amazonaws.com/api'),
    ]


def test_cannot_configure_client_without_session(sample_websocket_app,
                                                 create_websocket_event):
    demo, calls = sample_websocket_app
    demo.websocket_api.session = None
    event = create_websocket_event('$default', body='foo bar')
    handler = websocket_handler_for_route('$default', demo)
    with pytest.raises(ValueError) as e:
        handler(event, context=None)

    assert str(e.value) == (
        'Assign app.websocket_api.session to a boto3 session before using '
        'the WebsocketAPI'
    )


def test_cannot_send_websocket_message_without_configure(
        sample_websocket_app, create_websocket_event):
    demo = app.Chalice('app-name')
    client = FakeClient()
    demo.websocket_api.session = FakeSession(client)

    @demo.on_ws_message()
    def message_handler(event):
        demo.websocket_api.send('connection_id', event.body)

    event = create_websocket_event('$default', body='foo bar')
    event_obj = WebsocketEvent(event, None)
    handler = demo.websocket_handlers['$default'].handler_function
    with pytest.raises(ValueError) as e:
        handler(event_obj)
    assert str(e.value) == (
        'WebsocketAPI.configure must be called before using the WebsocketAPI'
    )


def test_can_close_websocket_connection(create_websocket_event):
    demo = app.Chalice('app-name')
    client = FakeClient()
    demo.websocket_api.session = FakeSession(client)

    @demo.on_ws_message()
    def message_handler(event):
        demo.websocket_api.close('connection_id')

    event = create_websocket_event('$default', body='foo bar')
    handler = websocket_handler_for_route('$default', demo)
    handler(event, context=None)

    calls = client.calls['close']
    assert len(calls) == 1
    call = calls[0]
    connection_id = call[0]
    assert connection_id == 'connection_id'


def test_close_does_fail_if_already_disconnected(create_websocket_event):
    demo = app.Chalice('app-name')
    client = FakeClient(errors=[FakeGoneException])
    demo.websocket_api.session = FakeSession(client)

    @demo.on_ws_message()
    def message_handler(event):
        with pytest.raises(WebsocketDisconnectedError) as e:
            demo.websocket_api.close('connection_id')
        assert e.value.connection_id == 'connection_id'

    event = create_websocket_event('$default', body='foo bar')
    handler = websocket_handler_for_route('$default', demo)
    handler(event, context=None)

    calls = client.calls['close']
    assert len(calls) == 1
    call = calls[0]
    connection_id = call[0]
    assert connection_id == 'connection_id'


def test_info_does_fail_if_already_disconnected(create_websocket_event):
    demo = app.Chalice('app-name')
    client = FakeClient(errors=[FakeGoneException])
    demo.websocket_api.session = FakeSession(client)

    @demo.on_ws_message()
    def message_handler(event):
        with pytest.raises(WebsocketDisconnectedError) as e:
            demo.websocket_api.info('connection_id')
        assert e.value.connection_id == 'connection_id'

    event = create_websocket_event('$default', body='foo bar')
    handler = websocket_handler_for_route('$default', demo)
    handler(event, context=None)

    calls = client.calls['info']
    assert len(calls) == 1
    call = calls[0]
    connection_id = call[0]
    assert connection_id == 'connection_id'


def test_can__about_websocket_connection(create_websocket_event):
    demo = app.Chalice('app-name')
    client = FakeClient(infos=[{'foo': 'bar'}])
    demo.websocket_api.session = FakeSession(client)
    closure = {}

    @demo.on_ws_message()
    def message_handler(event):
        closure['info'] = demo.websocket_api.info('connection_id')

    event = create_websocket_event('$default', body='foo bar')
    handler = websocket_handler_for_route('$default', demo)
    handler(event, context=None)

    assert closure['info'] == {'foo': 'bar'}
    calls = client.calls['info']
    assert len(calls) == 1
    call = calls[0]
    connection_id = call[0]
    assert connection_id == 'connection_id'


def test_can_send_websocket_message(create_websocket_event):
    demo = app.Chalice('app-name')
    client = FakeClient()
    demo.websocket_api.session = FakeSession(client)

    @demo.on_ws_message()
    def message_handler(event):
        demo.websocket_api.send('connection_id', event.body)

    event = create_websocket_event('$default', body='foo bar')
    handler = websocket_handler_for_route('$default', demo)
    handler(event, context=None)

    calls = client.calls['post_to_connection']
    assert len(calls) == 1
    call = calls[0]
    connection_id, message = call
    assert connection_id == 'connection_id'
    assert message == 'foo bar'


def test_does_raise_on_send_to_bad_websocket(create_websocket_event):
    demo = app.Chalice('app-name')
    client = FakeClient(errors=[FakeGoneException])
    demo.websocket_api.session = FakeSession(client)

    @demo.on_ws_message()
    def message_handler(event):
        with pytest.raises(WebsocketDisconnectedError) as e:
            demo.websocket_api.send('connection_id', event.body)
        assert e.value.connection_id == 'connection_id'

    event = create_websocket_event('$default', body='foo bar')
    handler = websocket_handler_for_route('$default', demo)
    handler(event, context=None)


def test_does_reraise_on_websocket_send_error(create_websocket_event):
    class SomeOtherError(Exception):
        pass

    demo = app.Chalice('app-name')
    fake_418_error = SomeOtherError()
    fake_418_error.response = {'ResponseMetadata': {'HTTPStatusCode': 418}}
    client = FakeClient(errors=[fake_418_error])
    demo.websocket_api.session = FakeSession(client)

    @demo.on_ws_message()
    def message_handler(event):
        with pytest.raises(SomeOtherError):
            demo.websocket_api.send('connection_id', event.body)

    event = create_websocket_event('$default', body='foo bar')
    handler = websocket_handler_for_route('$default', demo)
    handler(event, context=None)


def test_does_reraise_on_other_send_exception(create_websocket_event):
    demo = app.Chalice('app-name')
    fake_500_error = Exception()
    fake_500_error.response = {'ResponseMetadata': {'HTTPStatusCode': 500}}
    fake_500_error.key = 'foo'
    client = FakeClient(errors=[fake_500_error])
    demo.websocket_api.session = FakeSession(client)

    @demo.on_ws_message()
    def message_handler(event):
        with pytest.raises(Exception) as e:
            demo.websocket_api.send('connection_id', event.body)
        assert e.value.key == 'foo'

    event = create_websocket_event('$default', body='foo bar')
    demo(event, context=None)


def test_cannot_send_message_on_unconfigured_app():
    demo = app.Chalice('app-name')
    demo.websocket_api.session = None

    with pytest.raises(ValueError) as e:
        demo.websocket_api.send('connection_id', 'body')

    assert str(e.value) == (
        'Assign app.websocket_api.session to a boto3 session before '
        'using the WebsocketAPI'
    )


def test_cannot_re_register_websocket_handlers(create_websocket_event):
    demo = app.Chalice('app-name')

    @demo.on_ws_message()
    def message_handler(event):
        pass

    with pytest.raises(ValueError) as e:
        @demo.on_ws_message()
        def message_handler_2(event):
            pass

    assert str(e.value) == (
        "Duplicate websocket handler: 'on_ws_message'. There can only be one "
        "handler for each websocket decorator."
    )

    @demo.on_ws_connect()
    def connect_handler(event):
        pass

    with pytest.raises(ValueError) as e:
        @demo.on_ws_connect()
        def conncet_handler_2(event):
            pass

    assert str(e.value) == (
        "Duplicate websocket handler: 'on_ws_connect'. There can only be one "
        "handler for each websocket decorator."
    )

    @demo.on_ws_disconnect()
    def disconnect_handler(event):
        pass

    with pytest.raises(ValueError) as e:
        @demo.on_ws_disconnect()
        def disconncet_handler_2(event):
            pass

    assert str(e.value) == (
        "Duplicate websocket handler: 'on_ws_disconnect'. There can only be "
        "one handler for each websocket decorator."
    )


def test_can_parse_json_websocket_body(create_websocket_event):
    demo = app.Chalice('app-name')
    client = FakeClient()
    demo.websocket_api.session = FakeSession(client)

    @demo.on_ws_message()
    def message(event):
        assert event.json_body == {'foo': 'bar'}

    event = create_websocket_event('$default', body='{"foo": "bar"}')
    demo(event, context=None)


def test_can_access_websocket_json_body_twice(create_websocket_event):
    demo = app.Chalice('app-name')
    client = FakeClient()
    demo.websocket_api.session = FakeSession(client)

    @demo.on_ws_message()
    def message(event):
        assert event.json_body == {'foo': 'bar'}
        assert event.json_body == {'foo': 'bar'}

    event = create_websocket_event('$default', body='{"foo": "bar"}')
    demo(event, context=None)


def test_does_raise_on_invalid_json_wbsocket_body(create_websocket_event):
    demo = app.Chalice('app-name')
    client = FakeClient()
    demo.websocket_api.session = FakeSession(client)

    @demo.on_ws_message()
    def message(event):
        with pytest.raises(BadRequestError) as e:
            event.json_body
        assert 'Error Parsing JSON' in str(e.value)

    event = create_websocket_event('$default', body='foo bar')
    demo(event, context=None)


class TestMiddleware:
    def test_middleware_basic_api(self):
        demo = app.Chalice('app-name')
        called = []

        @demo.middleware('all')
        def myhandler(event, get_response):
            called.append({'name': 'myhandler', 'bucket': event.bucket})
            return get_response(event)

        @demo.middleware('all')
        def myhandler2(event, get_response):
            called.append({'name': 'myhandler2', 'bucket': event.bucket})
            return get_response(event)

        @demo.on_s3_event('mybucket')
        def handler(event):
            called.append({'name': 'main', 'bucket': event.bucket})
            return {'bucket': event.bucket}

        with Client(demo) as c:
            response = c.lambda_.invoke(
                'handler', c.events.generate_s3_event('mybucket', 'key')
            )
        assert response.payload == {'bucket': 'mybucket'}
        assert called == [
            {'name': 'myhandler', 'bucket': 'mybucket'},
            {'name': 'myhandler2', 'bucket': 'mybucket'},
            {'name': 'main', 'bucket': 'mybucket'},
        ]

    def test_can_access_original_event_and_context_in_http(self):
        demo = app.Chalice('app-name')
        called = []

        @demo.middleware('http')
        def myhandler(event, get_response):
            called.append({'event': event})
            return get_response(event)

        @demo.route('/')
        def index():
            return {'hello': 'world'}

        with Client(demo) as c:
            response = c.http.get('/')
        assert response.json_body == {'hello': 'world'}
        actual_event = called[0]['event']
        assert actual_event.path == '/'
        assert actual_event.lambda_context.function_name == 'api_handler'
        assert actual_event.to_original_event()[
            'requestContext']['resourcePath'] == '/'

    def test_can_short_circuit_response(self):
        demo = app.Chalice('app-name')
        called = []

        @demo.middleware('all')
        def myhandler(event, get_response):
            called.append({'name': 'myhandler', 'bucket': event.bucket})
            return {'short-circuit': True}

        @demo.middleware('all')
        def myhandler2(event, get_response):
            called.append({'name': 'myhandler2', 'bucket': event.bucket})
            return get_response(event)

        @demo.on_s3_event('mybucket')
        def handler(event):
            called.append({'name': 'main', 'bucket': event.bucket})
            return {'bucket': event.bucket}

        with Client(demo) as c:
            response = c.lambda_.invoke(
                'handler', c.events.generate_s3_event('mybucket', 'key')
            )
        assert response.payload == {'short-circuit': True}
        assert called == [
            {'name': 'myhandler', 'bucket': 'mybucket'},
        ]

    def test_can_alter_response(self):
        demo = app.Chalice('app-name')
        called = []

        @demo.middleware('all')
        def myhandler(event, get_response):
            called.append({'name': 'myhandler', 'bucket': event.bucket})
            response = get_response(event)
            response['myhandler'] = True
            return response

        @demo.middleware('all')
        def myhandler2(event, get_response):
            called.append({'name': 'myhandler2', 'bucket': event.bucket})
            response = get_response(event)
            response['myhandler2'] = True
            return response

        @demo.on_s3_event('mybucket')
        def handler(event):
            called.append({'name': 'main', 'bucket': event.bucket})
            return {'bucket': event.bucket}

        with Client(demo) as c:
            response = c.lambda_.invoke(
                'handler', c.events.generate_s3_event('mybucket', 'key')
            )
        assert response.payload == {
            'bucket': 'mybucket',
            'myhandler': True,
            'myhandler2': True,
        }
        assert called == [
            {'name': 'myhandler', 'bucket': 'mybucket'},
            {'name': 'myhandler2', 'bucket': 'mybucket'},
            {'name': 'main', 'bucket': 'mybucket'},
        ]

    def test_can_change_order_of_definitions(self):
        demo = app.Chalice('app-name')
        called = []

        @demo.on_s3_event('mybucket')
        def handler(event):
            called.append({'name': 'main', 'bucket': event.bucket})
            return {'bucket': event.bucket}

        @demo.middleware('all')
        def myhandler(event, get_response):
            called.append({'name': 'myhandler', 'bucket': event.bucket})
            response = get_response(event)
            response['myhandler'] = True
            return response

        @demo.middleware('all')
        def myhandler2(event, get_response):
            called.append({'name': 'myhandler2', 'bucket': event.bucket})
            response = get_response(event)
            response['myhandler2'] = True
            return response

        with Client(demo) as c:
            response = c.lambda_.invoke(
                'handler', c.events.generate_s3_event('mybucket', 'key')
            )
        assert response.payload == {
            'bucket': 'mybucket',
            'myhandler': True,
            'myhandler2': True,
        }
        assert called == [
            {'name': 'myhandler', 'bucket': 'mybucket'},
            {'name': 'myhandler2', 'bucket': 'mybucket'},
            {'name': 'main', 'bucket': 'mybucket'},
        ]

    def test_can_use_middleware_for_pure_lambda(self):
        demo = app.Chalice('app-name')
        called = []

        @demo.middleware('all')
        def mymiddleware(event, get_response):
            called.append({'name': 'mymiddleware', 'event': event.to_dict()})
            return get_response(event)

        @demo.lambda_function()
        def myfunction(event, context):
            called.append({'name': 'myfunction', 'event': event})
            return {'foo': 'bar'}

        with Client(demo) as c:
            response = c.lambda_.invoke(
                'myfunction', {'input-event': True}
            )

        assert response.payload == {'foo': 'bar'}
        assert called == [
            {'name': 'mymiddleware', 'event': {'input-event': True}},
            {'name': 'myfunction', 'event': {'input-event': True}},
        ]

    def test_can_use_for_websocket_handlers(self):
        demo = app.Chalice('app-name')
        called = []

        @demo.middleware('all')
        def mymiddleware(event, get_response):
            called.append({'name': 'mymiddleware', 'event': event.to_dict()})
            return get_response(event)

        @demo.on_ws_message()
        def myfunction(event):
            called.append({'name': 'myfunction', 'event': event.to_dict()})
            return {'foo': 'bar'}

        with Client(demo) as c:
            event = {
                'requestContext': {
                    'domainName': 'example.com',
                    'stage': 'dev',
                    'connectionId': 'abcd',
                    'apiId': 'abcd1234',
                },
                'body': "body"
            }
            response = c.lambda_.invoke('myfunction', event)

        assert response.payload == {'statusCode': 200}
        assert called == [
            {'name': 'mymiddleware', 'event': event},
            {'name': 'myfunction', 'event': event},
        ]

    def test_can_use_rest_api_for_middleware(self):
        demo = app.Chalice('app-name')
        called = []

        @demo.middleware('all')
        def mymiddleware(event, get_response):
            called.append({'name': 'mymiddleware', 'method': event.method})
            response = get_response(event)
            response.status_code = 201
            return response

        @demo.route('/')
        def index():
            called.append({'url': '/'})
            return {'index': True}

        @demo.route('/hello')
        def hello():
            called.append({'url': '/hello'})
            return {'hello': True}

        with Client(demo) as c:
            assert c.http.get('/').json_body == {'index': True}
            response = c.http.get('/hello')
            assert response.json_body == {'hello': True}
            # Verify middleware can alter the response.
            assert response.status_code == 201

        assert called == [
            {'name': 'mymiddleware', 'method': 'GET'},
            {'url': '/'},
            {'name': 'mymiddleware', 'method': 'GET'},
            {'url': '/hello'},
        ]

    def test_error_handler_rest_api_untouched(self):
        demo = app.Chalice('app-name')

        @demo.middleware('all')
        def mymiddleware(event, get_response):
            return get_response(event)

        @demo.route('/error')
        def index():
            raise NotFoundError("resource not found")

        with Client(demo) as c:
            response = c.http.get('/error')
            assert response.status_code == 404
            assert response.json_body == {
                'Code': 'NotFoundError',
                'Message': 'NotFoundError: resource not found'
            }

    def test_unhandled_error_not_caught(self):
        demo = app.Chalice('app-name')

        @demo.middleware('all')
        def mymiddleware(event, get_response):
            try:
                return get_response(event)
            except ChaliceUnhandledError:
                return Response(body={'foo': 'bar'}, status_code=200)

        @demo.route('/error')
        def index():
            raise ChaliceUnhandledError("unhandled")

        with Client(demo) as c:
            response = c.http.get('/error')
            assert response.status_code == 200
            assert response.json_body == {'foo': 'bar'}

    def test_middleware_errors_return_500_still_caught(self):
        demo = app.Chalice('app-name')

        @demo.middleware('all')
        def mymiddleware(event, get_response):
            return get_response(event)

        @demo.route('/error')
        def index():
            raise ChaliceUnhandledError("unhandled")

        with Client(demo) as c:
            # An uncaught ChaliceUnhandledError should still result
            # in the standard error handler processing for REST APIs
            # if the exception propagates out of the middleware stack.
            response = c.http.get('/error')
            assert response.status_code == 500
            assert response.json_body == {
                'Code': 'InternalServerError',
                'Message': 'An internal server error occurred.'
            }

    def test_middleware_errors_result_in_500(self):
        demo = app.Chalice('app-name')

        @demo.middleware('all')
        def mymiddleware(event, get_response):
            raise Exception("Error from middleware.")

        @demo.route('/')
        def index():
            return {}

        with Client(demo) as c:
            response = c.http.get('/')
            assert response.status_code == 500
            assert response.json_body['Code'] == 'InternalServerError'

    def test_can_filter_middleware_registration(self, sample_middleware_app):
        with Client(sample_middleware_app) as c:
            c.http.get('/')
            assert sample_middleware_app.calls == [
                {'type': 'all', 'event': 'Request'},
                {'type': 'http', 'event': 'Request'},
            ]
            sample_middleware_app.calls[:] = []
            c.lambda_.invoke(
                's3_handler', c.events.generate_s3_event('bucket', 'key'))
            assert sample_middleware_app.calls == [
                {'type': 'all', 'event': 'S3Event'},
                {'type': 's3', 'event': 'S3Event'},
            ]
            sample_middleware_app.calls[:] = []
            c.lambda_.invoke(
                'sns_handler', c.events.generate_sns_event('topic', 'message'))
            assert sample_middleware_app.calls == [
                {'type': 'all', 'event': 'SNSEvent'},
                {'type': 'sns', 'event': 'SNSEvent'},
            ]
            sample_middleware_app.calls[:] = []
            c.lambda_.invoke(
                'sqs_handler', c.events.generate_sns_event('queue', 'message'))
            # There is no sqs specific middleware.
            assert sample_middleware_app.calls == [
                {'type': 'all', 'event': 'SQSEvent'},
            ]
            sample_middleware_app.calls[:] = []
            c.lambda_.invoke('lambda_handler', {})
            assert sample_middleware_app.calls == [
                {'type': 'all', 'event': 'LambdaFunctionEvent'},
                {'type': 'pure_lambda', 'event': 'LambdaFunctionEvent'},
            ]
            sample_middleware_app.calls[:] = []
            c.lambda_.invoke('ws_handler', {
                'requestContext': {
                    'domainName': 'example.com',
                    'stage': 'dev',
                    'connectionId': 'abcd',
                    'apiId': 'abcd1234',
                },
                'body': "body"
            })
            assert sample_middleware_app.calls == [
                {'type': 'all', 'event': 'WebsocketEvent'},
                {'type': 'websocket', 'event': 'WebsocketEvent'},
            ]

    def test_can_register_middleware_on_blueprints(self):
        demo = app.Chalice('app-name')
        bp = app.Blueprint('bpmiddleware')
        called = []

        @demo.middleware('all')
        def mymiddleware(event, get_response):
            called.append({'name': 'fromapp', 'bucket': event.bucket})
            return get_response(event)

        @bp.middleware('all')
        def bp_middleware(event, get_response):
            called.append({'name': 'frombp', 'bucket': event.bucket})
            return get_response(event)

        @bp.on_s3_event('mybucket')
        def bp_handler(event):
            called.append({'name': 'bp_handler', 'bucket': event.bucket})
            return {'bucket': event.bucket}

        @bp.route('/')
        def index():
            pass

        @demo.on_s3_event('mybucket')
        def handler(event):
            called.append({'name': 'main', 'bucket': event.bucket})
            return {'bucket': event.bucket}

        demo.register_blueprint(bp)

        with Client(demo) as c:
            # The order is particular here.  When we're invoking the lambda
            # function from the "app" (demo) object, we expect
            # the order to be mymiddleware, bp_middleware because mymiddleware
            # is registered before the .register_blueprint().
            response = c.lambda_.invoke(
                'handler', c.events.generate_s3_event('mybucket', 'key')
            )
            assert response.payload == {'bucket': 'mybucket'}
            assert called == [
                {'name': 'fromapp', 'bucket': 'mybucket'},
                {'name': 'frombp', 'bucket': 'mybucket'},
                {'name': 'main', 'bucket': 'mybucket'},
            ]
            called[:] = []
            response = c.lambda_.invoke(
                'bp_handler', c.events.generate_s3_event('mybucket', 'key')
            )
            assert response.payload == {'bucket': 'mybucket'}
            assert called == [
                {'name': 'fromapp', 'bucket': 'mybucket'},
                {'name': 'frombp', 'bucket': 'mybucket'},
                {'name': 'bp_handler', 'bucket': 'mybucket'},
            ]

    def test_blueprint_gets_middlware_added(self):
        demo = app.Chalice('app-name')
        bp = app.Blueprint('bpmiddleware')
        called = []

        @bp.middleware('all')
        def bp_middleware(event, get_response):
            called.append({'name': 'frombp', 'bucket': 'mybucket'})
            return get_response(event)

        @demo.on_s3_event('mybucket')
        def handler(event):
            called.append({'name': 'main', 'bucket': event.bucket})
            return {'bucket': event.bucket}

        demo.register_blueprint(bp)

        with Client(demo) as c:
            response = c.lambda_.invoke(
                'handler', c.events.generate_s3_event('mybucket', 'key')
            )

        assert response.payload == {'bucket': 'mybucket'}
        assert called == [
            {'name': 'frombp', 'bucket': 'mybucket'},
            {'name': 'main', 'bucket': 'mybucket'},
        ]

    def test_can_register_middleware_without_decorator(self):
        demo = app.Chalice('app-name')
        called = []

        def mymiddleware(event, get_response):
            called.append({'name': 'mymiddleware', 'event': event.to_dict()})
            return get_response(event)

        @demo.lambda_function()
        def myfunction(event, context):
            called.append({'name': 'myfunction', 'event': event})
            return {'foo': 'bar'}

        demo.register_middleware(mymiddleware, 'all')

        with Client(demo) as c:
            response = c.lambda_.invoke(
                'myfunction', {'input-event': True}
            )

        assert response.payload == {'foo': 'bar'}
        assert called == [
            {'name': 'mymiddleware', 'event': {'input-event': True}},
            {'name': 'myfunction', 'event': {'input-event': True}},
        ]

    def test_can_convert_existing_lambda_decorator_to_middleware(self):
        demo = app.Chalice('app-name')
        called = []

        def mydecorator(func):
            def _wrapped(event, context):
                called.append({'name': 'wrapped', 'event': event})
                return func(event, context)
            return _wrapped

        @demo.middleware('all')
        def second_middleware(event, get_response):
            called.append({'name': 'second', 'event': event.to_dict()})
            return get_response(event)

        @demo.lambda_function()
        def myfunction(event, context):
            called.append({'name': 'myfunction', 'event': event})
            return {'foo': 'bar'}

        demo.register_middleware(ConvertToMiddleware(mydecorator))

        with Client(demo) as c:
            response = c.lambda_.invoke(
                'myfunction', {'input-event': True}
            )

        assert response.payload == {'foo': 'bar'}
        assert called == [
            {'name': 'second', 'event': {'input-event': True}},
            {'name': 'wrapped', 'event': {'input-event': True}},
            {'name': 'myfunction', 'event': {'input-event': True}},
        ]
