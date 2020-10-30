import re
import json
import decimal
import pytest
import mock
from pytest import fixture
from six import BytesIO
from six.moves.BaseHTTPServer import HTTPServer

from chalice import app
from chalice import local, BadRequestError, CORSConfig
from chalice import Response
from chalice import IAMAuthorizer
from chalice import CognitoUserPoolAuthorizer
from chalice.config import Config
from chalice.local import LambdaContext
from chalice.local import LocalARNBuilder
from chalice.local import LocalGateway
from chalice.local import LocalGatewayAuthorizer
from chalice.local import NotAuthorizedError
from chalice.local import ForbiddenError
from chalice.local import InvalidAuthorizerError
from chalice.local import LocalDevServer


AWS_REQUEST_ID_PATTERN = re.compile(
    '^[0-9a-f]{8}-([0-9a-f]{4}-){3}[0-9a-f]{12}$',
    re.I)


class FakeTimeSource(object):
    def __init__(self, times):
        """Create a fake source of second-precision time.

        :type time: List
        :param time: List of times that the time source should return in the
            order it should return them. These should be in seconds.
        """
        self._times = times

    def time(self):
        """Get the next time.

        This is for mimicing the Clock interface used in local.
        """
        time = self._times.pop(0)
        return time


class ChaliceStubbedHandler(local.ChaliceRequestHandler):
    requestline = ''
    request_version = 'HTTP/1.1'

    def setup(self):
        self.rfile = BytesIO()
        self.wfile = BytesIO()
        self.requestline = ''

    def finish(self):
        pass


class CustomSampleChalice(app.Chalice):
    def custom_method(self):
        return "foo"


@pytest.fixture
def arn_builder():
    return LocalARNBuilder()


@pytest.fixture
def lambda_context_args():
    # LambdaContext has several positional args before the ones that we
    # care about for the timing tests, this gives reasonable defaults for
    # those arguments.
    return ['lambda_name', 256]


@fixture
def custom_sample_app():
    demo = CustomSampleChalice(app_name='custom-demo-app')
    demo.debug = True

    return demo


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

    @demo.route('/custom_cors', methods=['GET', 'PUT'], cors=CORSConfig(
        allow_origin='https://foo.bar',
        allow_headers=['Header-A', 'Header-B'],
        expose_headers=['Header-A', 'Header-B'],
        max_age=600,
        allow_credentials=True
    ))
    def custom_cors():
        return {'cors': True}

    @demo.route('/cors-enabled-for-one-method', methods=['GET'])
    def without_cors():
        return {'ok': True}

    @demo.route('/cors-enabled-for-one-method', methods=['POST'], cors=True)
    def with_cors():
        return {'ok': True}

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

    @demo.route('/query-string-multi')
    def query_string_multi():
        params = demo.current_request.query_params
        keys = {k: params.getlist(k) for k in params}
        return keys

    @demo.route('/custom-response')
    def custom_response():
        return Response(body='text',
                        status_code=200,
                        headers={'Content-Type': 'text/plain'})

    @demo.route('/binary', methods=['POST'],
                content_types=['application/octet-stream'])
    def binary_round_trip():
        return Response(body=demo.current_request.raw_body,
                        status_code=200,
                        headers={'Content-Type': 'application/octet-stream'})

    @demo.route('/multi-value-header')
    def multi_value_header():
        return Response(body={},
                        status_code=200,
                        headers={
                            'Set-Cookie': ['CookieA=ValueA', 'CookieB=ValueB']
                        })

    return demo


