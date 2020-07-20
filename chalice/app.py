"""Chalice app and routing code."""
# pylint: disable=too-many-lines,ungrouped-imports
import re
import sys
import os
import logging
import json
import traceback
import decimal
import base64
import copy
from collections import defaultdict


__version__ = '1.16.0'
_PARAMS = re.compile(r'{\w+}')

# Implementation note:  This file is intended to be a standalone file
# that gets copied into the lambda deployment package.  It has no dependencies
# on other parts of chalice so it can stay small and lightweight, with minimal
# startup overhead.  This also means we need to handle py2/py3 compat issues
# directly in this file instead of copying over compat.py
try:
    from urllib.parse import unquote_plus
    from collections.abc import Mapping
    from collections.abc import MutableMapping

    unquote_str = unquote_plus

    # In python 3 string and bytes are different so we explicitly check
    # for both.
    _ANY_STRING = (str, bytes)
except ImportError:
    from urllib import unquote_plus
    from collections import Mapping
    from collections import MutableMapping

    # This is borrowed from botocore/compat.py
    def unquote_str(value, encoding='utf-8'):
        # In python2, unquote() gives us a string back that has the urldecoded
        # bits, but not the unicode parts.  We need to decode this manually.
        # unquote has special logic in which if it receives a unicode object it
        # will decode it to latin1.  This is hard coded.  To avoid this, we'll
        # encode the string with the passed in encoding before trying to
        # unquote it.
        byte_string = value.encode(encoding)
        return unquote_plus(byte_string).decode(encoding)
    # In python 2 there is a base class for the string types that we can check
    # for. It was removed in python 3 so it will cause a name error.
    _ANY_STRING = (basestring, bytes)  # noqa pylint: disable=E0602


def handle_extra_types(obj):
    # Lambda will automatically serialize decimals so we need
    # to support that as well.
    if isinstance(obj, decimal.Decimal):
        return float(obj)
    # This is added for backwards compatibility.
    # It will keep only the last value for every key as it used to.
    if isinstance(obj, MultiDict):
        return dict(obj)
    raise TypeError('Object of type %s is not JSON serializable'
                    % obj.__class__.__name__)


def error_response(message, error_code, http_status_code, headers=None):
    body = {'Code': error_code, 'Message': message}
    response = Response(body=body, status_code=http_status_code,
                        headers=headers)

    return response.to_dict()


def _matches_content_type(content_type, valid_content_types):
    # If '*/*' is in the Accept header or the valid types,
    # then all content_types match. Otherwise see of there are any common types
    content_type = content_type.lower()
    valid_content_types = [x.lower() for x in valid_content_types]
    return '*/*' in content_type or \
        '*/*' in valid_content_types or \
        _content_type_header_contains(content_type, valid_content_types)


def _content_type_header_contains(content_type_header, valid_content_types):
    content_type_header_parts = [
        p.strip() for p in
        re.split('[,;]', content_type_header)
    ]
    valid_parts = set(valid_content_types).intersection(
        content_type_header_parts
    )
    return len(valid_parts) > 0


class ChaliceError(Exception):
    pass


class WebsocketDisconnectedError(ChaliceError):
    def __init__(self, connection_id):
        self.connection_id = connection_id


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


class MultiDict(MutableMapping):  # pylint: disable=too-many-ancestors
    """A mapping of key to list of values.

    Accessing it in the usual way will return the last value in the list.
    Calling getlist will return a list of all the values associated with
    the same key.
    """

    def __init__(self, mapping):
        if mapping is None:
            mapping = {}

        self._dict = mapping

    def __getitem__(self, k):
        try:
            return self._dict[k][-1]
        except IndexError:
            raise KeyError(k)

    def __setitem__(self, k, v):
        self._dict[k] = [v]

    def __delitem__(self, k):
        del self._dict[k]

    def getlist(self, k):
        return list(self._dict[k])

    def __len__(self):
        return len(self._dict)

    def __iter__(self):
        return iter(self._dict)

    def __repr__(self):
        return 'MultiDict(%s)' % self._dict

    def __str__(self):
        return repr(self)


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
    scopes = []

    def to_swagger(self):
        raise NotImplementedError("to_swagger")

    def with_scopes(self, scopes):
        raise NotImplementedError("with_scopes")


