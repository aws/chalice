"""Chalice app and routing code."""
import re
import sys
import os
import logging
import json
import traceback
import decimal
import base64
from collections import defaultdict, Mapping


__version__ = '1.3.0'


# Implementation note:  This file is intended to be a standalone file
# that gets copied into the lambda deployment package.  It has no dependencies
# on other parts of chalice so it can stay small and lightweight, with minimal
# startup overhead.


_PARAMS = re.compile(r'{\w+}')

try:
    # In python 2 there is a base class for the string types that
    # we can check for. It was removed in python 3 so it will cause
    # a name error.
    _ANY_STRING = (basestring, bytes)
except NameError:
    # In python 3 string and bytes are different so we explicitly check
    # for both.
    _ANY_STRING = (str, bytes)


def handle_decimals(obj):
    # Lambda will automatically serialize decimals so we need
    # to support that as well.
    if isinstance(obj, decimal.Decimal):
        return float(obj)
    return obj


def error_response(message, error_code, http_status_code, headers=None):
    body = {'Code': error_code, 'Message': message}
    response = Response(body=body, status_code=http_status_code,
                        headers=headers)

    return response.to_dict()


def _matches_content_type(content_type, valid_content_types):
    if ';' in content_type:
        content_type = content_type.split(';', 1)[0].strip()
    return content_type in valid_content_types


class ChaliceError(Exception):
    pass


class ChaliceViewError(ChaliceError):
    STATUS_CODE = 500

    def __init__(self, msg=''):
        super(ChaliceViewError, self).__init__(
            self.__class__.__name__ + ': %s' % msg)


class BadRequestError(ChaliceViewError):
    STATUS_CODE = 400


class UnauthorizedError(ChaliceViewError):
    STATUS_CODE = 401


class ForbiddenError(ChaliceViewError):
    STATUS_CODE = 403


class NotFoundError(ChaliceViewError):
    STATUS_CODE = 404


class MethodNotAllowedError(ChaliceViewError):
    STATUS_CODE = 405


class RequestTimeoutError(ChaliceViewError):
    STATUS_CODE = 408


class ConflictError(ChaliceViewError):
    STATUS_CODE = 409


class UnprocessableEntityError(ChaliceViewError):
    STATUS_CODE = 422


class TooManyRequestsError(ChaliceViewError):
    STATUS_CODE = 429


ALL_ERRORS = [
    ChaliceViewError,
    BadRequestError,
    NotFoundError,
    UnauthorizedError,
    ForbiddenError,
    MethodNotAllowedError,
    RequestTimeoutError,
    ConflictError,
    UnprocessableEntityError,
    TooManyRequestsError]


class CaseInsensitiveMapping(Mapping):
    """Case insensitive and read-only mapping."""

    def __init__(self, mapping):
        mapping = mapping or {}
        self._dict = {k.lower(): v for k, v in mapping.items()}

    def __getitem__(self, key):
        return self._dict[key.lower()]

    def __iter__(self):
        return iter(self._dict)

    def __len__(self):
        return len(self._dict)

    def __repr__(self):
        return 'CaseInsensitiveMapping(%s)' % repr(self._dict)


class Authorizer(object):
    name = ''

    def to_swagger(self):
        raise NotImplementedError("to_swagger")


class IAMAuthorizer(Authorizer):

    _AUTH_TYPE = 'aws_iam'

    def __init__(self):
        self.name = 'sigv4'

    def to_swagger(self):
        return {
            'in': 'header',
            'type': 'apiKey',
            'name': 'Authorization',
            'x-amazon-apigateway-authtype': 'awsSigv4',
        }