@fixture
def demo_app_auth():
    demo = app.Chalice('app-name')

    def _policy(effect, resource, action='execute-api:Invoke'):
        return {
            'context': {},
            'principalId': 'user',
            'policyDocument': {
                'Version': '2012-10-17',
                'Statement': [
                    {
                        'Action': action,
                        'Effect': effect,
                        'Resource': resource,
                    }
                ]
            }
        }

    @demo.authorizer()
    def auth_with_explicit_policy(auth_request):
        token = auth_request.token
        if token == 'allow':
            return _policy(
                effect='Allow', resource=[
                    "arn:aws:execute-api:mars-west-1:123456789012:"
                    "ymy8tbxw7b/api/GET/explicit"])
        else:
            return _policy(
                effect='Deny', resource=[
                    "arn:aws:execute-api:mars-west-1:123456789012:"
                    "ymy8tbxw7b/api/GET/explicit"])

    @demo.authorizer()
    def demo_authorizer_returns_none(auth_request):
        return None

    @demo.authorizer()
    def auth_with_multiple_actions(auth_request):
        return _policy(
            effect='Allow', resource=[
                    "arn:aws:execute-api:mars-west-1:123456789012:"
                    "ymy8tbxw7b/api/GET/multi"],
            action=['execute-api:Invoke', 'execute-api:Other']
        )

    @demo.authorizer()
    def demo_auth(auth_request):
        token = auth_request.token
        if token == 'allow':
            return app.AuthResponse(routes=['/index'], principal_id='user')
        else:
            return app.AuthResponse(routes=[], principal_id='user')

    @demo.authorizer()
    def resource_auth(auth_request):
        token = auth_request.token
        if token == 'allow':
            return app.AuthResponse(routes=['/resource/foobar'],
                                    principal_id='user')
        else:
            return app.AuthResponse(routes=[], principal_id='user')

    @demo.authorizer()
    def all_auth(auth_request):
        token = auth_request.token
        if token == 'allow':
            return app.AuthResponse(routes=['*'], principal_id='user')
        else:
            return app.AuthResponse(routes=[], principal_id='user')

    @demo.authorizer()
    def landing_page_auth(auth_request):
        token = auth_request.token
        if token == 'allow':
            return app.AuthResponse(routes=['/'], principal_id='user')
        else:
            return app.AuthResponse(routes=[], principal_id='user')

    iam_authorizer = IAMAuthorizer()

    cognito_authorizer = CognitoUserPoolAuthorizer('app-name', [])

    @demo.route('/', authorizer=landing_page_auth)
    def landing_view():
        return {}

    @demo.route('/index', authorizer=demo_auth)
    def index_view():
        return {}

    @demo.route('/secret', authorizer=demo_auth)
    def secret_view():
        return {}

    @demo.route('/resource/{name}', authorizer=resource_auth)
    def single_value(name):
        return {'resource': name}

    @demo.route('/secret/{value}', authorizer=all_auth)
    def secret_view_value(value):
        return {'secret': value}

    @demo.route('/explicit', authorizer=auth_with_explicit_policy)
    def explicit():
        return {}

    @demo.route('/multi', authorizer=auth_with_multiple_actions)
    def multi():
        return {}

    @demo.route('/iam', authorizer=iam_authorizer)
    def iam_route():
        return {}

    @demo.route('/cognito', authorizer=cognito_authorizer)
    def cognito_route():
        return {}

    @demo.route('/none', authorizer=demo_authorizer_returns_none)
    def none_auth():
        return {}

    return demo


@fixture
def handler(sample_app):
    config = Config()
    chalice_handler = ChaliceStubbedHandler(
        None, ('127.0.0.1', 2000), None, app_object=sample_app, config=config)
    chalice_handler.sample_app = sample_app
    return chalice_handler


@fixture
def auth_handler(demo_app_auth):
    config = Config()
    chalice_handler = ChaliceStubbedHandler(
        None, ('127.0.0.1', 2000), None, app_object=demo_app_auth,
        config=config)
    chalice_handler.sample_app = demo_app_auth
    return chalice_handler


def _get_raw_body_from_response_stream(handler):
    # This is going to include things like status code and
    # response headers in the raw stream.  We just care about the
    # body for now so we'll split lines.
    raw_response = handler.wfile.getvalue()
    body = raw_response.splitlines()[-1]
    return body


def _get_body_from_response_stream(handler):
    body = _get_raw_body_from_response_stream(handler)
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


def test_uses_http_11(handler):
    set_current_request(handler, method='GET', path='/index')
    handler.do_GET()
    response_lines = handler.wfile.getvalue().splitlines()
    assert b'HTTP/1.1 200 OK' in response_lines


def test_can_route_url_params(handler):
    set_current_request(handler, method='GET', path='/names/james')
    handler.do_GET()
    assert _get_body_from_response_stream(handler) == {
        'provided-name': 'james'}


def test_can_route_put_with_body(handler):
    body = b'{"foo": "bar"}'
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
    assert b'Access-Control-Allow-Origin: *' in response_lines


def test_will_respond_with_custom_cors_enabled(handler):
    headers = {'content-type': 'application/json', 'origin': 'null'}
    set_current_request(handler, method='GET', path='/custom_cors',
                        headers=headers)
    handler.do_GET()
    response = handler.wfile.getvalue().splitlines()
    assert b'HTTP/1.1 200 OK' in response
    assert b'Access-Control-Allow-Origin: https://foo.bar' in response
    assert (b'Access-Control-Allow-Headers: Authorization,Content-Type,'
            b'Header-A,Header-B,X-Amz-Date,X-Amz-Security-Token,'
            b'X-Api-Key') in response
    assert b'Access-Control-Expose-Headers: Header-A,Header-B' in response
    assert b'Access-Control-Max-Age: 600' in response
    assert b'Access-Control-Allow-Credentials: true' in response


def test_will_respond_with_custom_cors_enabled_options(handler):
    headers = {'content-type': 'application/json', 'origin': 'null'}
    set_current_request(handler, method='OPTIONS', path='/custom_cors',
                        headers=headers)
    handler.do_OPTIONS()
    response = handler.wfile.getvalue().decode().splitlines()
    assert 'HTTP/1.1 200 OK' in response
    assert 'Access-Control-Allow-Origin: https://foo.bar' in response
    assert ('Access-Control-Allow-Headers: Authorization,Content-Type,'
            'Header-A,Header-B,X-Amz-Date,X-Amz-Security-Token,'
            'X-Api-Key') in response
    assert 'Access-Control-Expose-Headers: Header-A,Header-B' in response
    assert 'Access-Control-Max-Age: 600' in response
    assert 'Access-Control-Allow-Credentials: true' in response
    assert 'Content-Length: 0' in response

    # Ensure that the Access-Control-Allow-Methods header is sent
    # and that it sends all the correct methods over.
    methods_lines = [line for line in response
                     if line.startswith('Access-Control-Allow-Methods')]
    assert len(methods_lines) == 1
    method_line = methods_lines[0]
    _, methods_header_value = method_line.split(': ')
    methods = methods_header_value.strip().split(',')
    assert ['GET', 'OPTIONS', 'PUT'] == sorted(methods)


