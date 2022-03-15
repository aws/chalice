"""Dev server used for running a chalice app locally.

This is intended only for local development purposes.

"""
from __future__ import print_function
import re
import threading
import time
import uuid
import base64
import functools
import warnings
from collections import namedtuple
import json

from six.moves.BaseHTTPServer import HTTPServer
from six.moves.BaseHTTPServer import BaseHTTPRequestHandler
from six.moves.socketserver import ThreadingMixIn
from typing import (
    List,
    Any,
    Dict,
    Tuple,
    Callable,
    Optional,
    Union,
)  # noqa

from chalice.app import Chalice  # noqa
from chalice.app import CORSConfig  # noqa
from chalice.app import ChaliceAuthorizer  # noqa
from chalice.app import CognitoUserPoolAuthorizer  # noqa
from chalice.app import RouteEntry  # noqa
from chalice.app import Request  # noqa
from chalice.app import AuthResponse  # noqa
from chalice.app import BuiltinAuthConfig  # noqa
from chalice.config import Config  # noqa

from chalice.compat import urlparse, parse_qs


MatchResult = namedtuple('MatchResult', ['route', 'captured', 'query_params'])
EventType = Dict[str, Any]
ContextType = Dict[str, Any]
HeaderType = Dict[str, Any]
ResponseType = Dict[str, Any]
HandlerCls = Callable[..., 'ChaliceRequestHandler']
ServerCls = Callable[..., 'HTTPServer']


class Clock(object):
    def time(self):
        # type: () -> float
        return time.time()


def create_local_server(app_obj, config, host, port):
    # type: (Chalice, Config, str, int) -> LocalDevServer
    CustomLocalChalice.__bases__ = (LocalChalice, app_obj.__class__)
    app_obj.__class__ = CustomLocalChalice
    return LocalDevServer(app_obj, config, host, port)


class LocalARNBuilder(object):
    ARN_FORMAT = ('arn:aws:execute-api:{region}:{account_id}'
                  ':{api_id}/{stage}/{method}/{resource_path}')
    LOCAL_REGION = 'mars-west-1'
    LOCAL_ACCOUNT_ID = '123456789012'
    LOCAL_API_ID = 'ymy8tbxw7b'
    LOCAL_STAGE = 'api'

    def build_arn(self, method, path):
        # type: (str, str) -> str
        # In API Gateway the method and URI are separated by a / so typically
        # the uri portion omits the leading /. In the case where the entire
        # url is just '/' API Gateway adds a / to the end so that the arn end
        # with a '//'.
        if path != '/':
            path = path[1:]
        path = path.split('?')[0]
        return self.ARN_FORMAT.format(
            region=self.LOCAL_REGION,
            account_id=self.LOCAL_ACCOUNT_ID,
            api_id=self.LOCAL_API_ID,
            stage=self.LOCAL_STAGE,
            method=method,
            resource_path=path
        )


class ARNMatcher(object):
    def __init__(self, target_arn):
        # type: (str) -> None
        self._arn = target_arn

    def _resource_match(self, resource):
        # type: (str) -> bool
        # Arn matching supports two special case characetrs that are not
        # escapable. * represents a glob which translates to a non-greedy
        # match of any number of characters. ? which is any single character.
        # These are easy to translate to a regex using .*? and . respectivly.
        escaped_resource = re.escape(resource)
        resource_regex = escaped_resource.replace(r'\?', '.').replace(
            r'\*', '.*?')
        resource_regex = '^%s$' % resource_regex
        return re.match(resource_regex, self._arn) is not None

    def does_any_resource_match(self, resources):
        # type: (List[str]) -> bool
        for resource in resources:
            if self._resource_match(resource):
                return True
        return False