class CognitoUserPoolAuthorizer(Authorizer):

    _AUTH_TYPE = 'cognito_user_pools'

    def __init__(self, name, provider_arns, header='Authorization'):
        self.name = name
        self._header = header
        if not isinstance(provider_arns, list):
            # This class is used directly by users so we're
            # adding some validation to help them troubleshoot
            # potential issues.
            raise TypeError(
                "provider_arns should be a list of ARNs, received: %s"
                % provider_arns)
        self._provider_arns = provider_arns

    def to_swagger(self):
        return {
            'in': 'header',
            'type': 'apiKey',
            'name': self._header,
            'x-amazon-apigateway-authtype': self._AUTH_TYPE,
            'x-amazon-apigateway-authorizer': {
                'type': self._AUTH_TYPE,
                'providerARNs': self._provider_arns,
            }
        }


class CustomAuthorizer(Authorizer):

    _AUTH_TYPE = 'custom'

    def __init__(self, name, authorizer_uri, ttl_seconds=300,
                 header='Authorization'):
        self.name = name
        self._header = header
        self._authorizer_uri = authorizer_uri
        self._ttl_seconds = ttl_seconds

    def to_swagger(self):
        return {
            'in': 'header',
            'type': 'apiKey',
            'name': self._header,
            'x-amazon-apigateway-authtype': self._AUTH_TYPE,
            'x-amazon-apigateway-authorizer': {
                'type': 'token',
                'authorizerUri': self._authorizer_uri,
                'authorizerResultTtlInSeconds': self._ttl_seconds,
            }
        }


class CORSConfig(object):
    """A cors configuration to attach to a route."""

    _REQUIRED_HEADERS = ['Content-Type', 'X-Amz-Date', 'Authorization',
                         'X-Api-Key', 'X-Amz-Security-Token']

    def __init__(self, allow_origin='*', allow_headers=None,
                 expose_headers=None, max_age=None, allow_credentials=None):
        self.allow_origin = allow_origin

        if allow_headers is None:
            allow_headers = set(self._REQUIRED_HEADERS)
        else:
            allow_headers = set(allow_headers + self._REQUIRED_HEADERS)
        self._allow_headers = allow_headers

        if expose_headers is None:
            expose_headers = []
        self._expose_headers = expose_headers

        self._max_age = max_age
        self._allow_credentials = allow_credentials

    @property
    def allow_headers(self):
        return ','.join(sorted(self._allow_headers))

    def get_access_control_headers(self):
        headers = {
            'Access-Control-Allow-Origin': self.allow_origin,
            'Access-Control-Allow-Headers': self.allow_headers
        }
        if self._expose_headers:
            headers.update({
                'Access-Control-Expose-Headers': ','.join(self._expose_headers)
            })
        if self._max_age is not None:
            headers.update({
                'Access-Control-Max-Age': str(self._max_age)
            })
        if self._allow_credentials is True:
            headers.update({
                'Access-Control-Allow-Credentials': 'true'
            })

        return headers

    def __eq__(self, other):
        if isinstance(other, self.__class__):
            return self.get_access_control_headers() == \
                other.get_access_control_headers()


class Request(object):
    """The current request from API gateway."""

    def __init__(self, query_params, headers, uri_params, method, body,
                 context, stage_vars, is_base64_encoded):
        self.query_params = query_params
        self.headers = CaseInsensitiveMapping(headers)
        self.uri_params = uri_params
        self.method = method
        self._is_base64_encoded = is_base64_encoded
        self._body = body
        #: The parsed JSON from the body.  This value should
        #: only be set if the Content-Type header is application/json,
        #: which is the default content type value in chalice.
        self._json_body = None
        self._raw_body = b''
        self.context = context
        self.stage_vars = stage_vars

    def _base64decode(self, encoded):
        if not isinstance(encoded, bytes):
            encoded = encoded.encode('ascii')
        output = base64.b64decode(encoded)
        return output

    @property
    def raw_body(self):
        if not self._raw_body and self._body is not None:
            if self._is_base64_encoded:
                self._raw_body = self._base64decode(self._body)
            elif not isinstance(self._body, bytes):
                self._raw_body = self._body.encode('utf-8')
            else:
                self._raw_body = self._body
        return self._raw_body

    @property
    def json_body(self):
        if self.headers.get('content-type', '').startswith('application/json'):
            if self._json_body is None:
                try:
                    self._json_body = json.loads(self.raw_body)
                except ValueError:
                    raise BadRequestError('Error Parsing JSON')
            return self._json_body

    def to_dict(self):
        # Don't copy internal attributes.
        copied = {k: v for k, v in self.__dict__.items()
                  if not k.startswith('_')}
        # We want the output of `to_dict()` to be
        # JSON serializable, so we need to remove the CaseInsensitive dict.
        copied['headers'] = dict(copied['headers'])
        return copied