def test_can_preflight_request(handler):
    headers = {'content-type': 'application/json', 'origin': 'null'}
    set_current_request(handler, method='OPTIONS', path='/cors',
                        headers=headers)
    handler.do_OPTIONS()
    response_lines = handler.wfile.getvalue().splitlines()
    assert b'Access-Control-Allow-Origin: *' in response_lines


def test_non_preflight_options_request(handler):
    headers = {'content-type': 'application/json', 'origin': 'null'}
    set_current_request(handler, method='OPTIONS', path='/options',
                        headers=headers)
    handler.do_OPTIONS()
    assert _get_body_from_response_stream(handler) == {'options': True}


def test_preflight_request_should_succeed_even_if_cors_disabled(handler):
    headers = {'content-type': 'application/json', 'origin': 'null'}
    set_current_request(handler, method='OPTIONS', path='/index',
                        headers=headers)
    handler.do_OPTIONS()
    response_lines = handler.wfile.getvalue().splitlines()
    assert b'HTTP/1.1 200 OK' in response_lines


def test_preflight_returns_correct_methods_in_access_allow_header(handler):
    headers = {'content-type': 'application/json', 'origin': 'null'}
    set_current_request(handler, method='OPTIONS',
                        path='/cors-enabled-for-one-method',
                        headers=headers)
    handler.do_OPTIONS()
    response_lines = handler.wfile.getvalue().splitlines()
    assert b'HTTP/1.1 200 OK' in response_lines
    assert b'Access-Control-Allow-Methods: POST,OPTIONS' in response_lines


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


def test_can_round_trip_binary(handler):
    body = b'\xFE\xED'
    set_current_request(
        handler, method='POST', path='/binary',
        headers={
            'content-type': 'application/octet-stream',
            'accept': 'application/octet-stream',
            'content-length': len(body)
        }
    )
    handler.rfile.write(body)
    handler.rfile.seek(0)

    handler.do_POST()
    response = _get_raw_body_from_response_stream(handler)
    assert response == body


def test_querystring_is_mapped(handler):
    set_current_request(handler, method='GET', path='/query-string?a=b&c=d')
    handler.do_GET()
    assert _get_body_from_response_stream(handler) == {'a': 'b', 'c': 'd'}


def test_empty_querystring_is_none(handler):
    set_current_request(handler, method='GET', path='/query-string')
    handler.do_GET()
    assert _get_body_from_response_stream(handler) is None


def test_querystring_list_is_mapped(handler):
    set_current_request(
        handler,
        method='GET', path='/query-string-multi?a=b&c=d&a=c&e='
    )
    handler.do_GET()
    expected = {'a': ['b', 'c'], 'c': ['d'], 'e': ['']}
    assert _get_body_from_response_stream(handler) == expected


def test_querystring_undefined_is_mapped_consistent_with_apigateway(handler):
    # API Gateway picks up the last element of duplicate keys in a
    # querystring
    set_current_request(handler, method='GET', path='/query-string?a=b&a=c')
    handler.do_GET()
    assert _get_body_from_response_stream(handler) == {'a': 'c'}


def test_content_type_included_once(handler):
    set_current_request(handler, method='GET', path='/custom-response')
    handler.do_GET()
    value = handler.wfile.getvalue()
    response_lines = value.splitlines()
    content_header_lines = [line for line in response_lines
                            if line.startswith(b'Content-Type')]
    assert len(content_header_lines) == 1


def test_can_deny_unauthed_request(auth_handler):
    set_current_request(auth_handler, method='GET', path='/index')
    auth_handler.do_GET()
    value = auth_handler.wfile.getvalue()
    response_lines = value.splitlines()
    assert b'HTTP/1.1 401 Unauthorized' in response_lines
    assert b'x-amzn-ErrorType: UnauthorizedException' in response_lines
    assert b'Content-Type: application/json' in response_lines
    assert b'{"message":"Unauthorized"}' in response_lines


def test_multi_value_header(handler):
    set_current_request(handler, method='GET', path='/multi-value-header')
    handler.do_GET()
    response = handler.wfile.getvalue().decode().splitlines()
    assert 'Set-Cookie: CookieA=ValueA' in response
    assert 'Set-Cookie: CookieB=ValueB' in response


