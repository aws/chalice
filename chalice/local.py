"""Dev server used for running a chalice app locally.

This is intended only for local development purposes.

"""
import functools
from collections import namedtuple
from BaseHTTPServer import HTTPServer
from BaseHTTPServer import BaseHTTPRequestHandler


from chalice.app import Chalice  # noqa
from typing import List, Any, Dict, Tuple, Callable  # noqa

try:
    from urllib.parse import urlparse, parse_qs
except ImportError:
    from urlparse import urlparse, parse_qs


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
    """Convert an HTTP request to an event dict used by lambda."""
    def __init__(self, route_matcher):
        # type: (RouteMatcher) -> None
        self._route_matcher = route_matcher

    def create_lambda_event(self, method, path, headers, body=None):
        # type: (str, str, Dict[str, str], str) -> EventType
        view_route = self._route_matcher.match_route(path)
        if body is None:
            body = '{}'
        return {
            'requestContext': {
                'httpMethod': method,
                'resourcePath': view_route.route,
            },
            'headers': dict(headers),
            'queryStringParameters': view_route.query_params,
            'body': body,
            'pathParameters': view_route.captured,
            'stageVariables': {},
        }


class ChaliceRequestHandler(BaseHTTPRequestHandler):

    protocol = 'HTTP/1.1'

    def __init__(self, request, client_address, server, app_object):
        # type: (bytes, Tuple[str, int], HTTPServer, Chalice) -> None
        self.app_object = app_object
        self.event_converter = LambdaEventConverter(
            RouteMatcher(list(app_object.routes)))
        BaseHTTPRequestHandler.__init__(
            self, request, client_address, server)  # type: ignore

    def _generic_handle(self):
        # type: () -> None
        lambda_event = self._generate_lambda_event()
        self._do_invoke_view_function(lambda_event)

    def _do_invoke_view_function(self, lambda_event):
        # type: (EventType) -> None
        lambda_context = None
        response = self.app_object(lambda_event, lambda_context)
        self._send_http_response(lambda_event, response)

    def _send_http_response(self, lambda_event, response):
        # type: (EventType, Dict[str, Any]) -> None
        self.send_response(response['statusCode'])
        self.send_header('Content-Length', str(len(response['body'])))
        self.send_header(
            'Content-Type',
            response['headers'].get('Content-Type', 'application/json'))
        headers = response['headers']
        for header in headers:
            self.send_header(header, headers[header])
        self.end_headers()
        self.wfile.write(response['body'])

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
            self._send_autogen_options_response()

    def _cors_enabled_for_route(self, lambda_event):
        # type: (EventType) -> bool
        route_key = lambda_event['requestContext']['resourcePath']
        route_entry = self.app_object.routes[route_key]
        return route_entry.cors

    def _has_user_defined_options_method(self, lambda_event):
        # type: (EventType) -> bool
        route_key = lambda_event['requestContext']['resourcePath']
        route_entry = self.app_object.routes[route_key]
        return 'OPTIONS' in route_entry.methods

    def _send_autogen_options_response(self):
        # type:() -> None
        self.send_response(200)
        self.send_header(
            'Access-Control-Allow-Headers',
            'Content-Type,X-Amz-Date,Authorization,'
            'X-Api-Key,X-Amz-Security-Token'
        )
        self.send_header('Access-Control-Allow-Methods',
                         'GET,HEAD,PUT,POST,OPTIONS')
        self.send_header('Access-Control-Allow-Origin', '*')
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
        print "Serving on localhost:%s" % self.port
        self.server.serve_forever()
