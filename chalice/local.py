"""Dev server used for running a chalice app locally.

This is intended only for local development purposes.

"""
import json
import functools
from collections import namedtuple
import BaseHTTPServer

from chalice import ChaliceViewError
from chalice.app import ChaliceError
from typing import List  # noqa


MatchResult = namedtuple('MatchResult', ['route', 'captured'])


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
        parts = url.split('/')
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
                    return MatchResult(route_url, captured)
        raise ValueError("No matching route found for: %s" % url)


class LambdaEventConverter(object):
    """Convert an HTTP request to an event dict used by lambda."""
    def __init__(self, route_matcher):
        # type: (RouteMatcher) -> None
        self._route_matcher = route_matcher

    def create_lambda_event(self, method, path, headers, body=None):
        view_route = self._route_matcher.match_route(path)
        if body is None:
            body = '{}'
        json_body = {}
        if headers.get('content-type', '') == 'application/json':
            json_body = json.loads(body)
        base64_body = body.encode('base64')
        return {
            'context': {
                'http-method': method,
                'resource-path': view_route.route,
            },
            'params': {
                'header': dict(headers),
                'path': view_route.captured,
                'querystring': {},
            },
            'body-json': json_body,
            'base64-body': base64_body,
            'stage-variables': {},
        }


class ChaliceRequestHandler(BaseHTTPServer.BaseHTTPRequestHandler):

    protocol = 'HTTP/1.1'

    def __init__(self, request, client_address, server, app_object):
        self.app_object = app_object
        self.event_converter = LambdaEventConverter(
            RouteMatcher(list(app_object.routes)))
        BaseHTTPServer.BaseHTTPRequestHandler.__init__(
            self, request, client_address, server)

    def _generic_handle(self):
        lambda_event = self._generate_lambda_event()
        self._do_invoke_view_function(lambda_event)

    def _do_invoke_view_function(self, lambda_event):
        lambda_context = None
        try:
            response = self.app_object(lambda_event, lambda_context)
            self._send_http_response(lambda_event, response)
        except ChaliceViewError as e:
            response = {
                'Code': e.__class__.__name__,
                'Message': str(e)
            }
            self._send_http_response(lambda_event, response,
                                     status_code=e.STATUS_CODE)
        except ChaliceError as e:
            # This is a bit unfortunate, but in many cases
            # API gateway will return a 403 instead of a 500
            # or a 404.  In this case there's a slight difference
            # in behavior in local mode where any ChaliceError
            # just gets a plain old 500 response.
            response = {'message': str(e)}
            self._send_http_response(lambda_event, response,
                                     status_code=500)

    def _send_http_response(self, lambda_event, response, status_code=200):
        json_response = json.dumps(response)
        self.send_response(status_code)
        self.send_header('Content-Length', str(len(json_response)))
        self.send_header('Content-Type', 'application/json')
        if self._cors_enabled_for_route(lambda_event):
            self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(json_response)

    def _generate_lambda_event(self):
        content_length = int(self.headers.get('content-length', '0'))
        body = None
        if content_length > 0:
            body = self.rfile.read(content_length)
        lambda_event = self.event_converter.create_lambda_event(
            method=self.command, path=self.path, headers=dict(self.headers),
            body=body,
        )
        return lambda_event

    do_GET = do_PUT = do_POST = do_HEAD = _generic_handle

    def do_OPTIONS(self):
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
        route_key = lambda_event['context']['resource-path']
        route_entry = self.app_object.routes[route_key]
        return route_entry.cors

    def _has_user_defined_options_method(self, lambda_event):
        route_key = lambda_event['context']['resource-path']
        route_entry = self.app_object.routes[route_key]
        return 'OPTIONS' in route_entry.methods

    def _send_autogen_options_response(self):
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
    def __init__(self, app_object, handler_cls=ChaliceRequestHandler,
                 server_cls=BaseHTTPServer.HTTPServer):
        self.app_object = app_object
        self._wrapped_handler = functools.partial(
            handler_cls, app_object=app_object)
        self.server = server_cls(('', 8000), self._wrapped_handler)

    def handle_single_request(self):
        self.server.handle_request()

    def serve_forever(self):
        print "Serving on localhost:8000"
        self.server.serve_forever()
