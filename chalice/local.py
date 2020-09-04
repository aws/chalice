"""Dev server used for running a chalice app locally.

This is intended only for local development purposes.

"""
# pylint: disable=too-many-lines
from __future__ import print_function
import contextlib
import hashlib
import logging
import re
import threading
import time
import uuid
import base64
import functools
import warnings
import socket
from collections import namedtuple
import json
from six.moves.BaseHTTPServer import HTTPServer
from six.moves.BaseHTTPServer import BaseHTTPRequestHandler
from six.moves.socketserver import ThreadingMixIn
import requests

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
from chalice.app import Response
from chalice.app import AuthResponse  # noqa
from chalice.app import BuiltinAuthConfig  # noqa
from chalice.awsclient import TypedAWSClient
from chalice.config import Config  # noqa
from chalice.deploy.appgraph import DependencyBuilder, ApplicationGraphBuilder
from chalice.deploy.models import LambdaFunction
from chalice.deploy.packager import BaseLambdaDeploymentPackager
from chalice.deploy.packager import LayerDeploymentPackager
from chalice.compat import urlparse, parse_qs, posix_path
from chalice.docker import LambdaContainer, LambdaImageBuilder
from chalice.utils import UI, OSUtils

MatchResult = namedtuple('MatchResult', ['route', 'captured', 'query_params'])
EventType = Dict[str, Any]
ContextType = Dict[str, Any]
HeaderType = Dict[str, Any]
ResponseType = Dict[str, Any]
ContainerMap = Dict[str, LambdaContainer]
HandlerCls = Callable[..., 'ChaliceRequestHandler']
ServerCls = Callable[..., 'HTTPServer']
ProxyServerCls = Callable[..., 'LambdaProxyServer']
LOGGER = logging.getLogger(__name__)


class Clock(object):
    def time(self):
        # type: () -> float
        return time.time()


def create_local_server(app_obj, config, host, port):
    # type: (Chalice, Config, str, int) -> LocalDevServer
    app_obj.__class__ = LocalChalice
    return LocalDevServer(app_obj, config, host, port)


def create_container_proxy_resource_manager(
        config,            # type: Config
        ui,                # type: UI
        osutils,           # type: OSUtils
        packager,          # type: DockerPackager
        image_builder,     # type: LambdaImageBuilder
):
    # type: (...) -> ContainerProxyResourceManager
    return ContainerProxyResourceManager(config, ui, osutils,
                                         packager, image_builder)


def create_proxy_server_runner(
        config,                 # type: Config
        stage,                  # type: str
        host,                   # type: str
        port,                   # type: int
        app_graph_builder,      # type: ApplicationGraphBuilder
        dependency_builder,     # type: DependencyBuilder
        resource_manager,       # type: ContainerProxyResourceManager
        proxy_handler           # type: ContainerProxyHandler
):
    # type: (...) -> ProxyServerRunner
    return ProxyServerRunner(config, stage, host, port,
                             app_graph_builder, dependency_builder,
                             resource_manager, proxy_handler)


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
        # type: (str, str, Dict[str, str], str) -> EventType
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


class ResourceNotFoundError(LocalGatewayException):
    CODE = 404


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


class LocalFunctionCaller(object):
    def __init__(self, app_object):
        # type: (Chalice) -> None
        self._app_object = app_object

    def call_rest_api(self, event, context):
        # type: (EventType, LambdaContext) -> ResponseType
        return self._app_object(event, context)

    def call_authorizer(self, authorizer, event, context):
        # type: (Any, EventType, LambdaContext) -> ResponseType
        return authorizer(event, context)