class IAMAuthorizer(Authorizer):

    _AUTH_TYPE = 'aws_iam'

    def __init__(self):
        self.name = 'sigv4'
        self.scopes = []

    def to_swagger(self):
        return {
            'in': 'header',
            'type': 'apiKey',
            'name': 'Authorization',
            'x-amazon-apigateway-authtype': 'awsSigv4',
        }

    def with_scopes(self, scopes):
        raise NotImplementedError("with_scopes")


class CognitoUserPoolAuthorizer(Authorizer):

    _AUTH_TYPE = 'cognito_user_pools'

    def __init__(self, name, provider_arns, header='Authorization',
                 scopes=None):
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
        self.scopes = scopes or []

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

    def with_scopes(self, scopes):
        authorizer_with_scopes = copy.deepcopy(self)
        authorizer_with_scopes.scopes = scopes
        return authorizer_with_scopes


class CustomAuthorizer(Authorizer):

    _AUTH_TYPE = 'custom'

    def __init__(self, name, authorizer_uri, ttl_seconds=300,
                 header='Authorization', invoke_role_arn=None, scopes=None):
        self.name = name
        self._header = header
        self._authorizer_uri = authorizer_uri
        self._ttl_seconds = ttl_seconds
        self._invoke_role_arn = invoke_role_arn
        self.scopes = scopes or []

    def to_swagger(self):
        swagger = {
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
        if self._invoke_role_arn is not None:
            swagger['x-amazon-apigateway-authorizer'][
                'authorizerCredentials'] = self._invoke_role_arn
        return swagger

    def with_scopes(self, scopes):
        authorizer_with_scopes = copy.deepcopy(self)
        authorizer_with_scopes.scopes = scopes
        return authorizer_with_scopes


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
        return False


class Request(object):
    """The current request from API gateway."""

    def __init__(self, query_params, headers, uri_params, method, body,
                 context, stage_vars, is_base64_encoded):
        self.query_params = None if query_params is None \
            else MultiDict(query_params)
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
        if copied['query_params'] is not None:
            copied['query_params'] = dict(copied['query_params'])
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
            body = json.dumps(body, separators=(',', ':'),
                              default=handle_extra_types)
        single_headers, multi_headers = self._sort_headers(self.headers)
        response = {
            'headers': single_headers,
            'multiValueHeaders': multi_headers,
            'statusCode': self.status_code,
            'body': body
        }
        if binary_types is not None:
            self._b64encode_body_if_needed(response, binary_types)
        return response

    def _sort_headers(self, all_headers):
        multi_headers = {}
        single_headers = {}
        for name, value in all_headers.items():
            if isinstance(value, list):
                multi_headers[name] = value
            else:
                single_headers[name] = value
        return single_headers, multi_headers

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
                body = body if isinstance(body, bytes) \
                    else body.encode('utf-8')
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
        'application/octet-stream', 'application/x-tar', 'application/zip',
        'audio/basic', 'audio/ogg', 'audio/mp4', 'audio/mpeg', 'audio/wav',
        'audio/webm', 'image/png', 'image/jpg', 'image/jpeg', 'image/gif',
        'video/ogg', 'video/mpeg', 'video/webm',
    ]

    def __init__(self):
        self.binary_types = self.default_binary_types
        self.cors = False

    @property
    def default_binary_types(self):
        return list(self._DEFAULT_BINARY_TYPES)


class WebsocketAPI(object):
    _WEBSOCKET_ENDPOINT_TEMPLATE = 'https://{domain_name}/{stage}'

    def __init__(self):
        self.session = None
        self._endpoint = None
        self._client = None

    def configure(self, domain_name, stage):
        if self._endpoint is not None:
            return
        self._endpoint = self._WEBSOCKET_ENDPOINT_TEMPLATE.format(
            domain_name=domain_name,
            stage=stage,
        )

    def _get_client(self):
        if self.session is None:
            raise ValueError(
                'Assign app.websocket_api.session to a boto3 session before '
                'using the WebsocketAPI'
            )
        if self._endpoint is None:
            raise ValueError(
                'WebsocketAPI.configure must be called before using the '
                'WebsocketAPI'
            )
        if self._client is None:
            self._client = self.session.client(
                'apigatewaymanagementapi',
                endpoint_url=self._endpoint,
            )
        return self._client

    def send(self, connection_id, message):
        client = self._get_client()
        try:
            client.post_to_connection(
                ConnectionId=connection_id,
                Data=message,
            )
        except client.exceptions.GoneException:
            raise WebsocketDisconnectedError(connection_id)

    def close(self, connection_id):
        client = self._get_client()
        try:
            client.delete_connection(
                ConnectionId=connection_id,
            )
        except client.exceptions.GoneException:
            raise WebsocketDisconnectedError(connection_id)

    def info(self, connection_id):
        client = self._get_client()
        try:
            return client.get_connection(
                ConnectionId=connection_id,
            )
        except client.exceptions.GoneException:
            raise WebsocketDisconnectedError(connection_id)