@pytest.mark.parametrize('actual_url,matched_url', [
    ('/foo', '/foo'),
    ('/foo/', '/foo'),
    ('/foo/bar', '/foo/bar'),
    ('/foo/other', '/foo/{capture}'),
    ('/names/foo', '/names/{capture}'),
    ('/names/bar', '/names/{capture}'),
    ('/names/bar/', '/names/{capture}'),
    ('/names/', None),
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


def test_lambda_event_contains_source_ip():
    converter = local.LambdaEventConverter(
        local.RouteMatcher(['/foo/bar']))
    event = converter.create_lambda_event(
        method='GET',
        path='/foo/bar',
        headers={'content-type': 'application/json'}
    )
    source_ip = event.get('requestContext').get('identity').get('sourceIp')
    assert source_ip == local.LambdaEventConverter.LOCAL_SOURCE_IP


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
            'path': '/foo/other',
            'identity': {
                'sourceIp': local.LambdaEventConverter.LOCAL_SOURCE_IP
            },
        },
        'headers': {'content-type': 'application/json'},
        'pathParameters': {'capture': 'other'},
        'multiValueQueryStringParameters': None,
        'body': None,
        'stageVariables': {},
    }


def test_parse_query_string():
    converter = local.LambdaEventConverter(
        local.RouteMatcher(['/foo/bar', '/foo/{capture}']))
    event = converter.create_lambda_event(
        method='GET',
        path='/foo/other?a=1&b=&c=3',
        headers={'content-type': 'application/json'}
    )
    assert event == {
        'requestContext': {
            'httpMethod': 'GET',
            'resourcePath': '/foo/{capture}',
            'path': '/foo/other',
            'identity': {
                'sourceIp': local.LambdaEventConverter.LOCAL_SOURCE_IP
            },
        },
        'headers': {'content-type': 'application/json'},
        'pathParameters': {'capture': 'other'},
        'multiValueQueryStringParameters': {'a': ['1'], 'b': [''], 'c': ['3']},
        'body': None,
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
            'path': '/foo/other',
            'identity': {
                'sourceIp': local.LambdaEventConverter.LOCAL_SOURCE_IP
            },
        },
        'headers': {'content-type': 'application/json'},
        'pathParameters': {'capture': 'other'},
        'multiValueQueryStringParameters': None,
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
            'path': '/foo/other',
            'identity': {
                'sourceIp': local.LambdaEventConverter.LOCAL_SOURCE_IP
            },
        },
        'headers': {'content-type': 'application/x-www-form-urlencoded'},
        'pathParameters': {'capture': 'other'},
        'multiValueQueryStringParameters': None,
        'body': form_body,
        'stageVariables': {},
    }


def test_can_provide_port_to_local_server(sample_app):
    dev_server = local.create_local_server(sample_app, None, '127.0.0.1',
                                           port=23456)
    assert dev_server.server.server_port == 23456


def test_can_provide_host_to_local_server(sample_app):
    dev_server = local.create_local_server(sample_app, None, host='0.0.0.0',
                                           port=23456)
    assert dev_server.host == '0.0.0.0'


def test_wraps_custom_sample_app_with_local_chalice(custom_sample_app):
    dev_server = local.create_local_server(custom_sample_app, None,
                                           host='0.0.0.0', port=23456)
    assert isinstance(dev_server.app_object, local.LocalChalice)
    assert isinstance(dev_server.app_object, custom_sample_app.__class__)
    assert dev_server.app_object.custom_method() == 'foo'


class TestLambdaContext(object):
    def test_can_get_remaining_time_once(self, lambda_context_args):
        time_source = FakeTimeSource([0, 5])
        context = LambdaContext(*lambda_context_args, max_runtime_ms=10000,
                                time_source=time_source)
        time_remaining = context.get_remaining_time_in_millis()
        assert time_remaining == 5000

    def test_can_get_remaining_time_multiple(self, lambda_context_args):
        time_source = FakeTimeSource([0, 3, 7, 9])
        context = LambdaContext(*lambda_context_args, max_runtime_ms=10000,
                                time_source=time_source)

        time_remaining = context.get_remaining_time_in_millis()
        assert time_remaining == 7000
        time_remaining = context.get_remaining_time_in_millis()
        assert time_remaining == 3000
        time_remaining = context.get_remaining_time_in_millis()
        assert time_remaining == 1000

    def test_does_populate_aws_request_id_with_valid_uuid(self,
                                                          lambda_context_args):
        context = LambdaContext(*lambda_context_args)
        assert AWS_REQUEST_ID_PATTERN.match(context.aws_request_id)

    def test_does_set_version_to_latest(self, lambda_context_args):
        context = LambdaContext(*lambda_context_args)
        assert context.function_version == '$LATEST'