class ContainerFunctionCaller(object):
    def __init__(self, config, session, container_map=None):
        # type: (Config, requests.Session, ContainerMap) -> None
        self._config = config
        self._container_map = {} if container_map is None else container_map
        self._session = session

    def call_rest_api(self, event, context):
        # type: (EventType, LambdaContext) -> ResponseType
        function_name = "%s-%s" % (self._config.app_name,
                                   self._config.chalice_stage)
        response = self._get_container_response(function_name, event)
        return response

    def call_authorizer(self, authorizer, event, context):
        # type: (Any, EventType, LambdaContext) -> ResponseType
        # Authorizer had to be made into an Any type since mypy couldn't
        # detect that app.ChaliceAuthorizer was callable.
        function_name = "%s-%s-%s" % (self._config.app_name,
                                      self._config.chalice_stage,
                                      authorizer.name)
        response = self._get_container_response(function_name, event)
        return response

    def _get_container_response(self, function_name, event):
        # type: (str, EventType) -> ResponseType
        container = self._container_map[function_name]
        if not container.is_created():
            container.run()
            container.wait_for_initialize()
        url = "http://localhost:" + str(container.api_port) + \
              "/2015-03-31/functions/function-name/invocations"
        json_event = json.dumps(event)
        response = self._session.post(url, data=json_event)
        return json.loads(response.text)

    def update_container_map(self, container_map):
        # type: (ContainerMap) -> None
        self._container_map.update(container_map)


FunctionCaller = Union[LocalFunctionCaller, ContainerFunctionCaller]


class LocalGatewayAuthorizer(object):
    """A class for running user defined authorizers in local mode."""
    def __init__(self, app_object, function_caller):
        # type: (Chalice, FunctionCaller) -> None
        self._app_object = app_object
        self._function_caller = function_caller
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
        auth_result = self._function_caller.call_authorizer(authorizer,
                                                            auth_event,
                                                            lambda_context)
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
               statement.get('Action') == 'execute-api:Invoke':
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
    def __init__(self, app_object, config, function_caller):
        # type: (Chalice, Config, FunctionCaller) -> None
        self._app_object = app_object
        self._config = config
        self._function_caller = function_caller
        self.event_converter = LambdaEventConverter(
            RouteMatcher(list(app_object.routes)),
            self._app_object.api.binary_types
        )
        self._authorizer = LocalGatewayAuthorizer(app_object, function_caller)

    def _generate_lambda_context(self):
        # type: () -> LambdaContext
        if self._config.lambda_timeout is None:
            timeout = None
        else:
            timeout = self._config.lambda_timeout * 1000
        return LambdaContext(
            function_name=self._config.function_name,
            memory_size=self._config.lambda_memory_size,
            max_runtime_ms=timeout
        )

    def _generate_lambda_event(self, method, path, headers, body):
        # type: (str, str, HeaderType, Optional[str]) -> EventType
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
        # type: (str, str, HeaderType, Optional[str]) -> ResponseType
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
        response = self._function_caller.call_rest_api(lambda_event,
                                                       lambda_context)
        return response

    def _autogen_options_headers(self, lambda_event):
        # type:(EventType) -> HeaderType
        route_key = lambda_event['requestContext']['resourcePath']
        route_dict = self._app_object.routes[route_key]
        route_methods = list(route_dict.keys())

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
        function_caller = LocalFunctionCaller(app_object)
        self.local_gateway = LocalGateway(app_object, config, function_caller)
        BaseHTTPRequestHandler.__init__(
            self, request, client_address, server)  # type: ignore

    def _parse_payload(self):
        # type: () -> Tuple[HeaderType, Optional[str]]
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


class LambdaProxyServer(LocalDevServer):
    def __init__(self, config, host, port, proxy_handler,
                 server_cls=ThreadedHTTPServer):
        # type: (Config, str, int, ContainerProxyHandler, ServerCls) -> None
        self.host = host
        self.port = port
        self._wrapped_handler = functools.partial(
            ProxyRequestHandler, config=config, proxy_handler=proxy_handler)
        self.server = server_cls((host, port), self._wrapped_handler)