class DecoratorAPI(object):
    def authorizer(self, ttl_seconds=None, execution_role=None, name=None):
        return self._create_registration_function(
            handler_type='authorizer',
            name=name,
            registration_kwargs={
                'ttl_seconds': ttl_seconds, 'execution_role': execution_role,
            }
        )

    def on_s3_event(self, bucket, events=None,
                    prefix=None, suffix=None, name=None):
        return self._create_registration_function(
            handler_type='on_s3_event',
            name=name,
            registration_kwargs={
                'bucket': bucket, 'events': events,
                'prefix': prefix, 'suffix': suffix,
            }
        )

    def on_sns_message(self, topic, name=None):
        return self._create_registration_function(
            handler_type='on_sns_message',
            name=name,
            registration_kwargs={'topic': topic}
        )

    def on_sqs_message(self, queue, batch_size=1, name=None):
        return self._create_registration_function(
            handler_type='on_sqs_message',
            name=name,
            registration_kwargs={'queue': queue, 'batch_size': batch_size}
        )

    def on_cw_event(self, event_pattern, name=None):
        return self._create_registration_function(
            handler_type='on_cw_event',
            name=name,
            registration_kwargs={'event_pattern': event_pattern}
        )

    def schedule(self, expression, name=None, description=''):
        return self._create_registration_function(
            handler_type='schedule',
            name=name,
            registration_kwargs={'expression': expression,
                                 'description': description},
        )

    def route(self, path, **kwargs):
        return self._create_registration_function(
            handler_type='route',
            name=kwargs.pop('name', None),
            # This looks a little weird taking kwargs as a key,
            # but we want to preserve keep the **kwargs signature
            # in the route decorator.
            registration_kwargs={'path': path, 'kwargs': kwargs},
        )

    def lambda_function(self, name=None):
        return self._create_registration_function(
            handler_type='lambda_function', name=name)

    def on_ws_connect(self, name=None):
        return self._create_registration_function(
            handler_type='on_ws_connect',
            name=name,
            registration_kwargs={'route_key': '$connect'},
        )

    def on_ws_disconnect(self, name=None):
        return self._create_registration_function(
            handler_type='on_ws_disconnect',
            name=name,
            registration_kwargs={'route_key': '$disconnect'},
        )

    def on_ws_message(self, name=None):
        return self._create_registration_function(
            handler_type='on_ws_message',
            name=name,
            registration_kwargs={'route_key': '$default'},
        )

    def _create_registration_function(self, handler_type, name=None,
                                      registration_kwargs=None):
        def _register_handler(user_handler):
            handler_name = name
            if handler_name is None:
                handler_name = user_handler.__name__
            if registration_kwargs is not None:
                kwargs = registration_kwargs
            else:
                kwargs = {}
            wrapped = self._wrap_handler(handler_type, handler_name,
                                         user_handler)
            self._register_handler(handler_type, handler_name,
                                   user_handler, wrapped, kwargs)
            return wrapped
        return _register_handler

    def _wrap_handler(self, handler_type, handler_name, user_handler):
        event_classes = {
            'on_s3_event': S3Event,
            'on_sns_message': SNSEvent,
            'on_sqs_message': SQSEvent,
            'on_cw_event': CloudWatchEvent,
            'schedule': CloudWatchEvent,
        }
        if handler_type in event_classes:
            return EventSourceHandler(
                user_handler, event_classes[handler_type])

        websocket_event_classes = [
            'on_ws_connect',
            'on_ws_message',
            'on_ws_disconnect',
        ]
        if handler_type in websocket_event_classes:
            return WebsocketEventSourceHandler(
                user_handler, WebsocketEvent,
                self.websocket_api  # pylint: disable=no-member
            )
        if handler_type == 'authorizer':
            # Authorizer is special cased and doesn't quite fit the
            # EventSourceHandler pattern.
            return ChaliceAuthorizer(handler_name, user_handler)
        return user_handler

    def _register_handler(self, handler_type, name,
                          user_handler, wrapped_handler, kwargs, options=None):
        raise NotImplementedError("_register_handler")