class TestLocalGateway(object):
    def test_can_invoke_function(self):
        demo = app.Chalice('app-name')

        @demo.route('/')
        def index_view():
            return {'foo': 'bar'}

        gateway = LocalGateway(demo, Config())
        response = gateway.handle_request('GET', '/', {}, '')
        body = json.loads(response['body'])
        assert body['foo'] == 'bar'

    def test_does_populate_context(self):
        demo = app.Chalice('app-name')

        @demo.route('/context')
        def context_view():
            context = demo.lambda_context
            return {
                'name': context.function_name,
                'memory': context.memory_limit_in_mb,
                'version': context.function_version,
                'timeout': context.get_remaining_time_in_millis(),
                'request_id': context.aws_request_id,
            }

        disk_config = {
            'lambda_timeout': 10,
            'lambda_memory_size': 256,
        }
        config = Config(chalice_stage='api', config_from_disk=disk_config)
        gateway = LocalGateway(demo, config)
        response = gateway.handle_request('GET', '/context', {}, '')
        body = json.loads(response['body'])
        assert body['name'] == 'api_handler'
        assert body['memory'] == 256
        assert body['version'] == '$LATEST'
        assert body['timeout'] > 10
        assert body['timeout'] <= 10000
        assert AWS_REQUEST_ID_PATTERN.match(body['request_id'])

    def test_can_validate_route_with_variables(self, demo_app_auth):
        gateway = LocalGateway(demo_app_auth, Config())
        response = gateway.handle_request(
            'GET', '/secret/foobar', {'Authorization': 'allow'}, '')
        json_body = json.loads(response['body'])
        assert json_body['secret'] == 'foobar'

    def test_can_allow_route_with_variables(self, demo_app_auth):
        gateway = LocalGateway(demo_app_auth, Config())
        response = gateway.handle_request(
            'GET', '/resource/foobar', {'Authorization': 'allow'}, '')
        json_body = json.loads(response['body'])
        assert json_body['resource'] == 'foobar'

    def test_does_send_500_when_authorizer_returns_none(self, demo_app_auth):
        gateway = LocalGateway(demo_app_auth, Config())
        with pytest.raises(InvalidAuthorizerError):
            gateway.handle_request(
                'GET', '/none', {'Authorization': 'foobarbaz'}, '')

    def test_can_deny_route_with_variables(self, demo_app_auth):
        gateway = LocalGateway(demo_app_auth, Config())
        with pytest.raises(ForbiddenError):
            gateway.handle_request(
                'GET', '/resource/foobarbaz', {'Authorization': 'allow'}, '')

    def test_does_deny_unauthed_request(self, demo_app_auth):
        gateway = LocalGateway(demo_app_auth, Config())
        with pytest.raises(ForbiddenError) as ei:
            gateway.handle_request(
                'GET', '/index', {'Authorization': 'deny'}, '')
        exception_body = str(ei.value.body)
        assert ('{"Message": '
                '"User is not authorized to '
                'access this resource"}') in exception_body

    def test_does_throw_unauthorized_when_no_auth_token_present_on_valid_route(
            self, demo_app_auth):
        gateway = LocalGateway(demo_app_auth, Config())
        with pytest.raises(NotAuthorizedError) as ei:
            gateway.handle_request(
                'GET', '/index', {}, '')
        exception_body = str(ei.value.body)
        assert '{"message":"Unauthorized"}' in exception_body

    def test_does_deny_with_forbidden_when_route_not_found(
            self, demo_app_auth):
        gateway = LocalGateway(demo_app_auth, Config())
        with pytest.raises(ForbiddenError) as ei:
            gateway.handle_request('GET', '/badindex', {}, '')
        exception_body = str(ei.value.body)
        assert 'Missing Authentication Token' in exception_body

    def test_does_deny_with_forbidden_when_auth_token_present(
            self, demo_app_auth):
        gateway = LocalGateway(demo_app_auth, Config())
        with pytest.raises(ForbiddenError) as ei:
            gateway.handle_request('GET', '/badindex',
                                   {'Authorization': 'foobar'}, '')
        # The message should be a more complicated error message to do with
        # signing the request. It always ends with the Authorization token
        # that we passed up, so we can check for that.
        exception_body = str(ei.value.body)
        assert 'Authorization=foobar' in exception_body


