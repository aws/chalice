"""Chalice app and routing code."""
import re
import sys
import logging
import json
import traceback
import decimal
from collections import Mapping

# Implementation note:  This file is intended to be a standalone file
# that gets copied into the lambda deployment package.  It has no dependencies
# on other parts of chalice so it can stay small and lightweight, with minimal
# startup overhead.


_PARAMS = re.compile('{\w+}')


def handle_decimals(obj):
    # Lambda will automatically serialize decimals so we need
    # to support that as well.
    if isinstance(obj, decimal.Decimal):
        return float(obj)
    return obj


def error_response(message, error_code, http_status_code):
    body = {'Code': error_code, 'Message': message}
    response = Response(body=body, status_code=http_status_code)
    return response.to_dict()


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


class ConflictError(ChaliceViewError):
    STATUS_CODE = 409


class TooManyRequestsError(ChaliceViewError):
    STATUS_CODE = 429


ALL_ERRORS = [
    ChaliceViewError,
    BadRequestError,
    NotFoundError,
    UnauthorizedError,
    ForbiddenError,
    ConflictError,
    TooManyRequestsError]


class CaseInsensitiveMapping(Mapping):
    """Case insensitive and read-only mapping."""

    def __init__(self, mapping):
        self._dict = {k.lower(): v for k, v in mapping.items()}

    def __getitem__(self, key):
        return self._dict[key.lower()]

    def __iter__(self):
        return iter(self._dict)

    def __len__(self):
        return len(self._dict)

    def __repr__(self):
        return 'CaseInsensitiveMapping(%s)' % repr(self._dict)


class Request(object):
    """The current request from API gateway."""

    def __init__(self, query_params, headers, uri_params, method, body,
                 context, stage_vars):
        self.query_params = query_params
        self.headers = CaseInsensitiveMapping(headers)
        self.uri_params = uri_params
        self.method = method
        self.raw_body = body
        #: The parsed JSON from the body.  This value should
        #: only be set if the Content-Type header is application/json,
        #: which is the default content type value in chalice.
        self._json_body = None
        self.context = context
        self.stage_vars = stage_vars

    @property
    def json_body(self):
        if self.headers.get('content-type', '').startswith('application/json'):
            if self._json_body is None:
                self._json_body = json.loads(self.raw_body)
            return self._json_body

    def to_dict(self):
        copied = self.__dict__.copy()
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

    def to_dict(self):
        body = self.body
        if not isinstance(body, str):
            body = json.dumps(body, default=handle_decimals)
        return {
            'headers': self.headers,
            'statusCode': self.status_code,
            'body': body,
        }


class RouteEntry(object):

    def __init__(self, view_function, view_name, path, methods,
                 authorization_type=None, authorizer_id=None,
                 api_key_required=None, content_types=None,
                 cors=False):
        self.view_function = view_function
        self.view_name = view_name
        self.uri_pattern = path
        self.methods = methods
        self.authorization_type = authorization_type
        self.authorizer_id = authorizer_id
        self.api_key_required = api_key_required
        #: A list of names to extract from path:
        #: e.g, '/foo/{bar}/{baz}/qux -> ['bar', 'baz']
        self.view_args = self._parse_view_args()
        self.content_types = content_types
        self.cors = cors

    def _parse_view_args(self):
        if '{' not in self.uri_pattern:
            return []
        # The [1:-1] slice is to remove the braces
        # e.g {foobar} -> foobar
        results = [r[1:-1] for r in _PARAMS.findall(self.uri_pattern)]
        return results

    def __eq__(self, other):
        return self.__dict__ == other.__dict__


class Chalice(object):

    FORMAT_STRING = '%(name)s - %(levelname)s - %(message)s'

    def __init__(self, app_name, configure_logs=True):
        self.app_name = app_name
        self.routes = {}
        self.current_request = None
        self.debug = False
        self.configure_logs = configure_logs
        self.log = logging.getLogger(self.app_name)
        if self.configure_logs:
            self._configure_logging()

    def _configure_logging(self):
        log = logging.getLogger(self.app_name)
        if self._already_configured(log):
            return
        handler = logging.StreamHandler(sys.stdout)
        # Timestamp is handled by lambda itself so the
        # default FORMAT_STRING doesn't need to include it.
        formatter = logging.Formatter(self.FORMAT_STRING)
        handler.setFormatter(formatter)
        log.propagate = False
        if self.debug:
            level = logging.DEBUG
        else:
            level = logging.ERROR
        log.setLevel(level)
        log.addHandler(handler)

    def _already_configured(self, log):
        if not log.handlers:
            return False
        for handler in log.handlers:
            if isinstance(handler, logging.StreamHandler):
                if handler.stream == sys.stdout:
                    return True
        return False

    def route(self, path, **kwargs):
        def _register_view(view_func):
            self._add_route(path, view_func, **kwargs)
            return view_func
        return _register_view

    def _add_route(self, path, view_func, **kwargs):
        name = kwargs.pop('name', view_func.__name__)
        methods = kwargs.pop('methods', ['GET'])
        authorization_type = kwargs.pop('authorization_type', None)
        authorizer_id = kwargs.pop('authorizer_id', None)
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

        if path in self.routes:
            raise ValueError(
                "Duplicate route detected: '%s'\n"
                "URL paths must be unique." % path)
        entry = RouteEntry(view_func, name, path, methods, authorization_type,
                           authorizer_id, api_key_required,
                           content_types, cors)
        self.routes[path] = entry

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
        route_entry = self.routes[resource_path]
        if http_method not in route_entry.methods:
            return error_response(
                error_code='MethodNotAllowedError',
                message='Unsupported method: %s' % http_method,
                http_status_code=405)
        view_function = route_entry.view_function
        function_args = [event['pathParameters'][name]
                         for name in route_entry.view_args]
        self.current_request = Request(event['queryStringParameters'],
                                       event['headers'],
                                       event['pathParameters'],
                                       event['requestContext']['httpMethod'],
                                       event['body'],
                                       event['requestContext'],
                                       event['stageVariables'])
        # We're doing the header validation after creating the request
        # so can leverage the case insensitive dict that the Request class
        # uses for headers.
        if route_entry.content_types:
            content_type = self.current_request.headers.get(
                'content-type', 'application/json')
            if content_type not in route_entry.content_types:
                return error_response(
                    error_code='UnsupportedMediaType',
                    message='Unsupported media type: %s' % content_type,
                    http_status_code=415,
                )
        response = self._get_view_function_response(view_function,
                                                    function_args)
        if self._cors_enabled_for_route(route_entry):
            self._add_cors_headers(response)
        return response.to_dict()

    def _get_view_function_response(self, view_function, function_args):
        try:
            response = self._invoke_view_function(view_function, function_args)
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
        if not isinstance(response, Response):
            response = Response(body=response)
        self._validate_response(response)
        return response

    def _invoke_view_function(self, view_function, function_args):
        response = view_function(*function_args)
        self._validate_response(response)
        return response

    def _validate_response(self, response):
        if isinstance(response, Response):
            for header, value in response.headers.items():
                if '\n' in value:
                    raise ChaliceError("Bad value for header '%s': %r" %
                                       (header, value))

    def _cors_enabled_for_route(self, route_entry):
        return route_entry.cors

    def _add_cors_headers(self, response):
        response.headers['Access-Control-Allow-Origin'] = '*'