class _HandlerRegistration(object):

    def __init__(self):
        self.routes = defaultdict(dict)
        self.websocket_handlers = {}
        self.builtin_auth_handlers = []
        self.event_sources = []
        self.pure_lambda_functions = []
        self.api = APIGateway()

    def _do_register_handler(self, handler_type, name, user_handler,
                             wrapped_handler, kwargs, options=None):
        url_prefix = None
        name_prefix = None
        module_name = 'app'
        if options is not None:
            name_prefix = options.get('name_prefix')
            if name_prefix is not None:
                name = name_prefix + name
            url_prefix = options.get('url_prefix')
            if url_prefix is not None:
                # Move url_prefix into kwargs so only the
                # route() handler gets a url_prefix kwarg.
                kwargs['url_prefix'] = url_prefix
            # module_name is always provided if options is not None.
            module_name = options['module_name']
        handler_string = '%s.%s' % (module_name, user_handler.__name__)
        getattr(self, '_register_%s' % handler_type)(
            name=name,
            user_handler=user_handler,
            handler_string=handler_string,
            wrapped_handler=wrapped_handler,
            kwargs=kwargs,
        )

    def _attach_websocket_handler(self, handler):
        route_key = handler.route_key_handled
        decorator_name = {
            '$default': 'on_ws_message',
            '$connect': 'on_ws_connect',
            '$disconnect': 'on_ws_disconnect',
        }.get(route_key)
        if route_key in self.websocket_handlers:
            raise ValueError(
                "Duplicate websocket handler: '%s'. There can only be one "
                "handler for each websocket decorator." % decorator_name
            )
        self.websocket_handlers[route_key] = handler

    def _register_on_ws_connect(self, name, user_handler, handler_string,
                                kwargs, **unused):
        wrapper = WebsocketConnectConfig(
            name=name,
            handler_string=handler_string,
            user_handler=user_handler,
        )
        self._attach_websocket_handler(wrapper)

    def _register_on_ws_message(self, name, user_handler, handler_string,
                                kwargs, **unused):
        route_key = kwargs['route_key']
        wrapper = WebsocketMessageConfig(
            name=name,
            route_key_handled=route_key,
            handler_string=handler_string,
            user_handler=user_handler,
        )
        self._attach_websocket_handler(wrapper)
        self.websocket_handlers[route_key] = wrapper

    def _register_on_ws_disconnect(self, name, user_handler,
                                   handler_string, kwargs, **unused):
        wrapper = WebsocketDisconnectConfig(
            name=name,
            handler_string=handler_string,
            user_handler=user_handler,
        )
        self._attach_websocket_handler(wrapper)

    def _register_lambda_function(self, name, user_handler,
                                  handler_string, **unused):
        wrapper = LambdaFunction(
            user_handler, name=name,
            handler_string=handler_string,
        )
        self.pure_lambda_functions.append(wrapper)

    def _register_on_s3_event(self, name, handler_string, kwargs, **unused):
        events = kwargs['events']
        if events is None:
            events = ['s3:ObjectCreated:*']
        s3_event = S3EventConfig(
            name=name,
            bucket=kwargs['bucket'],
            events=events,
            prefix=kwargs['prefix'],
            suffix=kwargs['suffix'],
            handler_string=handler_string,
        )
        self.event_sources.append(s3_event)

    def _register_on_sns_message(self, name, handler_string, kwargs, **unused):
        sns_config = SNSEventConfig(
            name=name,
            handler_string=handler_string,
            topic=kwargs['topic'],
        )
        self.event_sources.append(sns_config)

    def _register_on_sqs_message(self, name, handler_string, kwargs, **unused):
        sqs_config = SQSEventConfig(
            name=name,
            handler_string=handler_string,
            queue=kwargs['queue'],
            batch_size=kwargs['batch_size'],
        )
        self.event_sources.append(sqs_config)

    def _register_on_cw_event(self, name, handler_string, kwargs, **unused):
        event_source = CloudWatchEventConfig(
            name=name,
            event_pattern=kwargs['event_pattern'],
            handler_string=handler_string
        )
        self.event_sources.append(event_source)

    def _register_schedule(self, name, handler_string, kwargs, **unused):
        event_source = ScheduledEventConfig(
            name=name,
            schedule_expression=kwargs['expression'],
            description=kwargs["description"],
            handler_string=handler_string,
        )
        self.event_sources.append(event_source)

    def _register_authorizer(self, name, handler_string, wrapped_handler,
                             kwargs, **unused):
        actual_kwargs = kwargs.copy()
        ttl_seconds = actual_kwargs.pop('ttl_seconds', None)
        execution_role = actual_kwargs.pop('execution_role', None)
        if actual_kwargs:
            raise TypeError(
                'TypeError: authorizer() got unexpected keyword '
                'arguments: %s' % ', '.join(list(actual_kwargs)))
        auth_config = BuiltinAuthConfig(
            name=name,
            handler_string=handler_string,
            ttl_seconds=ttl_seconds,
            execution_role=execution_role,
        )
        wrapped_handler.config = auth_config
        self.builtin_auth_handlers.append(auth_config)

    def _register_route(self, name, user_handler, kwargs, **unused):
        actual_kwargs = kwargs['kwargs']
        path = kwargs['path']
        url_prefix = kwargs.pop('url_prefix', None)
        if url_prefix is not None:
            path = '/'.join([url_prefix.rstrip('/'),
                             path.strip('/')]).rstrip('/')
        methods = actual_kwargs.pop('methods', ['GET'])
        route_kwargs = {
            'authorizer': actual_kwargs.pop('authorizer', None),
            'api_key_required': actual_kwargs.pop('api_key_required', None),
            'content_types': actual_kwargs.pop('content_types',
                                               ['application/json']),
            'cors': actual_kwargs.pop('cors', self.api.cors),
        }
        if route_kwargs['cors'] is None:
            route_kwargs['cors'] = self.api.cors
        if not isinstance(route_kwargs['content_types'], list):
            raise ValueError(
                'In view function "%s", the content_types '
                'value must be a list, not %s: %s' % (
                    name, type(route_kwargs['content_types']),
                    route_kwargs['content_types']))
        if actual_kwargs:
            raise TypeError('TypeError: route() got unexpected keyword '
                            'arguments: %s' % ', '.join(list(actual_kwargs)))
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
            entry = RouteEntry(user_handler, name, path, method,
                               **route_kwargs)
            self.routes[path][method] = entry