class TestLocalBuiltinAuthorizers(object):
    def test_can_authorize_empty_path(self, lambda_context_args,
                                      demo_app_auth, create_event):
        # Ensures that / routes work since that is a special case in the
        # API Gateway arn generation where an extra / is appended to the end
        # of the arn.
        authorizer = LocalGatewayAuthorizer(demo_app_auth)
        path = '/'
        event = create_event(path, 'GET', {})
        event['headers']['authorization'] = 'allow'
        context = LambdaContext(*lambda_context_args)
        event, context = authorizer.authorize(path, event, context)
        assert event['requestContext']['authorizer']['principalId'] == 'user'

    def test_can_call_method_without_auth(self, lambda_context_args,
                                          create_event):
        demo = app.Chalice('app-name')

        @demo.route('/index')
        def index_view():
            return {}

        path = '/index'
        authorizer = LocalGatewayAuthorizer(demo)
        original_event = create_event(path, 'GET', {})
        original_context = LambdaContext(*lambda_context_args)
        event, context = authorizer.authorize(
            path, original_event, original_context)
        # Assert that when the authorizer.authorize is called and there is no
        # authorizer defined for a particular route that it is a noop.
        assert original_event == event
        assert original_context == context

    def test_does_raise_not_authorized_error(self, demo_app_auth,
                                             lambda_context_args,
                                             create_event):
        authorizer = LocalGatewayAuthorizer(demo_app_auth)
        path = '/index'
        event = create_event(path, 'GET', {})
        context = LambdaContext(*lambda_context_args)
        with pytest.raises(NotAuthorizedError):
            authorizer.authorize(path, event, context)

    def test_does_authorize_valid_requests(self, demo_app_auth,
                                           lambda_context_args, create_event):
        authorizer = LocalGatewayAuthorizer(demo_app_auth)
        path = '/index'
        event = create_event(path, 'GET', {})
        event['headers']['authorization'] = 'allow'
        context = LambdaContext(*lambda_context_args)
        event, context = authorizer.authorize(path, event, context)
        assert event['requestContext']['authorizer']['principalId'] == 'user'

    def test_does_authorize_unsupported_authorizer(self, demo_app_auth,
                                                   lambda_context_args,
                                                   create_event):
        authorizer = LocalGatewayAuthorizer(demo_app_auth)
        path = '/iam'
        event = create_event(path, 'GET', {})
        context = LambdaContext(*lambda_context_args)
        with pytest.warns(None) as recorded_warnings:
            new_event, new_context = authorizer.authorize(path, event, context)
        assert event == new_event
        assert context == new_context
        assert len(recorded_warnings) == 1
        warning = recorded_warnings[0]
        assert issubclass(warning.category, UserWarning)
        assert ('IAMAuthorizer is not a supported in local '
                'mode. All requests made against a route will be authorized'
                ' to allow local testing.') in str(warning.message)

    def test_cannot_access_view_without_permission(self, demo_app_auth,
                                                   lambda_context_args,
                                                   create_event):
        authorizer = LocalGatewayAuthorizer(demo_app_auth)
        path = '/secret'
        event = create_event(path, 'GET', {})
        event['headers']['authorization'] = 'allow'
        context = LambdaContext(*lambda_context_args)
        with pytest.raises(ForbiddenError):
            authorizer.authorize(path, event, context)

    def test_can_understand_explicit_auth_policy(self, demo_app_auth,
                                                 lambda_context_args,
                                                 create_event):
        authorizer = LocalGatewayAuthorizer(demo_app_auth)
        path = '/explicit'
        event = create_event(path, 'GET', {})
        event['headers']['authorization'] = 'allow'
        context = LambdaContext(*lambda_context_args)
        event, context = authorizer.authorize(path, event, context)
        assert event['requestContext']['authorizer']['principalId'] == 'user'

    def test_can_understand_explicit_deny_policy(self, demo_app_auth,
                                                 lambda_context_args,
                                                 create_event):
        # Our auto-generated policies from the AuthResponse object do not
        # contain any Deny clauses, however we also allow the user to return
        # a dictionary that is transated into a policy, so we have to
        # account for the ability for a user to set an explicit deny policy.
        # It should behave exactly as not getting permission added with an
        # allow.
        authorizer = LocalGatewayAuthorizer(demo_app_auth)
        path = '/explicit'
        event = create_event(path, 'GET', {})
        context = LambdaContext(*lambda_context_args)
        with pytest.raises(NotAuthorizedError):
            authorizer.authorize(path, event, context)

    def test_can_understand_multi_actions(self, demo_app_auth,
                                          lambda_context_args,
                                          create_event):
        authorizer = LocalGatewayAuthorizer(demo_app_auth)
        path = '/multi'
        event = create_event(path, 'GET', {})
        event['headers']['authorization'] = 'allow'
        context = LambdaContext(*lambda_context_args)
        event, context = authorizer.authorize(path, event, context)
        assert event['requestContext']['authorizer']['principalId'] == 'user'

    def test_can_understand_cognito_token(self, lambda_context_args,
                                          demo_app_auth, create_event):
        # Ensures that / routes work since that is a special case in the
        # API Gateway arn generation where an extra / is appended to the end
        # of the arn.
        authorizer = LocalGatewayAuthorizer(demo_app_auth)
        path = '/cognito'
        event = create_event(path, 'GET', {})
        event["headers"]["authorization"] = "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJhYWFhYWFhYS1iYmJiLWNjY2MtZGRkZC1lZWVlZWVlZWVlZWUiLCJhdWQiOiJ4eHh4eHh4eHh4eHhleGFtcGxlIiwiZW1haWxfdmVyaWZpZWQiOnRydWUsInRva2VuX3VzZSI6ImlkIiwiYXV0aF90aW1lIjoxNTAwMDA5NDAwLCJpc3MiOiJodHRwczovL2NvZ25pdG8taWRwLnVzLWVhc3QtMS5hbWF6b25hd3MuY29tL3VzLWVhc3QtMV9leGFtcGxlIiwiY29nbml0bzp1c2VybmFtZSI6ImphbmVkb2UiLCJleHAiOjE1ODQ3MjM2MTYsImdpdmVuX25hbWUiOiJKYW5lIiwiaWF0IjoxNTAwMDA5NDAwLCJlbWFpbCI6ImphbmVkb2VAZXhhbXBsZS5jb20iLCJqdGkiOiJkN2UxMTMzYS0xZTNhLTQyMzEtYWU3Yi0yOGQ4NWVlMGIxNGQifQ.p35Yj9KJD5RbfPWGL08IJHgson8BhdGLPQqUOiF0-KM"  # noqa
        context = LambdaContext(*lambda_context_args)
        event, context = authorizer.authorize(path, event, context)
        principal_id = event['requestContext']['authorizer']['principalId']
        assert principal_id == 'janedoe'

    def test_does_authorize_unsupported_cognito_token(self,
                                                      lambda_context_args,
                                                      demo_app_auth,
                                                      create_event):
        authorizer = LocalGatewayAuthorizer(demo_app_auth)
        path = '/cognito'
        event = create_event(path, 'GET', {})
        event["headers"]["authorization"] = "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJhYWFhYWFhYS1iYmJiLWNjY2MtZGRkZC1lZWVlZWVlZWVlZWUiLCJhdWQiOiJ4eHh4eHh4eHh4eHhleGFtcGxlIiwiZW1haWxfdmVyaWZpZWQiOnRydWUsInRva2VuX3VzZSI6ImlkIiwiYXV0aF90aW1lIjoxNTAwMDA5NDAwLCJpc3MiOiJodHRwczovL2NvZ25pdG8taWRwLnVzLWVhc3QtMS5hbWF6b25hd3MuY29tL3VzLWVhc3QtMV9leGFtcGxlIiwiZXhwIjoxNTg0NzIzNjE2LCJnaXZlbl9uYW1lIjoiSmFuZSIsImlhdCI6MTUwMDAwOTQwMCwiZW1haWwiOiJqYW5lZG9lQGV4YW1wbGUuY29tIiwianRpIjoiZDdlMTEzM2EtMWUzYS00MjMxLWFlN2ItMjhkODVlZTBiMTRkIn0.SN5n-A3kxboNYg0sGIOipVUksCdn6xRJmAK9kSZof10"  # noqa
        context = LambdaContext(*lambda_context_args)
        with pytest.warns(None) as recorded_warnings:
            new_event, new_context = authorizer.authorize(path, event, context)
        assert event == new_event
        assert context == new_context
        assert len(recorded_warnings) == 1
        warning = recorded_warnings[0]
        assert issubclass(warning.category, UserWarning)
        assert ('CognitoUserPoolAuthorizer for machine-to-machine '
                'communicaiton is not supported in local mode. All requests '
                'made against a route will be authorized to allow local '
                'testing.') in str(warning.message)