class ProxyServerRunner(object):
    def __init__(self,
                 config,                # type: Config
                 stage,                 # type: str
                 host,                  # type: str
                 port,                  # type: int
                 app_graph_builder,     # type: ApplicationGraphBuilder
                 dependency_builder,    # type: DependencyBuilder
                 resource_manager,      # type: ContainerProxyResourceManager
                 proxy_handler,         # type: ContainerProxyHandler
                 server_cls=LambdaProxyServer    # type: ProxyServerCls
                 ):
        # type: (...) -> None
        self._config = config
        self._stage = stage
        self._host = host
        self._port = port
        self._app_graph_builder = app_graph_builder
        self._dependency_builder = dependency_builder
        self._resource_manager = resource_manager
        self._proxy_handler = proxy_handler
        self._server_cls = server_cls

    def run(self):
        # type: () -> None
        app_graph = self._app_graph_builder.build(self._config, self._stage)
        lambdas = self._dependency_builder\
            .list_dependencies_by_type(app_graph, LambdaFunction)
        resources = self._resource_manager.build_resources(lambdas)
        self._proxy_handler.add_resources(resources)
        server = self._server_cls(self._config, self._host,
                                  self._port, self._proxy_handler)
        try:
            server.serve_forever()
        finally:
            self._resource_manager.cleanup()


class ProxyRequestHandler(ChaliceRequestHandler):
    """A class for mapping raw HTTP events to the correct functions."""
    protocol_version = 'HTTP/1.1'

    def __init__(self,
                 request,           # type: bytes
                 client_address,    # type: Tuple[str, int]
                 server,            # type: HTTPServer
                 config,            # type: Config
                 proxy_handler      # type: ContainerProxyHandler
                 ):
        # type: (...) -> None
        # pylint: disable=non-parent-init-called
        self._config = config
        self._handler = proxy_handler
        BaseHTTPRequestHandler.__init__(
            self, request, client_address, server)  # type: ignore

    def _generic_handle(self):
        # type: () -> None
        function = re.match(r"^/\d{4}-\d{2}-\d{2}/functions/(.+)/invocations$",
                            self.path)
        headers, body = self._parse_payload()
        try:
            response = None
            if function is None:
                prefix = '/' + self._config.api_gateway_stage
                if self.path.startswith(prefix):
                    response = self._handler.handle_rest_api(
                        self.command, self.path[len(prefix):], headers, body)
                else:
                    raise ForbiddenError(
                        {'x-amzn-RequestId': str(uuid.uuid4()),
                         'x-amzn-ErrorType': 'ForbiddenException'},
                        (b'{"Message": '
                         b'"Forbidden"}'))
            else:
                function_name = function.group(1)
                response = self._handler.handle_invoke_function(
                    self.path, headers, body, function_name)
            self._send_http_response(response.status_code,
                                     response.headers, response.body)
        except LocalGatewayException as e:
            self._send_error_response(e)

    do_GET = do_PUT = do_POST = do_HEAD = do_DELETE = do_PATCH = do_OPTIONS = \
        _generic_handle


class ContainerProxyHandler(object):
    def __init__(self,
                 session,               # type: requests.Session
                 function_caller,       # type: ContainerFunctionCaller
                 local_gateway,         # type: LocalGateway
                 container_map=None     # type: Optional[ContainerMap]
                 ):
        # type: (...) -> None
        self._session = session
        self._container_map = {} if container_map is None else container_map
        self._function_caller = function_caller
        self._local_gateway = local_gateway

    def add_resources(self, container_map):
        # type: (ContainerMap) -> None
        self._container_map.update(container_map)
        self._function_caller.update_container_map(container_map)

    def handle_rest_api(self, method, path, headers, body):
        # type: (str, str, HeaderType, Optional[str]) -> Response
        if path == '':
            path = '/'
        try:
            response = self._local_gateway.handle_request(
                method=method,
                path=path,
                headers=headers,
                body=body
            )
            status_code = response['statusCode']
            headers = response['headers'].copy()
            headers.update(response['multiValueHeaders'])
            body = response['body']
            return Response(body, headers, status_code)
        except LocalGatewayException as e:
            return Response(e.body, e.headers, e.CODE)

    def handle_invoke_function(self, path, headers, body, function_name):
        # type: (str, HeaderType, Optional[str], str) -> Response
        self._validate_function(function_name)
        if body is None:
            body = b'{}'
        container = self._container_map[function_name]
        if not container.is_created():
            container.run()
            container.wait_for_initialize()
        url = "http://localhost:" + str(container.api_port) + path
        self._session.headers = headers     # type: ignore
        response = self._session.post(url, data=body)

        status_code = response.status_code
        headers = dict(response.headers)
        headers.pop("Content-Length")
        body = response.text
        return Response(body, headers, status_code)

    def _validate_function(self, function_name):
        # type: (str) -> None
        if function_name not in self._container_map:
            raise ResourceNotFoundError(
                {'x-amzn-RequestId': str(uuid.uuid4()),
                 'x-amzn-ErrorType': 'ResourceNotFoundException'},
                b'{"Message": 'b'"Function not found: %s"}' %
                function_name.encode('ascii'))