class Chalice(_HandlerRegistration, DecoratorAPI):
    FORMAT_STRING = '%(name)s - %(levelname)s - %(message)s'

    def __init__(self, app_name, debug=False, configure_logs=True, env=None):
        super(Chalice, self).__init__()
        self.app_name = app_name
        self.websocket_api = WebsocketAPI()
        self.current_request = None
        self.lambda_context = None
        self._debug = debug
        self.configure_logs = configure_logs
        self.log = logging.getLogger(self.app_name)
        if env is None:
            env = os.environ
        self._initialize(env)
        self.experimental_feature_flags = set()
        # This is marked as internal but is intended to be used by
        # any code within Chalice.
        self._features_used = set()

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

    def register_blueprint(self, blueprint, name_prefix=None, url_prefix=None):
        blueprint.register(self, options={'name_prefix': name_prefix,
                                          'url_prefix': url_prefix})

    def _register_handler(self, handler_type, name, user_handler,
                          wrapped_handler, kwargs, options=None):
        self._do_register_handler(handler_type, name, user_handler,
                                  wrapped_handler, kwargs, options)

    def _register_on_ws_connect(self, name, user_handler, handler_string,
                                kwargs, **unused):
        self._features_used.add('WEBSOCKETS')
        super(Chalice, self)._register_on_ws_connect(
            name, user_handler, handler_string, kwargs, **unused)

    def _register_on_ws_message(self, name, user_handler, handler_string,
                                kwargs, **unused):
        self._features_used.add('WEBSOCKETS')
        super(Chalice, self)._register_on_ws_message(
            name, user_handler, handler_string, kwargs, **unused)

    def _register_on_ws_disconnect(self, name, user_handler,
                                   handler_string, kwargs, **unused):
        self._features_used.add('WEBSOCKETS')
        super(Chalice, self)._register_on_ws_disconnect(
            name, user_handler, handler_string, kwargs, **unused)

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
        self.current_request = Request(
            event['multiValueQueryStringParameters'],
            event['headers'],
            event['pathParameters'],
            event['requestContext']['httpMethod'],
            event['body'],
            event['requestContext'],
            event['stageVariables'],
            event.get('isBase64Encoded', False)
        )
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
        except Exception:
            headers = {}
            self.log.error("Caught exception for %s", view_function,
                           exc_info=True)
            if self.debug:
                # If the user has turned on debug mode,
                # we'll let the original exception propagate so
                # they get more information about what went wrong.
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