class TestArnBuilder(object):
    def test_can_create_basic_arn(self, arn_builder):
        arn = ('arn:aws:execute-api:mars-west-1:123456789012:ymy8tbxw7b'
               '/api/GET/resource')
        built_arn = arn_builder.build_arn('GET', '/resource')
        assert arn == built_arn

    def test_can_create_root_arn(self, arn_builder):
        arn = ('arn:aws:execute-api:mars-west-1:123456789012:ymy8tbxw7b'
               '/api/GET//')
        built_arn = arn_builder.build_arn('GET', '/')
        assert arn == built_arn

    def test_can_create_multi_part_arn(self, arn_builder):
        arn = ('arn:aws:execute-api:mars-west-1:123456789012:ymy8tbxw7b'
               '/api/GET/path/to/resource')
        built_arn = arn_builder.build_arn('GET', '/path/to/resource')
        assert arn == built_arn

    def test_can_create_glob_method_arn(self, arn_builder):
        arn = ('arn:aws:execute-api:mars-west-1:123456789012:ymy8tbxw7b'
               '/api/*/resource')
        built_arn = arn_builder.build_arn('*', '/resource')
        assert arn == built_arn

    def test_build_arn_with_query_params(self, arn_builder):
        arn = ('arn:aws:execute-api:mars-west-1:123456789012:ymy8tbxw7b/api/'
               '*/resource')
        built_arn = arn_builder.build_arn('*', '/resource?foo=bar')
        assert arn == built_arn


@pytest.mark.parametrize('arn,pattern', [
    ('mars-west-2:123456789012:ymy8tbxw7b/api/GET/foo',
     'mars-west-2:123456789012:ymy8tbxw7b/api/GET/foo'
     ),
    ('mars-west-1:123456789012:ymy8tbxw7b/api/GET/foobar',
     'mars-west-1:123456789012:ymy8tbxw7b/api/GET/*'
     ),
    ('mars-west-1:123456789012:ymy8tbxw7b/api/PUT/foobar',
     'mars-west-1:123456789012:ymy8tbxw7b/api/???/foobar'
     ),
    ('mars-west-1:123456789012:ymy8tbxw7b/api/GET/foobar',
     'mars-west-1:123456789012:ymy8tbxw7b/api/???/*'
     ),
    ('mars-west-1:123456789012:ymy8tbxw7b/api/GET/foobar',
     'mars-west-1:123456789012:*/api/GET/*'
     ),
    ('mars-west-2:123456789012:ymy8tbxw7b/api/GET/foobar',
     '*'
     ),
    ('mars-west-2:123456789012:ymy8tbxw7b/api/GET/foo.bar',
     'mars-west-2:123456789012:ymy8tbxw7b/*/GET/*')
])
def test_can_allow_route_arns(arn, pattern):
    prefix = 'arn:aws:execute-api:'
    full_arn = '%s%s' % (prefix, arn)
    full_pattern = '%s%s' % (prefix, pattern)
    matcher = local.ARNMatcher(full_arn)
    does_match = matcher.does_any_resource_match([full_pattern])
    assert does_match is True


