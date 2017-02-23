import base64
import logging
import json

import pytest
from pytest import fixture
from chalice import app
from chalice import NotFoundError


def create_request_with_content_type(content_type):
    body = '{"json": "body"}'
    return app.Request(
        {}, {'Content-Type': content_type}, {}, 'GET',
        body, {}, {}
    )


def create_event(uri, method, path, content_type='application/json'):
    return {
        'requestContext': {
            'httpMethod': method,
            'resourcePath': uri,
        },
        'headers': {
            'Content-Type': content_type,
        },
        'pathParameters': path,
        'queryStringParameters': {},
        'body': "",
        'stageVariables': {},
    }


def create_event_with_body(body, uri='/', method='POST',
                           content_type='application/json'):
    event = create_event(uri, method, {}, content_type)
    if content_type == 'application/json':
        body = json.dumps(body)
    event['body'] = body
    return event


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


def test_can_parse_route_view_args():
    entry = app.RouteEntry(lambda: {"foo": "bar"}, 'view-name',
                           '/foo/{bar}/baz/{qux}', methods=['GET'])
    assert entry.view_args == ['bar', 'qux']


def test_can_route_single_view():
    demo = app.Chalice('app-name')

    @demo.route('/index')
    def index_view():
        return {}

    assert demo.routes['/index'] == app.RouteEntry(index_view, 'index_view',
                                                   '/index', ['GET'],
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
    assert demo.routes['/index'].view_function == index_view
    assert demo.routes['/other'].view_function == other_view


def test_error_on_unknown_event(sample_app):
    bad_event = {'random': 'event'}
    raw_response = sample_app(bad_event, context=None)
    assert raw_response['statusCode'] == 500
    assert json_response_body(raw_response)['Code'] == 'InternalServerError'


def test_can_route_api_call_to_view_function(sample_app):
    event = create_event('/index', 'GET', {})
    response = sample_app(event, context=None)
    assert_response_body_is(response, {'hello': 'world'})


def test_can_call_to_dict_on_current_request(sample_app):
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


def test_will_pass_captured_params_to_view(sample_app):
    event = create_event('/name/{name}', 'GET', {'name': 'james'})
    response = sample_app(event, context=None)
    response = json_response_body(response)
    assert response == {'provided-name': 'james'}


def test_error_on_unsupported_method(sample_app):
    event = create_event('/name/{name}', 'POST', {'name': 'james'})
    raw_response = sample_app(event, context=None)
    assert raw_response['statusCode'] == 405
    assert json_response_body(raw_response)['Code'] == 'MethodNotAllowedError'


def test_error_on_unsupported_method_gives_feedback_on_method(sample_app):
    method = 'POST'
    event = create_event('/name/{name}', method, {'name': 'james'})
    raw_response = sample_app(event, context=None)
    assert 'POST' in json_response_body(raw_response)['Message']


def test_no_view_function_found(sample_app):
    bad_path = create_event('/noexist', 'GET', {})
    with pytest.raises(app.ChaliceError):
        sample_app(bad_path, context=None)


def test_can_access_raw_body():
    demo = app.Chalice('app-name')

    @demo.route('/index')
    def index_view():
        return {'rawbody': demo.current_request.raw_body}


    event = create_event('/index', 'GET', {})
    event['body'] = '{"hello": "world"}'

    result = demo(event, context=None)
    result = json_response_body(result)
    assert result == {'rawbody': '{"hello": "world"}'}


def test_raw_body_cache_returns_same_result():
    demo = app.Chalice('app-name')

    @demo.route('/index')
    def index_view():
        # The first raw_body decodes base64,
        # the second value should return the cached value.
        # Both should be the same value
        return {'rawbody': demo.current_request.raw_body,
                'rawbody2': demo.current_request.raw_body}


    event = create_event('/index', 'GET', {})
    event['base64-body'] = base64.b64encode('{"hello": "world"}')

    result = demo(event, context=None)
    result = json_response_body(result)
    assert result['rawbody'] == result['rawbody2']


def test_error_on_duplicate_routes():
    demo = app.Chalice('app-name')

    @demo.route('/index', methods=['PUT'])
    def index_view():
        return {'foo': 'bar'}

    with pytest.raises(ValueError):
        @demo.route('/index', methods=['POST'])
        def index_post():
            return {'foo': 'bar'}


def test_json_body_available_with_right_content_type():
    demo = app.Chalice('demo-app')

    @demo.route('/', methods=['POST'])
    def index():
        return demo.current_request.json_body


    event = create_event('/', 'POST', {})
    event['body'] = json.dumps({'foo': 'bar'})

    result = demo(event, context=None)
    result = json_response_body(result)
    assert result == {'foo': 'bar'}


def test_cant_access_json_body_with_wrong_content_type():
    demo = app.Chalice('demo-app')

    @demo.route('/', methods=['POST'], content_types=['application/xml'])
    def index():
        return (demo.current_request.json_body, demo.current_request.raw_body)

    event = create_event('/', 'POST', {}, content_type='application/xml')
    event['body'] = '<Message>hello</Message>'

    response = json_response_body(demo(event, context=None))
    json_body, raw_body = response
    assert json_body is None
    assert raw_body == '<Message>hello</Message>'


def test_json_body_available_on_multiple_content_types():
    demo = app.Chalice('demo-app')

    @demo.route('/', methods=['POST'],
                content_types=['application/xml', 'application/json'])
    def index():
        return (demo.current_request.json_body, demo.current_request.raw_body)

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


def test_json_body_available_with_lowercase_content_type_key():
    demo = app.Chalice('demo-app')

    @demo.route('/', methods=['POST'])
    def index():
        return (demo.current_request.json_body, demo.current_request.raw_body)

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


def test_content_type_validation_raises_error_on_unknown_types():
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


def test_can_return_response_object():
    demo = app.Chalice('app-name')

    @demo.route('/index')
    def index_view():
        return app.Response(status_code=200, body={'foo': 'bar'},
                            headers={'Content-Type': 'application/json'})

    event = create_event('/index', 'GET', {})
    response = demo(event, context=None)
    assert response == {'statusCode': 200, 'body': '{"foo": "bar"}',
                        'headers': {'Content-Type': 'application/json'}}


def test_headers_have_basic_validation():
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


def test_no_content_type_is_still_allowed():
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


def test_route_equality():
    view_function = lambda: {"hello": "world"}
    a = app.RouteEntry(
        view_function,
        view_name='myview', path='/',
        methods=['GET'],
        authorization_type='foo',
        api_key_required=True,
        content_types=['application/json'],
    )
    b = app.RouteEntry(
        view_function,
        view_name='myview', path='/',
        methods=['GET'],
        authorization_type='foo',
        api_key_required=True,
        content_types=['application/json'],
    )
    assert a == b


def test_route_inequality():
    view_function = lambda: {"hello": "world"}
    a = app.RouteEntry(
        view_function,
        view_name='myview', path='/',
        methods=['GET'],
        authorization_type='foo',
        api_key_required=True,
        content_types=['application/json'],
    )
    b = app.RouteEntry(
        view_function,
        view_name='myview', path='/',
        methods=['GET'],
        authorization_type='foo',
        api_key_required=True,
        # Different content types
        content_types=['application/xml'],
    )
    assert not a == b


def test_exceptions_raised_as_chalice_errors(sample_app):

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


def test_original_exception_raised_in_debug_mode(sample_app):
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


def test_chalice_view_errors_propagate_in_non_debug_mode(sample_app):
    @sample_app.route('/notfound')
    def notfound():
        raise NotFoundError("resource not found")

    event = create_event('/notfound', 'GET', {})
    raw_response = sample_app(event, context=None)
    assert raw_response['statusCode'] == 404
    assert json_response_body(raw_response)['Code'] == 'NotFoundError'


def test_chalice_view_errors_propagate_in_debug_mode(sample_app):
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


def test_unknown_kwargs_raise_error(sample_app):
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