class Response(object):
    def __init__(self, body, headers=None, status_code=200):
        self.body = body
        if headers is None:
            headers = {}
        self.headers = headers
        self.status_code = status_code

    def to_dict(self, binary_types=None):
        body = self.body
        if not isinstance(body, _ANY_STRING):
            body = json.dumps(body, default=handle_decimals)
        response = {
            'headers': self.headers,
            'statusCode': self.status_code,
            'body': body
        }
        if binary_types is not None:
            self._b64encode_body_if_needed(response, binary_types)
        return response

    def _b64encode_body_if_needed(self, response_dict, binary_types):
        response_headers = CaseInsensitiveMapping(response_dict['headers'])
        content_type = response_headers.get('content-type', '')
        body = response_dict['body']

        if _matches_content_type(content_type, binary_types):
            if _matches_content_type(content_type, ['application/json']):
                # There's a special case when a user configures
                # ``application/json`` as a binary type.  The default
                # json serialization results in a string type, but for binary
                # content types we need a type bytes().  So we need to special
                # case this scenario and encode the JSON body to bytes().
                body = body.encode('utf-8')
            body = self._base64encode(body)
            response_dict['isBase64Encoded'] = True
        response_dict['body'] = body

    def _base64encode(self, data):
        if not isinstance(data, bytes):
            raise ValueError('Expected bytes type for body with binary '
                             'Content-Type. Got %s type body instead.'
                             % type(data))
        data = base64.b64encode(data)
        return data.decode('ascii')


class RouteEntry(object):

    def __init__(self, view_function, view_name, path, method,
                 api_key_required=None, content_types=None,
                 cors=False, authorizer=None):
        self.view_function = view_function
        self.view_name = view_name
        self.uri_pattern = path
        self.method = method
        self.api_key_required = api_key_required
        #: A list of names to extract from path:
        #: e.g, '/foo/{bar}/{baz}/qux -> ['bar', 'baz']
        self.view_args = self._parse_view_args()
        self.content_types = content_types
        # cors is passed as either a boolean or a CORSConfig object. If it is a
        # boolean it needs to be replaced with a real CORSConfig object to
        # pass the typechecker. None in this context will not inject any cors
        # headers, otherwise the CORSConfig object will determine which
        # headers are injected.
        if cors is True:
            cors = CORSConfig()
        elif cors is False:
            cors = None
        self.cors = cors
        self.authorizer = authorizer

    def _parse_view_args(self):
        if '{' not in self.uri_pattern:
            return []
        # The [1:-1] slice is to remove the braces
        # e.g {foobar} -> foobar
        results = [r[1:-1] for r in _PARAMS.findall(self.uri_pattern)]
        return results

    def __eq__(self, other):
        return self.__dict__ == other.__dict__


class APIGateway(object):

    _DEFAULT_BINARY_TYPES = [
        'application/octet-stream',
        'application/x-tar',
        'application/zip',
        'audio/basic',
        'audio/ogg',
        'audio/mp4',
        'audio/mpeg',
        'audio/wav',
        'audio/webm',
        'image/png',
        'image/jpg',
        'image/jpeg',
        'image/gif',
        'video/ogg',
        'video/mpeg',
        'video/webm',
    ]

    def __init__(self):
        self.binary_types = self.default_binary_types

    @property
    def default_binary_types(self):
        return list(self._DEFAULT_BINARY_TYPES)