# ChaliceAuthorizer is unique in that the runtime component (the thing
# that wraps the decorated function) also needs a reference to the config
# object (the object the describes how to create the resource).  In
# most event sources these are separate and don't need to know about
# each other, but ChaliceAuthorizer does.  This is because the way
# you associate a builtin authorizer with a view function is by passing
# a direct reference:
#
# @app.authorizer(...)
# def my_auth_function(...): pass
#
# @app.route('/', auth=my_auth_function)
#
# The 'route' part needs to know about the auth function for two reasons:
#
# 1. We use ``view.authorizer`` to figure out how to deploy the app
# 2. We need a reference to the runtime handler for the auth in order
#    to support local mode testing.
# I *think* we can refactor things to handle both of those issues but
# we would need more research to know for sure.  For now, this is a
# special cased runtime class that knows about its config.
class ChaliceAuthorizer(object):
    def __init__(self, name, func, scopes=None):
        self.name = name
        self.func = func
        self.scopes = scopes or []
        # This is filled in during the @app.authorizer()
        # processing.
        self.config = None

    def __call__(self, event, context):
        auth_request = self._transform_event(event)
        result = self.func(auth_request)
        if isinstance(result, AuthResponse):
            return result.to_dict(auth_request)
        return result

    def _transform_event(self, event):
        return AuthRequest(event['type'],
                           event['authorizationToken'],
                           event['methodArn'])

    def with_scopes(self, scopes):
        authorizer_with_scopes = copy.deepcopy(self)
        authorizer_with_scopes.scopes = scopes
        return authorizer_with_scopes


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
        if route in ['/', '*']:
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


class LambdaFunction(object):
    def __init__(self, func, name, handler_string):
        self.func = func
        self.name = name
        self.handler_string = handler_string

    def __call__(self, event, context):
        return self.func(event, context)


class BaseEventSourceConfig(object):
    def __init__(self, name, handler_string):
        self.name = name
        self.handler_string = handler_string


class ScheduledEventConfig(BaseEventSourceConfig):
    def __init__(self, name, handler_string, schedule_expression, description):
        super(ScheduledEventConfig, self).__init__(name, handler_string)
        self.schedule_expression = schedule_expression
        self.description = description


class CloudWatchEventConfig(BaseEventSourceConfig):
    def __init__(self, name, handler_string, event_pattern):
        super(CloudWatchEventConfig, self).__init__(name, handler_string)
        self.event_pattern = event_pattern


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


class S3EventConfig(BaseEventSourceConfig):
    def __init__(self, name, bucket, events, prefix, suffix, handler_string):
        super(S3EventConfig, self).__init__(name, handler_string)
        self.bucket = bucket
        self.events = events
        self.prefix = prefix
        self.suffix = suffix


class SNSEventConfig(BaseEventSourceConfig):
    def __init__(self, name, handler_string, topic):
        super(SNSEventConfig, self).__init__(name, handler_string)
        self.topic = topic


class SQSEventConfig(BaseEventSourceConfig):
    def __init__(self, name, handler_string, queue, batch_size):
        super(SQSEventConfig, self).__init__(name, handler_string)
        self.queue = queue
        self.batch_size = batch_size


class WebsocketConnectConfig(BaseEventSourceConfig):
    CONNECT_ROUTE = '$connect'

    def __init__(self, name, handler_string, user_handler):
        super(WebsocketConnectConfig, self).__init__(name, handler_string)
        self.route_key_handled = self.CONNECT_ROUTE
        self.handler_function = user_handler


class WebsocketMessageConfig(BaseEventSourceConfig):
    def __init__(self, name, route_key_handled, handler_string, user_handler):
        super(WebsocketMessageConfig, self).__init__(name, handler_string)
        self.route_key_handled = route_key_handled
        self.handler_function = user_handler


class WebsocketDisconnectConfig(BaseEventSourceConfig):
    DISCONNECT_ROUTE = '$disconnect'

    def __init__(self, name, handler_string, user_handler):
        super(WebsocketDisconnectConfig, self).__init__(name, handler_string)
        self.route_key_handled = self.DISCONNECT_ROUTE
        self.handler_function = user_handler