class RouteMatcher(object):
    def __init__(self, route_urls):
        # type: (List[str]) -> None
        # Sorting the route_urls ensures we always check
        # the concrete routes for a prefix before the
        # variable/capture parts of the route, e.g
        # '/foo/bar' before '/foo/{capture}'
        self.route_urls = sorted(route_urls)

    def match_route(self, url):
        # type: (str) -> MatchResult
        """Match the url against known routes.

        This method takes a concrete route "/foo/bar", and
        matches it against a set of routes.  These routes can
        use param substitution corresponding to API gateway patterns.
        For example::

            match_route('/foo/bar') -> '/foo/{name}'

        """
        # Otherwise we need to check for param substitution
        parsed_url = urlparse(url)
        query_params = parse_qs(parsed_url.query, keep_blank_values=True)
        path = parsed_url.path
        # API Gateway removes the trailing slash if the route is not the root
        # path. We do the same here so our route matching works the same way.
        if path != '/' and path.endswith('/'):
            path = path[:-1]
        parts = path.split('/')
        captured = {}
        for route_url in self.route_urls:
            url_parts = route_url.split('/')
            if len(parts) == len(url_parts):
                for i, j in zip(parts, url_parts):
                    if j.startswith('{') and j.endswith('}'):
                        captured[j[1:-1]] = i
                        continue
                    if i != j:
                        break
                else:
                    return MatchResult(route_url, captured, query_params)
        raise ValueError("No matching route found for: %s" % url)


class LambdaEventConverter(object):

    LOCAL_SOURCE_IP = '127.0.0.1'

    """Convert an HTTP request to an event dict used by lambda."""
    def __init__(self, route_matcher, binary_types=None):
        # type: (RouteMatcher, List[str]) -> None
        self._route_matcher = route_matcher
        if binary_types is None:
            binary_types = []
        self._binary_types = binary_types

    def _is_binary(self, headers):
        # type: (Dict[str,Any]) -> bool
        return headers.get('content-type', '') in self._binary_types

    def create_lambda_event(self, method, path, headers, body=None):
        # type: (str, str, Dict[str, str], bytes) -> EventType
        view_route = self._route_matcher.match_route(path)
        event = {
            'requestContext': {
                'httpMethod': method,
                'resourcePath': view_route.route,
                'identity': {
                    'sourceIp': self.LOCAL_SOURCE_IP
                },
                'path': path.split('?')[0],
            },
            'headers': {k.lower(): v for k, v in headers.items()},
            'pathParameters': view_route.captured,
            'stageVariables': {},
        }
        if view_route.query_params:
            event['multiValueQueryStringParameters'] = view_route.query_params
        else:
            # If no query parameters are provided, API gateway maps
            # this to None so we're doing this for parity.
            event['multiValueQueryStringParameters'] = None
        if self._is_binary(headers) and body is not None:
            event['body'] = base64.b64encode(body).decode('ascii')
            event['isBase64Encoded'] = True
        else:
            event['body'] = body
        return event


class LocalGatewayException(Exception):
    CODE = 0

    def __init__(self, headers, body=None):
        # type: (HeaderType, Optional[bytes]) -> None
        self.headers = headers
        self.body = body


class InvalidAuthorizerError(LocalGatewayException):
    CODE = 500


class ForbiddenError(LocalGatewayException):
    CODE = 403


class NotAuthorizedError(LocalGatewayException):
    CODE = 401


class LambdaContext(object):
    def __init__(self, function_name, memory_size,
                 max_runtime_ms=3000, time_source=None):
        # type: (str, int, int, Optional[Clock]) -> None
        if time_source is None:
            time_source = Clock()
        self._time_source = time_source
        self._start_time = self._current_time_millis()
        self._max_runtime = max_runtime_ms

        # Below are properties that are found on the real LambdaContext passed
        # by lambda and their associated documentation.

        # Name of the Lambda function that is executing.
        self.function_name = function_name

        # The Lambda function version that is executing. If an alias is used
        # to invoke the function, then function_version will be the version
        # the alias points to.
        # Chalice local obviously does not support versioning so it will always
        # be set to $LATEST.
        self.function_version = '$LATEST'

        # The ARN used to invoke this function. It can be function ARN or
        # alias ARN. An unqualified ARN executes the $LATEST version and
        # aliases execute the function version it is pointing to.
        self.invoked_function_arn = ''

        # Memory limit, in MB, you configured for the Lambda function. You set
        # the memory limit at the time you create a Lambda function and you
        # can change it later.
        self.memory_limit_in_mb = memory_size

        # AWS request ID associated with the request. This is the ID returned
        # to the client that called the invoke method.
        self.aws_request_id = str(uuid.uuid4())

        # The name of the CloudWatch log group where you can find logs written
        # by your Lambda function.
        self.log_group_name = ''

        # The name of the CloudWatch log stream where you can find logs
        # written by your Lambda function. The log stream may or may not
        # change for each invocation of the Lambda function.
        #
        # The value is null if your Lambda function is unable to create a log
        # stream, which can happen if the execution role that grants necessary
        # permissions to the Lambda function does not include permissions for
        # the CloudWatch Logs actions.
        self.log_stream_name = ''

        # The last two attributes have the following comment in the
        # documentation:
        # Information about the client application and device when invoked
        # through the AWS Mobile SDK, it can be null.
        # Chalice local doens't need to set these since they are specifically
        # for the mobile SDK.
        self.identity = None
        self.client_context = None

    def _current_time_millis(self):
        # type: () -> float
        return self._time_source.time() * 1000

    def get_remaining_time_in_millis(self):
        # type: () -> float
        runtime = self._current_time_millis() - self._start_time
        return self._max_runtime - runtime