class Chalice(object):

    FORMAT_STRING = '%(name)s - %(levelname)s - %(message)s'

    def __init__(self, app_name, debug=False, configure_logs=True, env=None):
        self.app_name = app_name
        self.api = APIGateway()
        self.routes = defaultdict(dict)
        self.current_request = None
        self.lambda_context = None
        self._debug = debug
        self.configure_logs = configure_logs
        self.log = logging.getLogger(self.app_name)
        self.builtin_auth_handlers = []
        self.event_sources = []
        self.pure_lambda_functions = []
        if env is None:
            env = os.environ
        self._initialize(env)

    def _initialize(self, env):
        if self.configure_logs:
            self._configure_logging()
        env['AWS_EXECUTION_ENV'] = '%s aws-chalice/%s' % (
            env.get('AWS_EXECUTION_ENV', 'AWS_Lambda'),
            __version__,
        )

    @property
    def debug(self):
        return self._debug

    @debug.setter
    def debug(self, value):
        self._debug = value
        self._configure_log_level()

    def _configure_logging(self):
        if self._already_configured(self.log):
            return
        handler = logging.StreamHandler(sys.stdout)
        # Timestamp is handled by lambda itself so the
        # default FORMAT_STRING doesn't need to include it.
        formatter = logging.Formatter(self.FORMAT_STRING)
        handler.setFormatter(formatter)
        self.log.propagate = False
        self._configure_log_level()
        self.log.addHandler(handler)

    def _already_configured(self, log):
        if not log.handlers:
            return False
        for handler in log.handlers:
            if isinstance(handler, logging.StreamHandler):
                if handler.stream == sys.stdout:
                    return True
        return False

    def _configure_log_level(self):
        if self._debug:
            level = logging.DEBUG
        else:
            level = logging.ERROR
        self.log.setLevel(level)

    def authorizer(self, name=None, **kwargs):
        def _register_authorizer(auth_func):
            auth_name = name
            if auth_name is None:
                auth_name = auth_func.__name__
            ttl_seconds = kwargs.pop('ttl_seconds', None)
            execution_role = kwargs.pop('execution_role', None)
            if kwargs:
                raise TypeError(
                    'TypeError: authorizer() got unexpected keyword '
                    'arguments: %s' % ', '.join(list(kwargs)))
            auth_config = BuiltinAuthConfig(
                name=auth_name,
                handler_string='app.%s' % auth_func.__name__,
                ttl_seconds=ttl_seconds,
                execution_role=execution_role,
            )
            self.builtin_auth_handlers.append(auth_config)
            return ChaliceAuthorizer(auth_name, auth_func, auth_config)
        return _register_authorizer

    def schedule(self, expression, name=None):
        def _register_schedule(event_func):
            handler_name = name
            if handler_name is None:
                handler_name = event_func.__name__
            event_source = CloudWatchEventSource(
                name=handler_name,
                schedule_expression=expression,
                handler_string='app.%s' % event_func.__name__)
            self.event_sources.append(event_source)
            return ScheduledEventHandler(event_func)
        return _register_schedule

    def lambda_function(self, name=None):
        def _register_lambda_function(lambda_func):
            handler_name = name
            if handler_name is None:
                handler_name = lambda_func.__name__
            wrapper = LambdaFunction(
                lambda_func, name=handler_name,
                handler_string='app.%s' % lambda_func.__name__)
            self.pure_lambda_functions.append(wrapper)
            return wrapper
        return _register_lambda_function

    def route(self, path, **kwargs):
        def _register_view(view_func):
            self._add_route(path, view_func, **kwargs)
            return view_func
        return _register_view

    def _add_route(self, path, view_func, **kwargs):
        name = kwargs.pop('name', view_func.__name__)
        methods = kwargs.pop('methods', ['GET'])
        authorizer = kwargs.pop('authorizer', None)
        api_key_required = kwargs.pop('api_key_required', None)
        content_types = kwargs.pop('content_types', ['application/json'])
        cors = kwargs.pop('cors', False)
        if not isinstance(content_types, list):
            raise ValueError('In view function "%s", the content_types '
                             'value must be a list, not %s: %s'
                             % (name, type(content_types), content_types))
        if kwargs:
            raise TypeError('TypeError: route() got unexpected keyword '
                            'arguments: %s' % ', '.join(list(kwargs)))
        for method in methods:
            if method in self.routes[path]:
                raise ValueError(
                    "Duplicate method: '%s' detected for route: '%s'\n"
                    "between view functions: \"%s\" and \"%s\". A specific "
                    "method may only be specified once for "
                    "a particular path." % (
                        method, path, self.routes[path][method].view_name,
                        name)
                )
            entry = RouteEntry(view_func, name, path, method,
                               api_key_required, content_types,
                               cors, authorizer)
            self.routes[path][method] = entry

    def __call__(self, event, context):
        # This is what's invoked via lambda.
        # Sometimes the event can be something that's not
        # what we specified in our request_template mapping.
        # When that happens, we want to give a better error message here.
        resource_path = event.get('requestContext', {}).get('resourcePath')
        if resource_path is None:
            return error_response(error_code='InternalServerError',
                                  message='Unknown request.',
                                  http_status_code=500)
        http_method = event['requestContext']['httpMethod']
        if resource_path not in self.routes:
            raise ChaliceError("No view function for: %s" % resource_path)
        if http_method not in self.routes[resource_path]:
            return error_response(
                error_code='MethodNotAllowedError',
                message='Unsupported method: %s' % http_method,
                http_status_code=405)
        route_entry = self.routes[resource_path][http_method]
        view_function = route_entry.view_function
        function_args = {name: event['pathParameters'][name]
                         for name in route_entry.view_args}
        self.lambda_context = context
        self.current_request = Request(event['queryStringParameters'],
                                       event['headers'],
                                       event['pathParameters'],
                                       event['requestContext']['httpMethod'],
                                       event['body'],
                                       event['requestContext'],
                                       event['stageVariables'],
                                       event.get('isBase64Encoded', False))
        # We're getting the CORS headers before validation to be able to
        # output desired headers with
        cors_headers = None
        if self._cors_enabled_for_route(route_entry):
            cors_headers = self._get_cors_headers(route_entry.cors)
        # We're doing the header validation after creating the request
        # so can leverage the case insensitive dict that the Request class
        # uses for headers.
        if route_entry.content_types:
            content_type = self.current_request.headers.get(
                'content-type', 'application/json')
            if not _matches_content_type(content_type,
                                         route_entry.content_types):
                return error_response(
                    error_code='UnsupportedMediaType',
                    message='Unsupported media type: %s' % content_type,
                    http_status_code=415,
                    headers=cors_headers
                )
        response = self._get_view_function_response(view_function,
                                                    function_args)
        if cors_headers is not None:
            self._add_cors_headers(response, cors_headers)

        response_headers = CaseInsensitiveMapping(response.headers)
        if not self._validate_binary_response(
                self.current_request.headers, response_headers):
            content_type = response_headers.get('content-type', '')
            return error_response(
                error_code='BadRequest',
                message=('Request did not specify an Accept header with %s, '
                         'The response has a Content-Type of %s. If a '
                         'response has a binary Content-Type then the request '
                         'must specify an Accept header that matches.'
                         % (content_type, content_type)),
                http_status_code=400,
                headers=cors_headers
            )
        response = response.to_dict(self.api.binary_types)
        return response

    def _validate_binary_response(self, request_headers, response_headers):
        # Validates that a response is valid given the request. If the response
        # content-type specifies a binary type, there must be an accept header
        # that is a binary type as well.
        request_accept_header = request_headers.get('accept')
        response_content_type = response_headers.get(
            'content-type', 'application/json')
        response_is_binary = _matches_content_type(response_content_type,
                                                   self.api.binary_types)
        expects_binary_response = False
        if request_accept_header is not None:
            expects_binary_response = _matches_content_type(
                request_accept_header, self.api.binary_types)
        if response_is_binary and not expects_binary_response:
            return False
        return True

    def _get_view_function_response(self, view_function, function_args):
        try:
            response = view_function(**function_args)
            if not isinstance(response, Response):
                response = Response(body=response)
            self._validate_response(response)
        except ChaliceViewError as e:
            # Any chalice view error should propagate.  These
            # get mapped to various HTTP status codes in API Gateway.
            response = Response(body={'Code': e.__class__.__name__,
                                      'Message': str(e)},
                                status_code=e.STATUS_CODE)
        except Exception as e:
            headers = {}
            if self.debug:
                # If the user has turned on debug mode,
                # we'll let the original exception propogate so
                # they get more information about what went wrong.
                self.log.debug("Caught exception for %s", view_function,
                               exc_info=True)
                stack_trace = ''.join(traceback.format_exc())
                body = stack_trace
                headers['Content-Type'] = 'text/plain'
            else:
                body = {'Code': 'InternalServerError',
                        'Message': 'An internal server error occurred.'}
            response = Response(body=body, headers=headers, status_code=500)
        return response

    def _validate_response(self, response):
        for header, value in response.headers.items():
            if '\n' in value:
                raise ChaliceError("Bad value for header '%s': %r" %
                                   (header, value))

    def _cors_enabled_for_route(self, route_entry):
        return route_entry.cors is not None

    def _get_cors_headers(self, cors):
        return cors.get_access_control_headers()

    def _add_cors_headers(self, response, cors_headers):
        for name, value in cors_headers.items():
            if name not in response.headers:
                response.headers[name] = value