class LambdaLayerDownloader(object):
    def __init__(self, config, ui, lambda_client, osutils, session):
        # type: (Config, UI, TypedAWSClient, OSUtils, requests.Session) -> None
        self._config = config
        self._ui = ui
        self._lambda_client = lambda_client
        self._osutils = osutils
        self._session = session

    def download_all(self, layer_arns, cache_dir):
        # type: (List[str], str) -> List[str]
        return [self.download(layer, cache_dir) for layer in layer_arns]

    def download(self, layer_arn, cache_dir):
        # type: (str, str) -> str
        layer_path = self._get_layer_path(layer_arn, cache_dir)
        if self._is_downloaded(layer_path):
            LOGGER.debug("Layer %s is already downloaded, skipping download.",
                         layer_arn)
            return layer_path
        layer = self._lambda_client.get_layer_version(layer_arn)
        try:
            uri = layer["Content"]["Location"]
        except KeyError:
            raise ValueError("Invalid layer arn: %s" % layer_arn)
        self._ui.write("Downloading layer %s...\n" % layer_arn)
        get_request = self._session.get(uri, stream=True)
        with open(layer_path, "wb") as local_layer_file:
            for data in get_request.iter_content(chunk_size=None):
                local_layer_file.write(data)
        return layer_path

    def _get_layer_path(self, layer_arn, cache_dir):
        # type: (str, str) -> str
        filename = 'layer-%s-%s.zip' \
                   % (hashlib.md5(layer_arn.encode('utf-8')).hexdigest(),
                      self._config.lambda_python_version)
        layer_path = self._osutils.joinpath(cache_dir, filename)
        return layer_path

    def _is_downloaded(self, layer_path):
        # type: (str) -> bool
        return self._osutils.file_exists(layer_path)