LocalAuthPair = Tuple[EventType, LambdaContext]


class LocalGatewayAuthorizer(object):
    """A class for running user defined authorizers in local mode."""
    def __init__(self, app_object):
        # type: (Chalice) -> None
        self._app_object = app_object
        self._arn_builder = LocalARNBuilder()

    def authorize(self, raw_path, lambda_event, lambda_context):
        # type: (str, EventType, LambdaContext) -> LocalAuthPair
        method = lambda_event['requestContext']['httpMethod']
        route_entry = self._route_for_event(lambda_event)
        if not route_entry:
            return lambda_event, lambda_context
        authorizer = route_entry.authorizer
        if not authorizer:
            return lambda_event, lambda_context
        # If authorizer is Cognito then try to parse the JWT and simulate an
        # APIGateway validated request
        if isinstance(authorizer, CognitoUserPoolAuthorizer):
            if "headers" in lambda_event\
                    and "authorization" in lambda_event["headers"]:
                token = lambda_event["headers"]["authorization"]
                claims = self._decode_jwt_payload(token)

                try:
                    cognito_username = claims["cognito:username"]
                except KeyError:
                    # If a key error is raised when trying to get the cognito
                    # username then it is a machine-to-machine communication.
                    # This kind of cognito authorization flow is not
                    # supported in local mode. We can ignore it here to allow
                    # users to test their code local with a different cognito
                    # authorization flow.
                    warnings.warn(
                        '%s for machine-to-machine communicaiton is not '
                        'supported in local mode. All requests made against '
                        'a route will be authorized to allow local testing.'
                        % authorizer.__class__.__name__
                    )
                    return lambda_event, lambda_context

                auth_result = {"context": {"claims": claims},
                               "principalId": cognito_username}
                lambda_event = self._update_lambda_event(lambda_event,
                                                         auth_result)
        if not isinstance(authorizer, ChaliceAuthorizer):
            # Currently the only supported local authorizer is the
            # BuiltinAuthConfig type. Anything else we will err on the side of
            # allowing local testing by simply admiting the request. Otherwise
            # there is no way for users to test their code in local mode.
            warnings.warn(
                '%s is not a supported in local mode. All requests made '
                'against a route will be authorized to allow local testing.'
                % authorizer.__class__.__name__
            )
            return lambda_event, lambda_context
        arn = self._arn_builder.build_arn(method, raw_path)
        auth_event = self._prepare_authorizer_event(arn, lambda_event,
                                                    lambda_context)
        auth_result = authorizer(auth_event, lambda_context)
        if auth_result is None:
            raise InvalidAuthorizerError(
                {'x-amzn-RequestId': lambda_context.aws_request_id,
                 'x-amzn-ErrorType': 'AuthorizerConfigurationException'},
                b'{"message":null}'
            )
        authed = self._check_can_invoke_view_function(arn, auth_result)
        if authed:
            lambda_event = self._update_lambda_event(lambda_event, auth_result)
        else:
            raise ForbiddenError(
                {'x-amzn-RequestId': lambda_context.aws_request_id,
                 'x-amzn-ErrorType': 'AccessDeniedException'},
                (b'{"Message": '
                 b'"User is not authorized to access this resource"}'))
        return lambda_event, lambda_context

    def _check_can_invoke_view_function(self, arn, auth_result):
        # type: (str, ResponseType) -> bool
        policy = auth_result.get('policyDocument', {})
        statements = policy.get('Statement', [])
        allow_resource_statements = []
        for statement in statements:
            if statement.get('Effect') == 'Allow' and \
                    (statement.get('Action') == 'execute-api:Invoke' or
                     'execute-api:Invoke' in statement.get('Action')):
                for resource in statement.get('Resource'):
                    allow_resource_statements.append(resource)

        arn_matcher = ARNMatcher(arn)
        return arn_matcher.does_any_resource_match(allow_resource_statements)

    def _route_for_event(self, lambda_event):
        # type: (EventType) -> Optional[RouteEntry]
        # Authorizer had to be made into an Any type since mypy couldn't
        # detect that app.ChaliceAuthorizer was callable.
        resource_path = lambda_event.get(
            'requestContext', {}).get('resourcePath')
        http_method = lambda_event['requestContext']['httpMethod']
        try:
            route_entry = self._app_object.routes[resource_path][http_method]
        except KeyError:
            # If a key error is raised when trying to get the route entry
            # then this route does not support this method. A method error
            # will be raised by the chalice handler method. We can ignore it
            # here by returning no authorizer to avoid duplicating the logic.
            return None
        return route_entry

    def _update_lambda_event(self, lambda_event, auth_result):
        # type: (EventType, ResponseType) -> EventType
        auth_context = auth_result['context']
        auth_context.update({
            'principalId': auth_result['principalId']
        })
        lambda_event['requestContext']['authorizer'] = auth_context
        return lambda_event

    def _prepare_authorizer_event(self, arn, lambda_event, lambda_context):
        # type: (str, EventType, LambdaContext) -> EventType
        """Translate event for an authorizer input."""
        authorizer_event = lambda_event.copy()
        authorizer_event['type'] = 'TOKEN'
        try:
            authorizer_event['authorizationToken'] = authorizer_event.get(
                'headers', {})['authorization']
        except KeyError:
            raise NotAuthorizedError(
                {'x-amzn-RequestId': lambda_context.aws_request_id,
                 'x-amzn-ErrorType': 'UnauthorizedException'},
                b'{"message":"Unauthorized"}')
        authorizer_event['methodArn'] = arn
        return authorizer_event

    def _decode_jwt_payload(self, jwt):
        # type: (str) -> Dict
        payload_segment = jwt.split(".", 2)[1]
        payload = base64.urlsafe_b64decode(self._base64_pad(payload_segment))
        return json.loads(payload)

    def _base64_pad(self, value):
        # type: (str) -> str
        rem = len(value) % 4
        if rem > 0:
            value += "=" * (4 - rem)
        return value