class BuiltinAuthConfig(object):
    def __init__(self, name, handler_string, ttl_seconds=None,
                 execution_role=None):
        # We'd also support all the misc config options you can set.
        self.name = name
        self.handler_string = handler_string
        self.ttl_seconds = ttl_seconds
        self.execution_role = execution_role


class ChaliceAuthorizer(object):
    def __init__(self, name, func, config):
        self.name = name
        self.func = func
        self.config = config

    def __call__(self, event, content):
        auth_request = self._transform_event(event)
        result = self.func(auth_request)
        if isinstance(result, AuthResponse):
            return result.to_dict(auth_request)
        return result

    def _transform_event(self, event):
        return AuthRequest(event['type'],
                           event['authorizationToken'],
                           event['methodArn'])


class AuthRequest(object):
    def __init__(self, auth_type, token, method_arn):
        self.auth_type = auth_type
        self.token = token
        self.method_arn = method_arn


class AuthResponse(object):
    ALL_HTTP_METHODS = ['DELETE', 'HEAD', 'OPTIONS',
                        'PATCH', 'POST', 'PUT', 'GET']

    def __init__(self, routes, principal_id, context=None):
        self.routes = routes
        self.principal_id = principal_id
        # The request is used to generate full qualified ARNs
        # that we need for the resource portion of the returned
        # policy.
        if context is None:
            context = {}
        self.context = context

    def to_dict(self, request):
        return {
            'context': self.context,
            'principalId': self.principal_id,
            'policyDocument': self._generate_policy(request),
        }

    def _generate_policy(self, request):
        allowed_resources = self._generate_allowed_resources(request)
        return {
            'Version': '2012-10-17',
            'Statement': [
                {
                    'Action': 'execute-api:Invoke',
                    'Effect': 'Allow',
                    'Resource': allowed_resources,
                }
            ]
        }

    def _generate_allowed_resources(self, request):
        allowed_resources = []
        for route in self.routes:
            if isinstance(route, AuthRoute):
                methods = route.methods
                path = route.path
            elif route == '*':
                # A string route of '*' means that all paths and
                # all HTTP methods are now allowed.
                methods = ['*']
                path = '*'
            else:
                # If 'route' is just a string, then they've
                # opted not to use the AuthRoute(), so we'll
                # generate a policy that allows all HTTP methods.
                methods = ['*']
                path = route
            for method in methods:
                allowed_resources.append(
                    self._generate_arn(path, request, method))
        return allowed_resources

    def _generate_arn(self, route, request, method='*'):
        incoming_arn = request.method_arn
        parts = incoming_arn.rsplit(':', 1)
        # "arn:aws:execute-api:us-west-2:123:rest-api-id/dev/GET/needs/auth"
        # Then we pull out the rest-api-id and stage, such that:
        #   base = ['rest-api-id', 'stage']
        base = parts[-1].split('/')[:2]
        # Now we add in the path components and rejoin everything
        # back together to make a full arn.
        # We're also assuming all HTTP methods (via '*') for now.
        # To support per HTTP method routes the API will need to be updated.
        # We also need to strip off the leading ``/`` so it can be
        # '/'.join(...)'d properly.
        base.extend([method, route[1:]])
        last_arn_segment = '/'.join(base)
        if route == '/' or route == '*':
            # We have to special case the '/' case.  For whatever
            # reason, API gateway adds an extra '/' to the method_arn
            # of the auth request, so we need to do the same thing.
            # We also have to handle the '*' case which is for wildcards
            last_arn_segment += route
        final_arn = '%s:%s' % (parts[0], last_arn_segment)
        return final_arn


