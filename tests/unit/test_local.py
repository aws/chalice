from chalice import local, BadRequestError
import json
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

    @demo.route('/badrequest')
    def badrequest():
        raise BadRequestError('bad-request')

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


def test_can_convert_request_handler_to_lambda_event(handler):
    handler.command = 'GET'
    handler.path = '/index'
    handler.headers = {'content-type': 'application/json'}
    handler.do_GET()

    body = _get_body_from_response_stream(handler)
    assert body == {'hello': 'world'}


def test_can_route_url_params(handler):
    handler.command = 'GET'
    handler.path = '/names/james'
    handler.headers = {'content-type': 'application/json'}

    handler.do_GET()
    body = _get_body_from_response_stream(handler)
    assert body == {'provided-name': 'james'}


def test_can_route_put_with_body(handler):
    handler.command = 'PUT'
    handler.path = '/put'
    body = '{"foo": "bar"}'
    handler.headers = {'content-type': 'application/json',
                       'content-length': len(body)}
    handler.rfile.write(body)
    handler.rfile.seek(0)

    handler.do_PUT()
    response_body = _get_body_from_response_stream(handler)
    assert response_body == {'body': {'foo': 'bar'}}


def test_will_respond_with_cors_enabled(handler):
    handler.command = 'GET'
    handler.path = '/cors'
    handler.headers = {'content-type': 'application/json', 'origin': 'null'}
    handler.do_GET()
    response_lines = handler.wfile.getvalue().splitlines()
    assert 'Access-Control-Allow-Origin: *' in response_lines


def test_can_preflight_request(handler):
    handler.command = 'OPTIONS'
    handler.path = '/cors'
    handler.headers = {'content-type': 'application/json', 'origin': 'null'}
    handler.do_OPTIONS()
    response_lines = handler.wfile.getvalue().splitlines()
    assert 'Access-Control-Allow-Origin: *' in response_lines


def test_non_preflight_options_request(handler):
    handler.command = 'OPTIONS'
    handler.path = '/options'
    handler.headers = {'content-type': 'application/json', 'origin': 'null'}
    handler.do_OPTIONS()
    body = _get_body_from_response_stream(handler)
    assert body == {'options': True}


def test_errors_converted_to_json_response(handler):
    handler.command = 'GET'
    handler.path = '/badrequest'
    handler.headers = {'content-type': 'application/json'}

    handler.do_GET()
    body = _get_body_from_response_stream(handler)
    assert body == {'Code': 'BadRequestError',
                    'Message': 'BadRequestError: bad-request'}


def test_unsupported_methods_raise_error(handler):
    handler.command = 'POST'
    handler.path = '/index'
    handler.headers = {'content-type': 'application/json'}
    handler.do_POST()

    body = _get_body_from_response_stream(handler)
    assert body == {
        'Code': 'MethodNotAllowedError',
        'Message': 'MethodNotAllowedError: Unsupported method: POST'
    }


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
        'context': {
            'http-method': 'GET',
            'resource-path': '/foo/{capture}',
        },
        'claims': {},
        'params': {
            'header': {'content-type': 'application/json'},
            'path': {'capture': 'other'},
            'querystring': {},
        },
        'body-json': {},
        'base64-body': json.dumps({}).encode("base64"),
        'stage-variables': {},
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
        'claims': {},
        'context': {
            'http-method': 'PUT',
            'resource-path': '/foo/{capture}',
        },
        'params': {
            'header': {'content-type': 'application/json'},
            'path': {'capture': 'other'},
            'querystring': {},
        },
        'body-json': {'foo': 'bar'},
        'base64-body': json.dumps({'foo': 'bar'}).encode("base64"),
        'stage-variables': {},
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
        'claims': {},
        'context': {
            'http-method': 'POST',
            'resource-path': '/foo/{capture}',
        },
        'params': {
            'header': {'content-type': 'application/x-www-form-urlencoded'},
            'path': {'capture': 'other'},
            'querystring': {},
        },
        'body-json': {},
        'base64-body': form_body.encode('base64'),
        'stage-variables': {},
    }