@pytest.mark.parametrize('arn,pattern', [
    ('mars-west-1:123456789012:ymy8tbxw7b/api/GET/foobar',
     'mars-west-1:123456789012:ymy8tbxw7b/api/PUT/*'
     ),
    ('mars-west-1:123456789012:ymy8tbxw7b/api/GET/foobar',
     'mars-west-1:123456789012:ymy8tbxw7b/api/??/foobar'
     ),
    ('mars-west-1:123456789012:ymy8tbxw7b/api/GET/foobar',
     'mars-west-2:123456789012:ymy8tbxw7b/api/???/*'
     ),
    ('mars-west-2:123456789012:ymy8tbxw7b/api/GET/foobar',
     'mars-west-2:123456789012:ymy8tbxw7b/*/GET/foo...')
])
def test_can_deny_route_arns(arn, pattern):
    prefix = 'arn:aws:execute-api:'
    full_arn = '%s%s' % (prefix, arn)
    full_pattern = '%s%s' % (prefix, pattern)
    matcher = local.ARNMatcher(full_arn)
    does_match = matcher.does_any_resource_match([full_pattern])
    assert does_match is False


@pytest.mark.parametrize('arn,patterns', [
    ('mars-west-1:123456789012:ymy8tbxw7b/api/GET/foobar',
     [
         'mars-west-1:123456789012:ymy8tbxw7b/api/PUT/*',
         'mars-west-1:123456789012:ymy8tbxw7b/api/GET/foobar'
     ]),
    ('mars-west-1:123456789012:ymy8tbxw7b/api/GET/foobar',
     [
         'mars-west-1:123456789012:ymy8tbxw7b/api/GET/foobar',
         'mars-west-1:123456789012:ymy8tbxw7b/api/PUT/*'
     ]),
    ('mars-west-1:123456789012:ymy8tbxw7b/api/GET/foobar',
     [
         'mars-west-1:123456789012:ymy8tbxw7b/api/PUT/foobar',
         '*'
     ])
])
def test_can_allow_multiple_resource_arns(arn, patterns):
    prefix = 'arn:aws:execute-api:'
    full_arn = '%s%s' % (prefix, arn)
    full_patterns = ['%s%s' % (prefix, pattern) for pattern in patterns]
    matcher = local.ARNMatcher(full_arn)
    does_match = matcher.does_any_resource_match(full_patterns)
    assert does_match is True


@pytest.mark.parametrize('arn,patterns', [
    ('mars-west-1:123456789012:ymy8tbxw7b/api/GET/foobar',
     [
         'mars-west-1:123456789012:ymy8tbxw7b/api/POST/*',
         'mars-west-1:123456789012:ymy8tbxw7b/api/PUT/foobar'
     ]),
    ('mars-west-1:123456789012:ymy8tbxw7b/api/GET/foobar',
     [
         'mars-west-2:123456789012:ymy8tbxw7b/api/GET/foobar',
         'mars-west-2:123456789012:ymy8tbxw7b/api/*/*'
     ])
])
def test_can_deny_multiple_resource_arns(arn, patterns):
    prefix = 'arn:aws:execute-api:'
    full_arn = '%s%s' % (prefix, arn)
    full_patterns = ['%s%s' % (prefix, pattern) for pattern in patterns]
    matcher = local.ARNMatcher(full_arn)
    does_match = matcher.does_any_resource_match(full_patterns)
    assert does_match is False


class TestLocalDevServer(object):
    def test_can_delegate_to_server(self, sample_app):
        http_server = mock.Mock(spec=HTTPServer)
        dev_server = LocalDevServer(
            sample_app, Config(), '0.0.0.0', 8000,
            server_cls=lambda *args: http_server,
        )

        dev_server.handle_single_request()
        http_server.handle_request.assert_called_with()

        dev_server.serve_forever()
        http_server.serve_forever.assert_called_with()

    def test_host_and_port_forwarded_to_server_creation(self, sample_app):
        provided_args = []

        def args_recorder(*args):
            provided_args[:] = list(args)

        LocalDevServer(
            sample_app, Config(), '0.0.0.0', 8000,
            server_cls=args_recorder,
        )

        assert provided_args[0] == ('0.0.0.0', 8000)

    def test_does_use_daemon_threads(self, sample_app):
        server = LocalDevServer(
            sample_app, Config(), '0.0.0.0', 8000
        )

        assert server.server.daemon_threads