class EventSourceHandler(object):

    def __init__(self, func, event_class):
        self.func = func
        self.event_class = event_class

    def __call__(self, event, context):
        event_obj = self.event_class(event, context)
        return self.func(event_obj)


class WebsocketEventSourceHandler(object):
    def __init__(self, func, event_class, websocket_api):
        self.func = func
        self.event_class = event_class
        self.websocket_api = websocket_api

    def __call__(self, event, context):
        event_obj = self.event_class(event, context)
        self.websocket_api.configure(
            event_obj.domain_name,
            event_obj.stage,
        )
        self.func(event_obj)
        return {'statusCode': 200}


# These classes contain all the event types that are passed
# in as arguments in the lambda event handlers.  These are
# part of Chalice's public API and must be backwards compatible.

class BaseLambdaEvent(object):
    def __init__(self, event_dict, context):
        self._event_dict = event_dict
        self.context = context
        self._extract_attributes(event_dict)

    def _extract_attributes(self, event_dict):
        raise NotImplementedError("_extract_attributes")

    def to_dict(self):
        return self._event_dict


class CloudWatchEvent(BaseLambdaEvent):
    def _extract_attributes(self, event_dict):
        self.version = event_dict['version']
        self.account = event_dict['account']
        self.region = event_dict['region']
        self.detail = event_dict['detail']
        self.detail_type = event_dict['detail-type']
        self.source = event_dict['source']
        self.time = event_dict['time']
        self.event_id = event_dict['id']
        self.resources = event_dict['resources']


class WebsocketEvent(BaseLambdaEvent):
    def __init__(self, event_dict, context):
        super(WebsocketEvent, self).__init__(event_dict, context)
        self._json_body = None

    def _extract_attributes(self, event_dict):
        request_context = event_dict['requestContext']
        self.domain_name = request_context['domainName']
        self.stage = request_context['stage']
        self.connection_id = request_context['connectionId']
        self.body = event_dict.get('body')

    @property
    def json_body(self):
        if self._json_body is None:
            try:
                self._json_body = json.loads(self.body)
            except ValueError:
                raise BadRequestError('Error Parsing JSON')
        return self._json_body


class SNSEvent(BaseLambdaEvent):
    def _extract_attributes(self, event_dict):
        first_record = event_dict['Records'][0]
        self.message = first_record['Sns']['Message']
        self.subject = first_record['Sns']['Subject']


class S3Event(BaseLambdaEvent):
    def _extract_attributes(self, event_dict):
        s3 = event_dict['Records'][0]['s3']
        self.bucket = s3['bucket']['name']
        self.key = unquote_str(s3['object']['key'])


class SQSEvent(BaseLambdaEvent):
    def _extract_attributes(self, event_dict):
        # We don't extract anything off the top level
        # event.
        pass

    def __iter__(self):
        for record in self._event_dict['Records']:
            yield SQSRecord(record, self.context)


class SQSRecord(BaseLambdaEvent):
    def _extract_attributes(self, event_dict):
        self.body = event_dict['body']
        self.receipt_handle = event_dict['receiptHandle']


class Blueprint(DecoratorAPI):
    def __init__(self, import_name):
        self._import_name = import_name
        self._deferred_registrations = []
        self._current_app = None
        self._lambda_context = None

    @property
    def current_request(self):
        if self._current_app is None:
            raise RuntimeError(
                "Can only access Blueprint.current_request if it's registered "
                "to an app."
            )
        return self._current_app.current_request

    @property
    def lambda_context(self):
        if self._current_app is None:
            raise RuntimeError(
                "Can only access Blueprint.lambda_context if it's registered "
                "to an app."
            )
        return self._current_app.lambda_context

    def register(self, app, options):
        self._current_app = app
        all_options = options.copy()
        all_options['module_name'] = self._import_name
        for function in self._deferred_registrations:
            function(app, all_options)

    def _register_handler(self, handler_type, name, user_handler,
                          wrapped_handler, kwargs, options=None):
        # If we go through the public API (app.route, app.schedule, etc) then
        # we have to duplicate either the methods or the params in this
        # class.  We're using _register_handler as a tradeoff for cutting
        # down on the duplication.
        self._deferred_registrations.append(
            # pylint: disable=protected-access
            lambda app, options: app._register_handler(
                handler_type, name, user_handler, wrapped_handler,
                kwargs, options
            )
        )
