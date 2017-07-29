"""Dev server used for running a chalice app locally.

This is intended only for local development purposes.

"""
from __future__ import print_function
import base64
import functools
from collections import namedtuple

from six.moves.BaseHTTPServer import HTTPServer
from six.moves.BaseHTTPServer import BaseHTTPRequestHandler
from typing import List, Any, Dict, Tuple, Callable  # noqa

from chalice.app import Chalice, CORSConfig  # noqa
from chalice.compat import urlparse, parse_qs


MatchResult = namedtuple('MatchResult', ['route', 'captured', 'query_params'])
EventType = Dict[str, Any]
HandlerCls = Callable[..., 'ChaliceRequestHandler']
ServerCls = Callable[..., 'HTTPServer']


def create_local_server(app_obj, port):
    # type: (Chalice, int) -> LocalDevServer
    return LocalDevServer(app_obj, port)


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
        query_params = {k: v[0] for k, v in parse_qs(parsed_url.query).items()}
        parts = parsed_url.path.split('/')
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
            },
            'headers': dict(headers),
            'queryStringParameters': view_route.query_params,
            'pathParameters': view_route.captured,
            'stageVariables': {},
        }
        if body is None:
            event['body'] = '{}'
        elif self._is_binary(headers):
            event['body'] = base64.b64encode(body).decode('ascii')
            event['isBase64Encoded'] = True
        else:
            event['body'] = body
        return event


class ChaliceRequestHandler(BaseHTTPRequestHandler):

    protocol = 'HTTP/1.1'

    def __init__(self, request, client_address, server, app_object):
        # type: (bytes, Tuple[str, int], HTTPServer, Chalice) -> None
        self.app_object = app_object
        self.event_converter = LambdaEventConverter(
            RouteMatcher(list(app_object.routes)),
            self.app_object.api.binary_types
        )
        BaseHTTPRequestHandler.__init__(
            self, request, client_address, server)  # type: ignore

    def _generic_handle(self):
        # type: () -> None
        lambda_event = self._generate_lambda_event()
        self._do_invoke_view_function(lambda_event)

    def _handle_binary(self, response):
        # type: (Dict[str,Any]) -> Dict[str,Any]
        if response.get('isBase64Encoded'):
            body = base64.b64decode(response['body'])
            response['body'] = body
        return response

    def _do_invoke_view_function(self, lambda_event):
        # type: (EventType) -> None
        lambda_context = None
        response = self.app_object(lambda_event, lambda_context)
        response = self._handle_binary(response)
        self._send_http_response(lambda_event, response)

    def _send_http_response(self, lambda_event, response):
        # type: (EventType, Dict[str, Any]) -> None
        self.send_response(response['statusCode'])
        self.send_header('Content-Length', str(len(response['body'])))
        content_type = response['headers'].pop(
            'Content-Type', 'application/json')
        self.send_header('Content-Type', content_type)
        headers = response['headers']
        for header in headers:
            self.send_header(header, headers[header])
        self.end_headers()
        body = response['body']
        if not isinstance(body, bytes):
            body = body.encode('utf-8')
        self.wfile.write(body)

    def _generate_lambda_event(self):
        # type: () -> EventType
        content_length = int(self.headers.get('content-length', '0'))
        body = None
        if content_length > 0:
            body = self.rfile.read(content_length)
        # mypy doesn't like dict(self.headers) so I had to use a
        # dictcomp instead to make it happy.
        converted_headers = {key: value for key, value in self.headers.items()}
        lambda_event = self.event_converter.create_lambda_event(
            method=self.command, path=self.path, headers=converted_headers,
            body=body,
        )
        return lambda_event

    do_GET = do_PUT = do_POST = do_HEAD = do_DELETE = do_PATCH = \
        _generic_handle

    def do_OPTIONS(self):
        # type: () -> None
        # This can either be because the user's provided an OPTIONS method
        # *or* this is a preflight request, which chalice automatically
        # sets up for you.
        lambda_event = self._generate_lambda_event()
        if self._has_user_defined_options_method(lambda_event):
            self._do_invoke_view_function(lambda_event)
        else:
            # Otherwise this is a preflight request which we automatically
            # generate.
            self._send_autogen_options_response(lambda_event)

    def _has_user_defined_options_method(self, lambda_event):
        # type: (EventType) -> bool
        route_key = lambda_event['requestContext']['resourcePath']
        return 'OPTIONS' in self.app_object.routes[route_key]

    def _send_autogen_options_response(self, lambda_event):
        # type:(EventType) -> None
        route_key = lambda_event['requestContext']['resourcePath']
        route_dict = self.app_object.routes[route_key]
        route_methods = list(route_dict.keys())

        # Chalice ensures that routes with multiple views have the same
        # CORS configuration, so if any view has a CORS Config we can use
        # that config since they will all be the same.
        cors_config = route_dict[route_methods[0]].cors
        cors_headers = cors_config.get_access_control_headers()

        # The keys will be ordered in python 3 but in python 2 they will not
        # be. To assert this header is sent correctly we need to introduce
        # order by sorting the methods list. We also need to add OPTIONS since
        # it cannot be added directly to the route, but it will be added to
        # the API Gateway definition, so its added afterward.
        route_methods.append('OPTIONS')
        route_methods = sorted(route_methods)

        # The Access-Control-Allow-Methods header is not added by the
        # CORSConfig object it is added to the API Gateway route during
        # deployment, so we need to manually add those headers here.
        cors_headers.update({
            'Access-Control-Allow-Methods': '%s' % ','.join(route_methods)
        })

        self.send_response(200)
        for k, v in cors_headers.items():
            self.send_header(k, v)
        self.end_headers()


class LocalDevServer(object):
    def __init__(self, app_object, port, handler_cls=ChaliceRequestHandler,
                 server_cls=HTTPServer):
        # type: (Chalice, int, HandlerCls, ServerCls) -> None
        self.app_object = app_object
        self.port = port
        self._wrapped_handler = functools.partial(
            handler_cls, app_object=app_object)
        self.server = server_cls(('', port), self._wrapped_handler)

    def handle_single_request(self):
        # type: () -> None
        self.server.handle_request()

    def serve_forever(self):
        # type: () -> None
        print("Serving on localhost:%s" % self.port)
        self.server.serve_forever()