class DockerPackager(object):
    def __init__(self,
                 config,            # type: Config
                 osutils,           # type: OSUtils
                 app_packager,      # type: BaseLambdaDeploymentPackager
                 layer_packager,    # type: LayerDeploymentPackager
                 layer_downloader   # type: LambdaLayerDownloader
                 ):
        self._config = config
        self._osutils = osutils
        self._app_packager = app_packager
        self._layer_packager = layer_packager
        self._layer_downloader = layer_downloader

    def package_app(self):
        # type: () -> str
        project_dir = self._config.project_dir
        python_version = self._config.lambda_python_version
        app_file = self._app_packager.create_deployment_package(
            project_dir, python_version)
        filename = app_file[:-4]
        dir_path = self._osutils.joinpath(self._cache_directory(), filename)
        if self._osutils.directory_exists(dir_path):
            return dir_path
        self._osutils.makedirs(dir_path)
        self._osutils.extract_zipfile(app_file, dir_path)
        return dir_path

    def package_layers(self, lambda_functions):
        # type: (List[LambdaFunction]) -> Dict[str, str]
        if self._config.automatic_layer:
            auto_layer_path = self._layer_packager.create_deployment_package(
                self._config.project_dir, self._config.lambda_python_version)
        else:
            auto_layer_path = ''
        layer_dir_map = {}
        for function in lambda_functions:
            stage = self._config.chalice_stage
            scoped_config = self._config.scope(stage, function.resource_name)
            layer_dir = self.create_layer_directory(scoped_config.layers,
                                                    auto_layer_path)
            layer_dir_map[function.function_name] = layer_dir
        return layer_dir_map

    def create_layer_directory(self, layer_arns, auto_layer_path):
        # type: (List[str], str) -> str
        layers_id = (auto_layer_path + ' '.join(layer_arns)).encode("utf-8")
        dir_name = "layers-%s-%s" % (hashlib.md5(layers_id).hexdigest(),
                                     self._config.lambda_python_version)
        cache_dir = self._cache_directory()
        dir_path = self._osutils.joinpath(cache_dir, dir_name)
        if self._osutils.directory_exists(dir_path):
            return dir_path
        self._osutils.makedirs(dir_path)
        if auto_layer_path != '':
            self._osutils.extract_zipfile(auto_layer_path, dir_path)
        layer_files = self._layer_downloader.download_all(layer_arns,
                                                          cache_dir)
        for layer_file in layer_files:
            self._osutils.extract_zipfile(layer_file, dir_path)
        return dir_path

    def _cache_directory(self):
        # type: () -> str
        cache_dir = self._osutils.joinpath(self._config.project_dir,
                                           '.chalice', 'deployments')
        if not self._osutils.directory_exists(cache_dir):
            self._osutils.makedirs(cache_dir)
        return cache_dir


class ContainerProxyResourceManager(object):
    def __init__(self,
                 config,            # type: Config
                 ui,                # type: UI
                 osutils,           # type: OSUtils
                 packager,          # type: DockerPackager
                 image_builder,     # type: LambdaImageBuilder
                 ):
        # type: (...) -> None
        self._config = config
        self._ui = ui
        self._osutils = osutils
        self._packager = packager
        self._image_builder = image_builder

        self._container_map = {}    # type: ContainerMap

    def build_resources(self, lambda_functions):
        # type: (List[LambdaFunction]) -> ContainerMap
        app_dir = self._packager.package_app()
        layer_dirs = self._packager.package_layers(lambda_functions)
        python_version = self._config.lambda_python_version
        lambda_image = self._image_builder.build(python_version)
        container_map = self._create_containers(
            lambda_image, lambda_functions, app_dir, layer_dirs)
        self._container_map = container_map
        return container_map

    def cleanup(self):
        # type: () -> None
        for _, container in self._container_map.items():
            try:
                container.delete()
            except Exception as ex:
                LOGGER.debug("Failed to delete Docker container")
                LOGGER.exception(ex)

    def _create_containers(self,
                           lambda_image,    # type: str
                           functions,       # type: List[LambdaFunction]
                           app_dir,         # type: str
                           layer_dir_map    # type: Dict[str, str]
                           ):
        # type: (...) -> ContainerMap
        container_map = {}
        self._ui.write("Creating Docker containers.\n")
        for function in functions:
            config = self._config.scope(self._config.chalice_stage,
                                        function.resource_name)
            layers_dir = layer_dir_map[function.function_name]
            container_port = self._unused_tcp_port()
            env_vars = config.environment_variables
            memory_limit = config.lambda_memory_size
            container_map[function.function_name] = \
                LambdaContainer(ui=self._ui,
                                port=container_port,
                                handler=function.handler,
                                code_dir=posix_path(app_dir),
                                layers_dir=posix_path(layers_dir),
                                image=lambda_image,
                                env_vars=env_vars,
                                memory_limit_mb=memory_limit,
                                stay_open=True)
        return container_map

    def _unused_tcp_port(self):
        # type: () -> int
        # pylint: disable=no-member
        with contextlib.closing(socket.socket()) as sock:
            sock.bind(('127.0.0.1', 0))
            return sock.getsockname()[1]