class LocalGateway(object):
    """A class for faking the behavior of API Gateway."""

    MAX_LAMBDA_EXECUTION_TIME = 900

    def __init__(self, app_object, config):
        # type: (Chalice, Config) -> None
        self._app_object = app_object
        self._config = config
        self.event_converter = LambdaEventConverter(
            RouteMatcher(list(app_object.routes)),
            self._app_object.api.binary_types
        )
        self._authorizer = LocalGatewayAuthorizer(app_object)

    def _generate_lambda_context(self):
        # type: () -> LambdaContext
        if self._config.lambda_timeout is None:
            timeout = self.MAX_LAMBDA_EXECUTION_TIME * 1000
        else:
            timeout = self._config.lambda_timeout * 1000
        return LambdaContext(
            function_name=self._config.function_name,
            memory_size=self._config.lambda_memory_size,
            max_runtime_ms=timeout
        )

    def _generate_lambda_event(self, method, path, headers, body):
        # type: (str, str, HeaderType, Optional[bytes]) -> EventType
        lambda_event = self.event_converter.create_lambda_event(
            method=method, path=path, headers=headers,
            body=body,
        )
        return lambda_event

    def _has_user_defined_options_method(self, lambda_event):
        # type: (EventType) -> bool
        route_key = lambda_event['requestContext']['resourcePath']
        return 'OPTIONS' in self._app_object.routes[route_key]

    def handle_request(self, method, path, headers, body):
        # type: (str, str, HeaderType, Optional[bytes]) -> ResponseType
        lambda_context = self._generate_lambda_context()
        try:
            lambda_event = self._generate_lambda_event(
                method, path, headers, body)
        except ValueError:
            # API Gateway will return a different error on route not found
            # depending on whether or not we have an authorization token in our
            # request. Since we do not do that check until we actually find
            # the authorizer that we will call we do not have that information
            # available at this point. Instead we just check to see if that
            # header is present and change our response if it is. This will
            # need to be refactored later if we decide to more closely mirror
            # how API Gateway does their auth and routing.
            error_headers = {'x-amzn-RequestId': lambda_context.aws_request_id,
                             'x-amzn-ErrorType': 'UnauthorizedException'}
            auth_header = headers.get('authorization')
            if auth_header is None:
                auth_header = headers.get('Authorization')
            if auth_header is not None:
                raise ForbiddenError(
                    error_headers,
                    (b'{"message": "Authorization header requires '
                     b'\'Credential\''
                     b' parameter. Authorization header requires \'Signature\''
                     b' parameter. Authorization header requires '
                     b'\'SignedHeaders\' parameter. Authorization header '
                     b'requires existence of either a \'X-Amz-Date\' or a'
                     b' \'Date\' header. Authorization=%s"}'
                     % auth_header.encode('ascii')))
            raise ForbiddenError(
                error_headers,
                b'{"message": "Missing Authentication Token"}')

        # This can either be because the user's provided an OPTIONS method
        # *or* this is a preflight request, which chalice automatically
        # responds to without invoking a user defined route.
        if method == 'OPTIONS' and \
           not self._has_user_defined_options_method(lambda_event):
            # No options route was defined for this path. API Gateway should
            # automatically generate our CORS headers.
            options_headers = self._autogen_options_headers(lambda_event)
            return {
                'statusCode': 200,
                'headers': options_headers,
                'multiValueHeaders': {},
                'body': None
            }
        # The authorizer call will be a noop if there is no authorizer method
        # defined for route. Otherwise it will raise a ForbiddenError
        # which will be caught by the handler that called this and a 403 or
        # 401 will be sent back over the wire.
        lambda_event, lambda_context = self._authorizer.authorize(
            path, lambda_event, lambda_context)
        response = self._app_object(lambda_event, lambda_context)
        return response

    def _autogen_options_headers(self, lambda_event):
        # type:(EventType) -> HeaderType
        route_key = lambda_event['requestContext']['resourcePath']
        route_dict = self._app_object.routes[route_key]
        route_methods = [method for method in route_dict.keys()
                         if route_dict[method].cors is not None]

        # If there are no views with CORS enabled
        # then OPTIONS is the only allowed method.
        if not route_methods:
            return {'Access-Control-Allow-Methods': 'OPTIONS'}

        # Chalice ensures that routes with multiple views have the same
        # CORS configuration, so if any view has a CORS Config we can use
        # that config since they will all be the same.
        cors_config = route_dict[route_methods[0]].cors
        cors_headers = cors_config.get_access_control_headers()

        # We need to add OPTIONS since it is not a part of the CORSConfig
        # object. APIGateway handles this entirely based on the API definition.
        # So our local version needs to add this manually to our set of allowed
        # headers.
        route_methods.append('OPTIONS')

        # The Access-Control-Allow-Methods header is not added by the
        # CORSConfig object it is added to the API Gateway route during
        # deployment, so we need to manually add those headers here.
        cors_headers.update({
            'Access-Control-Allow-Methods': '%s' % ','.join(route_methods)
        })
        return cors_headers


