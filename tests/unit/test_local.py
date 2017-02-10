from chalice import local, BadRequestError
import json
import decimal
import pytest
from pytest import fixture
from StringIO import StringIO

from chalice import app


class ChaliceStubbedHandler(local.ChaliceRequestHandler):
    requestline = ''
    request_version = 'HTTP/1.1'

    def setup(self):
        self.rfile = StringIO()
        self.wfile = StringIO()
        self.requestline = ''

    def finish(self):
        pass


@fixture
def sample_app():
    demo = app.Chalice('demo-app')
    demo.debug = True

    @demo.route('/index', methods=['GET'])
    def index():
        return {'hello': 'world'}

    @demo.route('/names/{name}', methods=['GET'])
    def name(name):
        return {'provided-name': name}

    @demo.route('/put', methods=['PUT'])
    def put():
        return {'body': demo.current_request.json_body}

    @demo.route('/cors', methods=['GET', 'PUT'], cors=True)
    def cors():
        return {'cors': True}

    @demo.route('/options', methods=['OPTIONS'])
    def options():
        return {'options': True}

    @demo.route('/delete', methods=['DELETE'])
    def delete():
        return {'delete': True}

    @demo.route('/patch', methods=['PATCH'])
    def patch():
        return {'patch': True}

    @demo.route('/badrequest')
    def badrequest():
        raise BadRequestError('bad-request')

    @demo.route('/decimals')
    def decimals():
        return decimal.Decimal('100')

    @demo.route('/query-string')
    def query_string():
        return demo.current_request.query_params

    return demo


@fixture
def handler(sample_app):
    chalice_handler = ChaliceStubbedHandler(None, ('127.0.0.1', 2000), None,
                                            app_object=sample_app)
    chalice_handler.sample_app = sample_app
    return chalice_handler


def _get_body_from_response_stream(handler):
    # This is going to include things like status code and
    # response headers in the raw stream.  We just care about the
    # body for now so we'll split lines.
    raw_response = handler.wfile.getvalue()
    body = raw_response.splitlines()[-1]
    return json.loads(body)


def set_current_request(handler, method, path, headers=None):
    if headers is None:
        headers = {'content-type': 'application/json'}
    handler.command = method
    handler.path = path
    handler.headers = headers


def test_can_convert_request_handler_to_lambda_event(handler):
    set_current_request(handler, method='GET', path='/index')
    handler.do_GET()
    assert _get_body_from_response_stream(handler) == {'hello': 'world'}


def test_can_route_url_params(handler):
    set_current_request(handler, method='GET', path='/names/james')
    handler.do_GET()
    assert _get_body_from_response_stream(handler) == {
        'provided-name': 'james'}


def test_can_route_put_with_body(handler):
    body = '{"foo": "bar"}'
    headers = {'content-type': 'application/json',
               'content-length': len(body)}
    set_current_request(handler, method='PUT', path='/put',
                        headers=headers)
    handler.rfile.write(body)
    handler.rfile.seek(0)

    handler.do_PUT()
    assert _get_body_from_response_stream(handler) == {
        'body': {'foo': 'bar'}}


def test_will_respond_with_cors_enabled(handler):
    headers = {'content-type': 'application/json', 'origin': 'null'}
    set_current_request(handler, method='GET', path='/cors', headers=headers)
    handler.do_GET()
    response_lines = handler.wfile.getvalue().splitlines()
    assert 'Access-Control-Allow-Origin: *' in response_lines


def test_can_preflight_request(handler):
    headers = {'content-type': 'application/json', 'origin': 'null'}
    set_current_request(handler, method='OPTIONS', path='/cors',
                        headers=headers)
    handler.do_OPTIONS()
    response_lines = handler.wfile.getvalue().splitlines()
    assert 'Access-Control-Allow-Origin: *' in response_lines


def test_non_preflight_options_request(handler):
    headers = {'content-type': 'application/json', 'origin': 'null'}
    set_current_request(handler, method='OPTIONS', path='/options',
                        headers=headers)
    handler.do_OPTIONS()
    assert _get_body_from_response_stream(handler) == {'options': True}


def test_errors_converted_to_json_response(handler):
    set_current_request(handler, method='GET', path='/badrequest')
    handler.do_GET()
    assert _get_body_from_response_stream(handler) == {
        'Code': 'BadRequestError',
        'Message': 'BadRequestError: bad-request'
    }


