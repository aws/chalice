import pytest
from pytest import fixture
from chalice import app


def create_event(uri, method, path):
    return {
        'context': {
            'http-method': method,
            'resource-path': uri,
        },
        'params': {
            'header': {},
            'path': path,
            'querystring': {},
        },
        'body-json': {},
        'stage-variables': {},
    }


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
                                                   '/index', 'GET')


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