class ChaliceRequestHandler(BaseHTTPRequestHandler):
    """A class for mapping raw HTTP events to and from LocalGateway."""
    protocol_version = 'HTTP/1.1'

    def __init__(self, request, client_address, server, app_object, config):
        # type: (bytes, Tuple[str, int], HTTPServer, Chalice, Config) -> None
        self.local_gateway = LocalGateway(app_object, config)
        BaseHTTPRequestHandler.__init__(
            self, request, client_address, server)  # type: ignore

    def _parse_payload(self):
        # type: () -> Tuple[HeaderType, Optional[bytes]]
        body = None
        content_length = int(self.headers.get('content-length', '0'))
        if content_length > 0:
            body = self.rfile.read(content_length)
        converted_headers = dict(self.headers)
        return converted_headers, body

    def _generic_handle(self):
        # type: () -> None
        headers, body = self._parse_payload()
        try:
            response = self.local_gateway.handle_request(
                method=self.command,
                path=self.path,
                headers=headers,
                body=body
            )
            status_code = response['statusCode']
            headers = response['headers'].copy()
            headers.update(response['multiValueHeaders'])
            response = self._handle_binary(response)
            body = response['body']
            self._send_http_response(status_code, headers, body)
        except LocalGatewayException as e:
            self._send_error_response(e)

    def _handle_binary(self, response):
        # type: (Dict[str,Any]) -> Dict[str,Any]
        if response.get('isBase64Encoded'):
            body = base64.b64decode(response['body'])
            response['body'] = body
        return response

    def _send_error_response(self, error):
        # type: (LocalGatewayException) -> None
        code = error.CODE
        headers = error.headers
        body = error.body
        self._send_http_response(code, headers, body)

    def _send_http_response(self, code, headers, body):
        # type: (int, HeaderType, Optional[Union[str,bytes]]) -> None
        if body is None:
            self._send_http_response_no_body(code, headers)
        else:
            self._send_http_response_with_body(code, headers, body)

    def _send_http_response_with_body(self, code, headers, body):
        # type: (int, HeaderType, Union[str,bytes]) -> None
        self.send_response(code)
        if not isinstance(body, bytes):
            body = body.encode('utf-8')
        self.send_header('Content-Length', str(len(body)))
        content_type = headers.pop(
            'Content-Type', 'application/json')
        self.send_header('Content-Type', content_type)
        self._send_headers(headers)
        self.wfile.write(body)

    do_GET = do_PUT = do_POST = do_HEAD = do_DELETE = do_PATCH = do_OPTIONS = \
        _generic_handle

    def _send_http_response_no_body(self, code, headers):
        # type: (int, HeaderType) -> None
        headers['Content-Length'] = '0'
        self.send_response(code)
        self._send_headers(headers)

    def _send_headers(self, headers):
        # type: (HeaderType) -> None
        for header_name, header_value in headers.items():
            if isinstance(header_value, list):
                for value in header_value:
                    self.send_header(header_name, value)
            else:
                self.send_header(header_name, header_value)
        self.end_headers()