def test_can_support_delete_method(handler):
    set_current_request(handler, method='DELETE', path='/delete')
    handler.do_DELETE()
    assert _get_body_from_response_stream(handler) == {'delete': True}


def test_can_support_patch_method(handler):
    set_current_request(handler, method='PATCH', path='/patch')
    handler.do_PATCH()
    assert _get_body_from_response_stream(handler) == {'patch': True}

def test_can_support_decimals(handler):
    set_current_request(handler, method='GET', path='/decimals')
    handler.do_PATCH()
    assert _get_body_from_response_stream(handler) == 100


def test_unsupported_methods_raise_error(handler):
    set_current_request(handler, method='POST', path='/index')
    handler.do_POST()
    assert _get_body_from_response_stream(handler) == {
        'Code': 'MethodNotAllowedError',
        'Message': 'Unsupported method: POST'
    }


def test_querystring_is_mapped(handler):
    set_current_request(handler, method='GET', path='/query-string?a=b&c=d')
    handler.do_GET()
    assert _get_body_from_response_stream(handler) == {'a': 'b', 'c': 'd'}


@pytest.mark.parametrize('actual_url,matched_url', [
    ('/foo', '/foo'),
    ('/foo/bar', '/foo/bar'),
    ('/foo/other', '/foo/{capture}'),
    ('/names/foo', '/names/{capture}'),
    ('/names/bar', '/names/{capture}'),
    ('/nomatch', None),
    ('/names/bar/wrong', None),
    ('/a/z/c', '/a/{capture}/c'),
    ('/a/b/c', '/a/b/c'),
])
def test_can_match_exact_route(actual_url, matched_url):
    matcher = local.RouteMatcher([
        '/foo', '/foo/{capture}', '/foo/bar',
        '/names/{capture}',
        '/a/{capture}/c', '/a/b/c'
    ])
    if matched_url is not None:
        assert matcher.match_route(actual_url).route == matched_url
    else:
        with pytest.raises(ValueError):
            matcher.match_route(actual_url)


def test_can_create_lambda_event():
    converter = local.LambdaEventConverter(
        local.RouteMatcher(['/foo/bar', '/foo/{capture}']))
    event = converter.create_lambda_event(
        method='GET',
        path='/foo/other',
        headers={'content-type': 'application/json'}
    )
    assert event == {
        'requestContext': {
            'httpMethod': 'GET',
            'resourcePath': '/foo/{capture}',
        },
        'headers': {'content-type': 'application/json'},
        'pathParameters': {'capture': 'other'},
        'queryStringParameters': {},
        'body': '{}',
        'stageVariables': {},
    }


def test_can_create_lambda_event_for_put_request():
    converter = local.LambdaEventConverter(
        local.RouteMatcher(['/foo/bar', '/foo/{capture}']))
    event = converter.create_lambda_event(
        method='PUT',
        path='/foo/other',
        headers={'content-type': 'application/json'},
        body='{"foo": "bar"}',
    )
    assert event == {
        'requestContext': {
            'httpMethod': 'PUT',
            'resourcePath': '/foo/{capture}',
        },
        'headers': {'content-type': 'application/json'},
        'pathParameters': {'capture': 'other'},
        'queryStringParameters': {},
        'body': '{"foo": "bar"}',
        'stageVariables': {},
    }


def test_can_create_lambda_event_for_post_with_formencoded_body():
    converter = local.LambdaEventConverter(
        local.RouteMatcher(['/foo/bar', '/foo/{capture}']))
    form_body = 'foo=bar&baz=qux'
    event = converter.create_lambda_event(
        method='POST',
        path='/foo/other',
        headers={'content-type': 'application/x-www-form-urlencoded'},
        body=form_body,
    )
    assert event == {
        'requestContext': {
            'httpMethod': 'POST',
            'resourcePath': '/foo/{capture}',
        },
        'headers': {'content-type': 'application/x-www-form-urlencoded'},
        'pathParameters': {'capture': 'other'},
        'queryStringParameters': {},
        'body': form_body,
        'stageVariables': {},
    }


def test_can_provide_port_to_local_server(sample_app):
    dev_server = local.create_local_server(sample_app, port=23456)
    assert dev_server.server.server_port == 23456
