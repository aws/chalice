import base64
import json

import pytest
from pytest import fixture
from chalice import app
from chalice import NotFoundError


def create_event(uri, method, path, content_type='application/json'):
    return {
        'context': {
            'http-method': method,
            'resource-path': uri,
        },
        'params': {
            'header': {
                'Content-Type': content_type,
            },
            'path': path,
            'querystring': {},
        },
        'body-json': {},
        'base64-body': "",
        'stage-variables': {},
    }


def create_event_with_body(body, uri='/', method='POST',
                           content_type='application/json'):
    event = create_event(uri, method, {}, content_type)
    event['body-json'] = body
    if content_type == 'application/json':
        event['base64-body'] = base64.b64encode(json.dumps(body))
    else:
        event['base64-body'] = base64.b64encode(body)
    return event


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
    with pytest.raises(app.ChaliceError):
        sample_app(bad_event, context=None)


def test_can_route_api_call_to_view_function(sample_app):
    event = create_event('/index', 'GET', {})
    response = sample_app(event, context=None)
    assert response == {'hello': 'world'}


def test_can_call_to_dict_on_current_request(sample_app):
    @sample_app.route('/todict')
    def todict():
        return sample_app.current_request.to_dict()
    event = create_event('/todict', 'GET', {})
    response = sample_app(event, context=None)
    assert isinstance(response, dict)
    # The dict can change over time so we'll just pick
    # out a few keys as a basic sanity test.
    assert response['method'] == 'GET'
    assert response['json_body'] == {}
    # We also want to verify that to_dict() is always
    # JSON serializable so we check we can roundtrip
    # the data to/from JSON.
    assert isinstance(json.loads(json.dumps(response)), dict)


def test_will_pass_captured_params_to_view(sample_app):
    event = create_event('/name/{name}', 'GET', {'name': 'james'})
    response = sample_app(event, context=None)
    assert response == {'provided-name': 'james'}


def test_error_on_unsupported_method(sample_app):
    event = create_event('/name/{name}', 'POST', {'name': 'james'})
    with pytest.raises(app.ChaliceError):
        sample_app(event, context=None)


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
    event['base64-body'] = base64.b64encode('{"hello": "world"}')

    result = demo(event, context=None)
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
    event['body-json'] = {'foo': 'bar'}

    result = demo(event, context=None)
    assert result == event['body-json']


def test_cant_access_json_body_with_wrong_content_type():
    demo = app.Chalice('demo-app')

    @demo.route('/', methods=['POST'], content_types=['application/xml'])
    def index():
        return (demo.current_request.json_body, demo.current_request.raw_body)

    event = create_event('/', 'POST', {}, content_type='application/xml')
    event['body-json'] = '<Message>hello</Message>'
    event['base64-body'] = base64.b64encode('<Message>hello</Message>')

    json_body, raw_body = demo(event, context=None)
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

    json_body, raw_body = demo(event, context=None)
    assert json_body is None
    assert raw_body == '<Message>hello</Message>'

    # Now if we create an event with JSON, we should be able
    # to access .json_body as well.
    event = create_event_with_body({'foo': 'bar'},
                                   content_type='application/json')
    json_body, raw_body = demo(event, context=None)
    assert json_body == {'foo': 'bar'}
    assert raw_body == '{"foo": "bar"}'


def test_json_body_available_with_lowercase_content_type_key():
    demo = app.Chalice('demo-app')

    @demo.route('/', methods=['POST'])
    def index():
        return (demo.current_request.json_body, demo.current_request.raw_body)

    event = create_event_with_body({'foo': 'bar'})
    del event['params']['header']['Content-Type']
    event['params']['header']['content-type'] = 'application/json'

    json_body, raw_body = demo(event, context=None)
    assert json_body == {'foo': 'bar'}
    assert raw_body == '{"foo": "bar"}'


def test_content_types_must_be_lists():
    demo = app.Chalice('app-name')

    with pytest.raises(ValueError):
        @demo.route('/index', content_types='application/not-a-list')
        def index_post():
            return {'foo': 'bar'}


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
    with pytest.raises(app.ChaliceViewError):
        sample_app(event, context=None)


def test_original_exception_raised_in_debug_mode(sample_app):
    sample_app.debug = True

    @sample_app.route('/error')
    def raise_error():
        raise ValueError("You will see this error")

    event = create_event('/error', 'GET', {})
    with pytest.raises(ValueError) as e:
        sample_app(event, context=None)
    # In debug mode, we let the original exception propagate.
    # This includes the original type as well as the message.
    assert str(e.value) == 'You will see this error'


def test_chalice_view_errors_propagate_in_non_debug_mode(sample_app):
    @sample_app.route('/notfound')
    def notfound():
        raise NotFoundError("resource not found")

    event = create_event('/notfound', 'GET', {})
    with pytest.raises(NotFoundError):
        sample_app(event, context=None)


def test_chalice_view_errors_propagate_in_debug_mode(sample_app):
    @sample_app.route('/notfound')
    def notfound():
        raise NotFoundError("resource not found")

    sample_app.debug = True
    event = create_event('/notfound', 'GET', {})
    with pytest.raises(NotFoundError):
        sample_app(event, context=None)


def test_case_insensitive_mapping():
    mapping = app.CaseInsensitiveMapping({'HEADER': 'Value'})

    assert mapping['hEAdEr']
    assert mapping.get('hEAdEr')
    assert 'hEAdEr' in mapping
    assert repr({'header': 'Value'}) in repr(mapping)