class AuthRoute(object):
    def __init__(self, path, methods):
        self.path = path
        self.methods = methods


class EventSource(object):
    def __init__(self, name, handler_string):
        self.name = name
        self.handler_string = handler_string


class CloudWatchEventSource(EventSource):
    def __init__(self, name, handler_string, schedule_expression):
        super(CloudWatchEventSource, self).__init__(name, handler_string)
        self.schedule_expression = schedule_expression


class ScheduleExpression(object):
    def to_string(self):
        raise NotImplementedError("to_string")


class Rate(ScheduleExpression):
    MINUTES = 'MINUTES'
    HOURS = 'HOURS'
    DAYS = 'DAYS'

    def __init__(self, value, unit):
        self.value = value
        self.unit = unit

    def to_string(self):
        unit = self.unit.lower()
        if self.value == 1:
            # Remove the 's' from the end if it's singular.
            # This is required by the cloudwatch events API.
            unit = unit[:-1]
        return 'rate(%s %s)' % (self.value, unit)


class Cron(ScheduleExpression):
    def __init__(self, minutes, hours, day_of_month, month, day_of_week, year):
        self.minutes = minutes
        self.hours = hours
        self.day_of_month = day_of_month
        self.month = month
        self.day_of_week = day_of_week
        self.year = year

    def to_string(self):
        return 'cron(%s %s %s %s %s %s)' % (
            self.minutes,
            self.hours,
            self.day_of_month,
            self.month,
            self.day_of_week,
            self.year,
        )


class ScheduledEventHandler(object):
    def __init__(self, func):
        self.func = func

    def __call__(self, event, context):
        event_obj = self._convert_to_obj(event)
        return self.func(event_obj)

    def _convert_to_obj(self, event_dict):
        return CloudWatchEvent(event_dict)


class CloudWatchEvent(object):
    def __init__(self, event_dict):
        self.version = event_dict['version']
        self.account = event_dict['account']
        self.region = event_dict['region']
        self.detail = event_dict['detail']
        self.detail_type = event_dict['detail-type']
        self.source = event_dict['source']
        self.time = event_dict['time']
        self.event_id = event_dict['id']
        self.resources = event_dict['resources']
        self._event_dict = event_dict

    def to_dict(self):
        return self._event_dict


class LambdaFunction(object):
    def __init__(self, func, name, handler_string):
        self.func = func
        self.name = name
        self.handler_string = handler_string

    def __call__(self, event, context):
        return self.func(event, context)