class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    """Threading mixin to better support browsers.

    When a browser sends a GET request to Chalice it keeps the connection open
    for reuse. In the single threaded model this causes Chalice local to become
    unresponsive to all clients other than that browser socket. Even sending a
    header requesting that the client close the connection is not good enough,
    the browswer will simply open another one and sit on it.
    """

    daemon_threads = True


class LocalDevServer(object):
    def __init__(self, app_object, config, host, port,
                 handler_cls=ChaliceRequestHandler,
                 server_cls=ThreadedHTTPServer):
        # type: (Chalice, Config, str, int, HandlerCls, ServerCls) -> None
        self.app_object = app_object
        self.host = host
        self.port = port
        self._wrapped_handler = functools.partial(
            handler_cls, app_object=app_object, config=config)
        self.server = server_cls((host, port), self._wrapped_handler)

    def handle_single_request(self):
        # type: () -> None
        self.server.handle_request()

    def serve_forever(self):
        # type: () -> None
        print("Serving on http://%s:%s" % (self.host, self.port))
        self.server.serve_forever()

    def shutdown(self):
        # type: () -> None
        # This must be called from another thread of else it
        # will deadlock.
        self.server.shutdown()


class HTTPServerThread(threading.Thread):
    """Thread that manages starting/stopping local HTTP server.

    This is a small wrapper around a normal threading.Thread except
    that it adds shutdown capability of the HTTP server, which is
    not part of the normal threading.Thread interface.

    """
    def __init__(self, server_factory):
        # type: (Callable[[], LocalDevServer]) -> None
        threading.Thread.__init__(self)
        self._server_factory = server_factory
        self._server = None  # type: Optional[LocalDevServer]
        self.daemon = True

    def run(self):
        # type: () -> None
        self._server = self._server_factory()
        self._server.serve_forever()

    def shutdown(self):
        # type: () -> None
        if self._server is not None:
            self._server.shutdown()


class LocalChalice(Chalice):

    _THREAD_LOCAL = threading.local()

    # This is a known mypy bug where you can't override instance
    # variables with properties.  So this should be type safe, which
    # is why we're adding the type: ignore comments here.
    # See: https://github.com/python/mypy/issues/4125

    @property  # type: ignore
    def current_request(self):  # type: ignore
        # type: () -> Request
        return self._THREAD_LOCAL.current_request

    @current_request.setter
    def current_request(self, value):  # type: ignore
        # type: (Request) -> None
        self._THREAD_LOCAL.current_request = value


class CustomLocalChalice(LocalChalice):
    pass
