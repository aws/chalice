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
import functools
import datetime
from collections import defaultdict

# Implementation note:  This file is intended to be a standalone file
# that gets copied into the lambda deployment package.  It has no dependencies
# on other parts of chalice, so it can stay small and lightweight, with minimal
# startup overhead.
from urllib.parse import unquote_plus
from collections.abc import Mapping
from collections.abc import MutableMapping


__version__: str = '1.32.0'

from typing import List, Dict, Any, Optional, Sequence, Union, Callable, Set, \
    Iterator, TYPE_CHECKING, Tuple

if TYPE_CHECKING:
    from chalice.local import LambdaContext

_PARAMS = re.compile(r'{\w+}')
MiddlewareFuncType = Callable[[Any, Callable[[Any], Any]], Any]
UserHandlerFuncType = Callable[..., Any]
HeadersType = Dict[str, Union[str, List[str]]]

# In python 3 string and bytes are different so we explicitly check
# for both.
_ANY_STRING = (str, bytes)


def handle_extra_types(
        obj: Union[decimal.Decimal, 'MultiDict']
) -> Union[float, Dict]:
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


def error_response(
    message: str, error_code: str, http_status_code: int,
    headers: Optional[HeadersType] = None
) -> 'Response':
    body = {'Code': error_code, 'Message': message}
    response = Response(body=body, status_code=http_status_code,
                        headers=headers)
    return response


def _matches_content_type(content_type: str,
                          valid_content_types: List[str]) -> bool:
    # If '*/*' is in the Accept header or the valid types,
    # then all content_types match. Otherwise see of there are any common types
    content_type = content_type.lower()
    valid_content_types = [x.lower() for x in valid_content_types]
    return '*/*' in content_type or \
        '*/*' in valid_content_types or \
        _content_type_header_contains(content_type, valid_content_types)


def _content_type_header_contains(
        content_type_header: str,
        valid_content_types: List[str]
) -> bool:
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
    def __init__(self, connection_id: str):
        self.connection_id: str = connection_id


class ChaliceViewError(ChaliceError):
    STATUS_CODE: int = 500


class ChaliceUnhandledError(ChaliceError):
    """This error is not caught from a Chalice view function.

    This exception is allowed to propagate from a view function so
    that middleware handlers can process the exception.
    """


class BadRequestError(ChaliceViewError):
    STATUS_CODE: int = 400


class UnauthorizedError(ChaliceViewError):
    STATUS_CODE: int = 401


class ForbiddenError(ChaliceViewError):
    STATUS_CODE: int = 403


class NotFoundError(ChaliceViewError):
    STATUS_CODE: int = 404


class MethodNotAllowedError(ChaliceViewError):
    STATUS_CODE: int = 405


class RequestTimeoutError(ChaliceViewError):
    STATUS_CODE: int = 408


class ConflictError(ChaliceViewError):
    STATUS_CODE: int = 409


class UnprocessableEntityError(ChaliceViewError):
    STATUS_CODE: int = 422


class TooManyRequestsError(ChaliceViewError):
    STATUS_CODE: int = 429


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
    TooManyRequestsError,
]


class MultiDict(MutableMapping):  # pylint: disable=too-many-ancestors
    """A mapping of key to list of values.

    Accessing it in the usual way will return the last value in the list.
    Calling getlist will return a list of all the values associated with
    the same key.
    """

    def __init__(self, mapping: Optional[Dict]):
        if mapping is None:
            mapping = {}

        self._dict = mapping

    def __getitem__(self, k: Any) -> Any:
        try:
            return self._dict[k][-1]
        except IndexError:
            raise KeyError(k)

    def __setitem__(self, k: Any, v: Any) -> None:
        self._dict[k] = [v]

    def __delitem__(self, k: Any) -> None:
        del self._dict[k]

    def getlist(self, k: Any) -> List:
        return list(self._dict[k])

    def __len__(self) -> int:
        return len(self._dict)

    def __iter__(self) -> Iterator:
        return iter(self._dict)

    def __repr__(self) -> str:
        return 'MultiDict(%s)' % self._dict

    def __str__(self) -> str:
        return repr(self)


class CaseInsensitiveMapping(Mapping):
    """Case insensitive and read-only mapping."""

    def __init__(self, mapping: Union[Dict[str, Any], MultiDict]) -> None:
        mapping = mapping or {}
        self._dict = {k.lower(): v for k, v in mapping.items()}

    def __getitem__(self, key: str) -> Any:
        return self._dict[key.lower()]

    def __iter__(self) -> Iterator:
        return iter(self._dict)

    def __len__(self) -> int:
        return len(self._dict)

    def __repr__(self) -> str:
        return 'CaseInsensitiveMapping(%s)' % repr(self._dict)


class Authorizer(object):
    name: str = ''
    scopes: List[str] = []

    def to_swagger(self) -> Dict[str, Any]:
        raise NotImplementedError("to_swagger")

    def with_scopes(self, scopes: List[str]) -> 'Authorizer':
        raise NotImplementedError("with_scopes")


class IAMAuthorizer(Authorizer):
    _AUTH_TYPE: str = 'aws_iam'

    def __init__(self) -> None:
        self.name: str = 'sigv4'
        self.scopes: List[str] = []

    def to_swagger(self) -> Dict[str, str]:
        return {
            'in': 'header',
            'type': 'apiKey',
            'name': 'Authorization',
            'x-amazon-apigateway-authtype': 'awsSigv4',
        }

    def with_scopes(self, scopes: List[str]) -> 'Authorizer':
        raise NotImplementedError("with_scopes")


class CognitoUserPoolAuthorizer(Authorizer):

    _AUTH_TYPE: str = 'cognito_user_pools'

    def __init__(self, name: str, provider_arns: List[str],
                 header: Optional[str] = 'Authorization',
                 scopes: Optional[List] = None) -> None:
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

    def to_swagger(self) -> Dict[str, Any]:
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

    def with_scopes(self, scopes: List[str]) -> 'Authorizer':
        authorizer_with_scopes = copy.deepcopy(self)
        authorizer_with_scopes.scopes = scopes
        return authorizer_with_scopes


class CustomAuthorizer(Authorizer):

    _AUTH_TYPE = 'custom'

    def __init__(self, name: str, authorizer_uri: str, ttl_seconds: int = 300,
                 header: str = 'Authorization',
                 invoke_role_arn: Optional[str] = None,
                 scopes: Optional[List[str]] = None) -> None:
        self.name = name
        self._header = header
        self._authorizer_uri = authorizer_uri
        self._ttl_seconds = ttl_seconds
        self._invoke_role_arn = invoke_role_arn
        self.scopes = scopes or []

    def to_swagger(self) -> Dict[str, Any]:
        swagger: Dict[str, Any] = {
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

    def with_scopes(self, scopes: List[str]) -> 'Authorizer':
        authorizer_with_scopes = copy.deepcopy(self)
        authorizer_with_scopes.scopes = scopes
        return authorizer_with_scopes


class CORSConfig(object):
    """A cors configuration to attach to a route."""

    _REQUIRED_HEADERS: List[str] = ['Content-Type', 'X-Amz-Date',
                                    'Authorization', 'X-Api-Key',
                                    'X-Amz-Security-Token']

    def __init__(self, allow_origin: str = '*',
                 allow_headers: Optional[Sequence[str]] = None,
                 expose_headers: Optional[Sequence[str]] = None,
                 max_age: Optional[int] = None,
                 allow_credentials: Optional[bool] = None):
        self.allow_origin = allow_origin

        if allow_headers is None:
            self._allow_headers = set(self._REQUIRED_HEADERS)
        else:
            self._allow_headers = set(
                list(allow_headers) + self._REQUIRED_HEADERS
            )

        if expose_headers is None:
            expose_headers = []
        self._expose_headers = expose_headers

        self._max_age = max_age
        self._allow_credentials = allow_credentials

    @property
    def allow_headers(self) -> str:
        return ','.join(sorted(self._allow_headers))

    def get_access_control_headers(self) -> Dict[str, str]:
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

    def __eq__(self, other: object) -> bool:
        if isinstance(other, self.__class__):
            return self.get_access_control_headers() == \
                other.get_access_control_headers()
        return False


class Request(object):
    """The current request from API gateway."""
    _NON_SERIALIZED_ATTRS: List[str] = ['lambda_context']
    body: Any
    base64_body: str

    def __init__(self, event_dict: Dict[str, Any],
                 lambda_context: Optional[Any] = None) -> None:
        query_params = event_dict['multiValueQueryStringParameters']
        self.query_params: Optional[MultiDict] = None \
            if query_params is None else MultiDict(query_params)
        self.headers: CaseInsensitiveMapping = \
            CaseInsensitiveMapping(event_dict['headers'])
        self.uri_params: Optional[Dict[str, str]] \
            = event_dict['pathParameters']
        self.method: str = event_dict['requestContext']['httpMethod']
        self._is_base64_encoded = event_dict.get('isBase64Encoded', False)
        self._body: Any = event_dict['body']
        #: The parsed JSON from the body.  This value should
        #: only be set if the Content-Type header is application/json,
        #: which is the default content type value in chalice.
        self._json_body: Optional[Any] = None
        self._raw_body = b''
        self.context: Dict[str, Any] = event_dict['requestContext']
        self.stage_vars: Optional[Dict[str, str]] \
            = event_dict['stageVariables']
        self.path: str = event_dict['requestContext']['resourcePath']
        self.lambda_context = lambda_context
        self._event_dict = event_dict

    def _base64decode(self, encoded: Union[bytes, str]) -> bytes:
        if not isinstance(encoded, bytes):
            encoded = encoded.encode('ascii')
        output = base64.b64decode(encoded)
        return output

    @property
    def raw_body(self) -> Union[str, bytes]:
        if not self._raw_body and self._body is not None:
            if self._is_base64_encoded:
                self._raw_body = self._base64decode(self._body)
            elif not isinstance(self._body, bytes):
                self._raw_body = self._body.encode('utf-8')
            else:
                self._raw_body = self._body
        return self._raw_body

    @property
    def json_body(self) -> Any:
        if self.headers.get('content-type', '').startswith('application/json'):
            if self._json_body is None:
                try:
                    self._json_body = json.loads(self.raw_body)
                except ValueError:
                    raise BadRequestError('Error Parsing JSON')
            return self._json_body

    def to_dict(self) -> Dict[Any, Any]:
        # Don't copy internal attributes.
        copied = {
            k: v for k, v in self.__dict__.items()
            if not k.startswith('_') and
            k not in self._NON_SERIALIZED_ATTRS
        }
        # We want the output of `to_dict()` to be
        # JSON serializable, so we need to remove the CaseInsensitive dict.
        copied['headers'] = dict(copied['headers'])
        if copied['query_params'] is not None:
            copied['query_params'] = dict(copied['query_params'])
        return copied

    def to_original_event(self) -> Dict[str, Any]:
        # To bring consistency with the BaseLambdaEvents, every
        # input event should have access to the original event
        # dictionary as an escape hatch to the underlying data
        # in case something gets added and we haven't mapped it yet.
        # We unfortunately already have a `to_dict()` method which is
        # what other events use so we have to use a different method name.
        return self._event_dict


class Response(object):

    def __init__(
            self, body: Any,
            headers: Optional[HeadersType] = None,
            status_code: int = 200
    ):
        self.body: Any = body
        if headers is None:
            headers = {}
        self.headers: HeadersType = headers
        self.status_code = status_code

    def to_dict(
            self,
            binary_types: Optional[List[str]] = None
    ) -> Dict[str, Any]:
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

    def _sort_headers(
            self, all_headers: HeadersType
    ) -> Tuple[Dict[str, Any], Dict[str, List]]:
        multi_headers: Dict[str, List] = {}
        single_headers: Dict[str, Any] = {}
        for name, value in all_headers.items():
            if isinstance(value, list):
                multi_headers[name] = value
            else:
                single_headers[name] = value
        return single_headers, multi_headers

    def _b64encode_body_if_needed(
            self,
            response_dict: Dict[str, Any],
            binary_types: List[str]
    ) -> None:
        response_headers = CaseInsensitiveMapping(response_dict['headers'])
        content_type = response_headers.get('content-type', '')
        body = response_dict['body']

        if _matches_content_type(content_type, binary_types):
            if _matches_content_type(content_type, ['application/json']) or \
                    not content_type:
                # There's a special case when a user configures
                # ``application/json`` as a binary type.  The default
                # json serialization results in a string type, but for binary
                # content types we need a type bytes().  So we need to special
                # case this scenario and encode the JSON body to bytes().
                #
                # If a user does not provide a content type header, which can
                # happen if they return a python type instead of a ``Response``
                # type, then we assume the content is application/json.
                body = body if isinstance(body, bytes) \
                    else body.encode('utf-8')
            body = self._base64encode(body)
            response_dict['isBase64Encoded'] = True
        response_dict['body'] = body

    def _base64encode(self, data: bytes) -> str:
        if not isinstance(data, bytes):
            raise ValueError('Expected bytes type for body with binary '
                             'Content-Type. Got %s type body instead.'
                             % type(data))
        data = base64.b64encode(data)
        return data.decode('ascii')


class RouteEntry(object):

    def __init__(self, view_function: Callable[..., Any], view_name: str,
                 path: str, method: str,
                 api_key_required: Optional[bool] = None,
                 content_types: Optional[List[str]] = None,
                 cors: Optional[Union[bool, CORSConfig]] = False,
                 authorizer: Optional[Authorizer] = None):
        self.view_function: Callable[..., Any] = view_function
        self.view_name: str = view_name
        self.uri_pattern: str = path
        self.method: str = method
        self.api_key_required: Optional[bool] = api_key_required
        #: A list of names to extract from path:
        #: e.g, '/foo/{bar}/{baz}/qux -> ['bar', 'baz']
        self.view_args: List[str] = self._parse_view_args()
        self.content_types: List[str] = content_types or []
        # cors is passed as either a boolean or a CORSConfig object. If it is a
        # boolean it needs to be replaced with a real CORSConfig object to
        # pass the typechecker. None in this context will not inject any cors
        # headers, otherwise the CORSConfig object will determine which
        # headers are injected.
        if cors is True:
            cors = CORSConfig()
        elif cors is False:
            cors = None
        self.cors: CORSConfig = cors  # type: ignore
        self.authorizer: Optional[Authorizer] = authorizer

    def _parse_view_args(self) -> List[str]:
        if '{' not in self.uri_pattern:
            return []
        # The [1:-1] slice is to remove the braces
        # e.g {foobar} -> foobar
        results = [r[1:-1] for r in _PARAMS.findall(self.uri_pattern)]
        return results

    def __eq__(self, other: object) -> bool:
        return self.__dict__ == other.__dict__


class APIGateway(object):

    _DEFAULT_BINARY_TYPES = [
        'application/octet-stream', 'application/x-tar', 'application/zip',
        'audio/basic', 'audio/ogg', 'audio/mp4', 'audio/mpeg', 'audio/wav',
        'audio/webm', 'image/png', 'image/jpg', 'image/jpeg', 'image/gif',
        'video/ogg', 'video/mpeg', 'video/webm',
    ]

    def __init__(self) -> None:
        self.binary_types: List[str] = self.default_binary_types
        self.cors: Union[bool, CORSConfig] = False

    @property
    def default_binary_types(self) -> List[str]:
        return list(self._DEFAULT_BINARY_TYPES)


class WebsocketAPI(object):
    _WEBSOCKET_ENDPOINT_TEMPLATE = 'https://{domain_name}/{stage}'
    _REGION_ENV_VARS = ['AWS_REGION', 'AWS_DEFAULT_REGION']

    def __init__(self, env: Optional[MutableMapping] = None) -> None:
        self.session: Optional[Any] = None
        self._endpoint: Optional[str] = None
        self._client = None
        if env is None:
            self._env: MutableMapping = os.environ
        else:
            self._env = env

    def configure(self, domain_name: str, stage: str) -> None:
        if self._endpoint is not None:
            return
        self._endpoint = self._WEBSOCKET_ENDPOINT_TEMPLATE.format(
            domain_name=domain_name,
            stage=stage,
        )

    def configure_from_api_id(self, api_id: str, stage: str) -> None:
        if self._endpoint is not None:
            return
        region_name = self._get_region()

        if region_name.startswith("cn-"):
            domain_name_template = (
                '{api_id}.execute-api.{region}.amazonaws.com.cn'
            )
        else:
            domain_name_template = (
                '{api_id}.execute-api.{region}.amazonaws.com'
            )

        domain_name = domain_name_template.format(
            api_id=api_id, region=region_name)
        self.configure(domain_name, stage)

    def _get_region(self) -> str:
        # Attempt to get the region so we can configure the
        # apigatewaymanagementapi client.  We'll first try
        # retrieving this value from env vars because these should
        # always be set in the Lambda runtime environment.
        for varname in self._REGION_ENV_VARS:
            if varname in self._env:
                return self._env[varname]
        # As a last attempt we'll try to retrieve the region
        # from the currently configured region.  If the session
        # isn't configured or we can't get the region, we have
        # no choice but to error out.
        if self.session is not None:
            region_name = self.session.region_name
            if region_name is not None:
                return region_name
        raise ValueError(
            "Unable to retrieve the region name when configuring the "
            "websocket client.  Either set the 'AWS_REGION' environment "
            "variable or assign 'app.websocket_api.session' to a boto3 "
            "session."
        )

    def _get_client(self) -> Any:
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

    def send(self, connection_id: str, message: str) -> None:
        client = self._get_client()
        try:
            client.post_to_connection(
                ConnectionId=connection_id,
                Data=message,
            )
        except client.exceptions.GoneException:
            raise WebsocketDisconnectedError(connection_id)

    def close(self, connection_id: str) -> None:
        client = self._get_client()
        try:
            client.delete_connection(
                ConnectionId=connection_id,
            )
        except client.exceptions.GoneException:
            raise WebsocketDisconnectedError(connection_id)

    def info(self, connection_id: str) -> Any:
        client = self._get_client()
        try:
            return client.get_connection(
                ConnectionId=connection_id,
            )
        except client.exceptions.GoneException:
            raise WebsocketDisconnectedError(connection_id)


class DecoratorAPI(object):
    websocket_api: Optional[WebsocketAPI] = None

    def middleware(
            self,
            event_type: str = 'all'
    ) -> Callable[[Callable[..., Any]], Any]:
        def _middleware_wrapper(
                func: Callable[..., Any]
        ) -> Callable[..., Any]:
            self.register_middleware(func, event_type)
            return func
        return _middleware_wrapper

    def authorizer(self, ttl_seconds: Optional[int] = None,
                   execution_role: Optional[str] = None,
                   name: Optional[str] = None,
                   header: Optional[str] = 'Authorization'
                   ) -> Callable[..., Any]:
        return self._create_registration_function(
            handler_type='authorizer',
            name=name,
            registration_kwargs={
                'ttl_seconds': ttl_seconds,
                'execution_role': execution_role,
                'header': header
            }
        )

    def on_s3_event(self, bucket: str, events: Optional[List[str]] = None,
                    prefix: Optional[str] = None, suffix: Optional[str] = None,
                    name: Optional[str] = None) -> Callable[..., Any]:
        return self._create_registration_function(
            handler_type='on_s3_event',
            name=name,
            registration_kwargs={
                'bucket': bucket, 'events': events,
                'prefix': prefix, 'suffix': suffix,
            }
        )

    def on_sns_message(self, topic: str,
                       name: Optional[str] = None) -> Callable[..., Any]:
        return self._create_registration_function(
            handler_type='on_sns_message',
            name=name,
            registration_kwargs={'topic': topic}
        )

    def on_sqs_message(self, queue: Optional[str] = None, batch_size: int = 1,
                       name: Optional[str] = None,
                       queue_arn: Optional[str] = None,
                       maximum_batching_window_in_seconds: int = 0,
                       maximum_concurrency: Optional[int] = None,
                       ) -> Callable[..., Any]:
        return self._create_registration_function(
            handler_type='on_sqs_message',
            name=name,
            registration_kwargs={
                'queue': queue,
                'queue_arn': queue_arn,
                'batch_size': batch_size,
                'maximum_batching_window_in_seconds':
                    maximum_batching_window_in_seconds,
                'maximum_concurrency': maximum_concurrency,
            }
        )

    def on_cw_event(self, event_pattern: Dict[str, Any],
                    name: Optional[str] = None) -> Callable[..., Any]:
        return self._create_registration_function(
            handler_type='on_cw_event',
            name=name,
            registration_kwargs={'event_pattern': event_pattern}
        )

    def schedule(self, expression: Union[str, 'ScheduleExpression'],
                 name: Optional[str] = None,
                 description: str = '') -> Callable[..., Any]:
        return self._create_registration_function(
            handler_type='schedule',
            name=name,
            registration_kwargs={'expression': expression,
                                 'description': description},
        )

    def on_kinesis_record(self, stream: str, batch_size: int = 100,
                          starting_position: str = 'LATEST',
                          name: Optional[str] = None,
                          maximum_batching_window_in_seconds: int = 0
                          ) -> Callable[..., Any]:
        return self._create_registration_function(
            handler_type='on_kinesis_record',
            name=name,
            registration_kwargs={
                'stream': stream,
                'batch_size': batch_size,
                'starting_position': starting_position,
                'maximum_batching_window_in_seconds':
                    maximum_batching_window_in_seconds},
        )

    def on_dynamodb_record(
            self, stream_arn: str,
            batch_size: int = 100,
            starting_position: str = 'LATEST',
            name: Optional[str] = None,
            maximum_batching_window_in_seconds: int = 0
    ) -> Callable[..., Any]:
        return self._create_registration_function(
            handler_type='on_dynamodb_record',
            name=name,
            registration_kwargs={
                'stream_arn': stream_arn,
                'batch_size': batch_size,
                'starting_position': starting_position,
                'maximum_batching_window_in_seconds':
                    maximum_batching_window_in_seconds},
        )

    def route(self, path: str, **kwargs: Any) -> Callable[..., Any]:
        return self._create_registration_function(
            handler_type='route',
            name=kwargs.pop('name', None),
            # This looks a little weird taking kwargs as a key,
            # but we want to preserve keep the **kwargs signature
            # in the route decorator.
            registration_kwargs={'path': path, 'kwargs': kwargs},
        )

    def lambda_function(self,
                        name: Optional[str] = None) -> Callable[..., Any]:
        return self._create_registration_function(
            handler_type='lambda_function', name=name)

    def on_ws_connect(self,
                      name: Optional[str] = None) -> Callable[..., Any]:
        return self._create_registration_function(
            handler_type='on_ws_connect',
            name=name,
            registration_kwargs={'route_key': '$connect'},
        )

    def on_ws_disconnect(self,
                         name: Optional[str] = None) -> Callable[..., Any]:
        return self._create_registration_function(
            handler_type='on_ws_disconnect',
            name=name,
            registration_kwargs={'route_key': '$disconnect'},
        )

    def on_ws_message(self, name: Optional[str] = None) -> Callable[..., Any]:
        return self._create_registration_function(
            handler_type='on_ws_message',
            name=name,
            registration_kwargs={'route_key': '$default'},
        )

    def _create_registration_function(self, handler_type: str,
                                      name: Optional[str] = None,
                                      registration_kwargs: Optional[Any] = None
                                      ) -> Callable[..., Any]:
        def _register_handler(
                user_handler: UserHandlerFuncType
        ) -> Callable[..., Any]:
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

    def _wrap_handler(self, handler_type: str,
                      handler_name: str,
                      user_handler: UserHandlerFuncType
                      ) -> UserHandlerFuncType:
        if handler_type in _EVENT_CLASSES:
            if handler_type == 'lambda_function':
                # We have to wrap existing @app.lambda_function()
                # handlers for backwards compat reasons so we can
                # preserve the `def handler(event, context): ...`
                # interface.  However we need a consistent interface
                # for middleware so we have to wrap the event
                # here.
                user_handler = PureLambdaWrapper(user_handler)
            return EventSourceHandler(
                user_handler, _EVENT_CLASSES[handler_type],
                middleware_handlers=self._get_middleware_handlers(
                    event_type=_MIDDLEWARE_MAPPING[handler_type],
                )
            )

        websocket_event_classes = [
            'on_ws_connect',
            'on_ws_message',
            'on_ws_disconnect',
        ]
        if self.websocket_api and handler_type in websocket_event_classes:
            return WebsocketEventSourceHandler(
                user_handler, WebsocketEvent,
                self.websocket_api,
                middleware_handlers=self._get_middleware_handlers(
                    event_type='websocket')
            )
        if handler_type == 'authorizer':
            # Authorizer is special cased and doesn't quite fit the
            # EventSourceHandler pattern.
            return ChaliceAuthorizer(handler_name, user_handler)
        return user_handler

    def _get_middleware_handlers(self, event_type: str) -> List:
        raise NotImplementedError("_get_middleware_handlers")

    def _register_handler(self, handler_type: str, name: str,
                          user_handler: UserHandlerFuncType,
                          wrapped_handler: Callable[..., Any],
                          kwargs: Dict[str, Any],
                          options: Optional[Dict[Any, Any]] = None) -> None:
        raise NotImplementedError("_register_handler")

    def register_middleware(self, func: MiddlewareFuncType,
                            event_type: str = 'all') -> None:
        raise NotImplementedError("register_middleware")


class _HandlerRegistration(object):

    def __init__(self) -> None:
        self.routes: Dict[str, Dict[str, RouteEntry]] = defaultdict(dict)
        self.websocket_handlers: Dict[str, Any] = {}
        self.builtin_auth_handlers: List['BuiltinAuthConfig'] = []
        self.event_sources: List['BaseEventSourceConfig'] = []
        self.pure_lambda_functions: List['LambdaFunction'] = []
        self.api: APIGateway = APIGateway()
        self.handler_map: Dict[str, Callable[..., Any]] = {}
        self.middleware_handlers: List[Tuple[MiddlewareFuncType, str]] = []

    def register_middleware(self, func: MiddlewareFuncType,
                            event_type: str = 'all') -> None:
        self.middleware_handlers.append((func, event_type))

    def _do_register_handler(self, handler_type: str, name: str,
                             user_handler: UserHandlerFuncType,
                             wrapped_handler: Callable[..., Any], kwargs: Any,
                             options: Optional[Dict[Any, Any]] = None) -> None:
        module_name = 'app'
        if options is not None:
            name_prefix = options.get('name_prefix')
            if name_prefix is not None:
                name = name_prefix + name
            url_prefix = options.get('url_prefix')
            if url_prefix is not None and handler_type == 'route':
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
        self.handler_map[name] = wrapped_handler

    def _attach_websocket_handler(self, handler: Union[
        'WebsocketConnectConfig',
        'WebsocketMessageConfig',
        'WebsocketDisconnectConfig'
    ]) -> None:
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

    def _register_on_ws_connect(self, name: str,
                                user_handler: UserHandlerFuncType,
                                handler_string: str,
                                kwargs: Any, **unused: Dict[str, Any]) -> None:
        wrapper = WebsocketConnectConfig(
            name=name,
            handler_string=handler_string,
            user_handler=user_handler,
        )
        self._attach_websocket_handler(wrapper)

    def _register_on_ws_message(self, name: str,
                                user_handler: UserHandlerFuncType,
                                handler_string: str,
                                kwargs: Any, **unused: Dict[str, Any]) -> None:
        route_key = kwargs['route_key']
        wrapper = WebsocketMessageConfig(
            name=name,
            route_key_handled=route_key,
            handler_string=handler_string,
            user_handler=user_handler,
        )
        self._attach_websocket_handler(wrapper)
        self.websocket_handlers[route_key] = wrapper

    def _register_on_ws_disconnect(self, name: str,
                                   user_handler: UserHandlerFuncType,
                                   handler_string: str, kwargs: Any,
                                   **unused: Dict[str, Any]) -> None:
        wrapper = WebsocketDisconnectConfig(
            name=name,
            handler_string=handler_string,
            user_handler=user_handler,
        )
        self._attach_websocket_handler(wrapper)

    def _register_lambda_function(self, name: str,
                                  user_handler: UserHandlerFuncType,
                                  handler_string: str,
                                  **unused: Dict[str, Any]) -> None:
        wrapper = LambdaFunction(
            func=user_handler, name=name,
            handler_string=handler_string,
        )
        self.pure_lambda_functions.append(wrapper)

    def _register_on_s3_event(self, name: str,
                              handler_string: str,
                              kwargs: Any, **unused: Dict[str, Any]
                              ) -> None:
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

    def _register_on_sns_message(self, name: str,
                                 handler_string: str,
                                 kwargs: Any,
                                 **unused: Dict[str, Any]
                                 ) -> None:
        sns_config = SNSEventConfig(
            name=name,
            handler_string=handler_string,
            topic=kwargs['topic'],
        )
        self.event_sources.append(sns_config)

    def _register_on_sqs_message(self, name: str,
                                 handler_string: str,
                                 kwargs: Any,
                                 **unused: Dict[str, Any]
                                 ) -> None:
        queue = kwargs.get('queue')
        queue_arn = kwargs.get('queue_arn')
        if not queue and not queue_arn:
            raise ValueError(
                "Must provide either `queue` or `queue_arn` to the "
                "`on_sqs_message` decorator."
            )
        sqs_config = SQSEventConfig(
            name=name,
            handler_string=handler_string,
            queue=queue,
            queue_arn=queue_arn,
            batch_size=kwargs['batch_size'],
            maximum_batching_window_in_seconds=kwargs[
                'maximum_batching_window_in_seconds'],
            maximum_concurrency=kwargs[
                'maximum_concurrency'],
        )
        self.event_sources.append(sqs_config)

    def _register_on_kinesis_record(self,
                                    name: str,
                                    handler_string: str,
                                    kwargs: Any,
                                    **unused: Dict[str, Any]
                                    ) -> None:
        kinesis_config = KinesisEventConfig(
            name=name,
            handler_string=handler_string,
            stream=kwargs['stream'],
            batch_size=kwargs['batch_size'],
            starting_position=kwargs['starting_position'],
            maximum_batching_window_in_seconds=kwargs[
                'maximum_batching_window_in_seconds'],
        )
        self.event_sources.append(kinesis_config)

    def _register_on_dynamodb_record(self, name: str,
                                     handler_string: str,
                                     kwargs: Any,
                                     **unused: Dict[str, Any]) -> None:
        ddb_config = DynamoDBEventConfig(
            name=name,
            handler_string=handler_string,
            stream_arn=kwargs['stream_arn'],
            batch_size=kwargs['batch_size'],
            starting_position=kwargs['starting_position'],
            maximum_batching_window_in_seconds=kwargs[
                'maximum_batching_window_in_seconds'],
        )
        self.event_sources.append(ddb_config)

    def _register_on_cw_event(self, name: str, handler_string: str,
                              kwargs: Any, **unused: Dict[str, Any]) -> None:
        event_source = CloudWatchEventConfig(
            name=name,
            event_pattern=kwargs['event_pattern'],
            handler_string=handler_string
        )
        self.event_sources.append(event_source)

    def _register_schedule(self, name: str, handler_string: str,
                           kwargs: Any, **unused: Dict[str, Any]) -> None:
        event_source = ScheduledEventConfig(
            name=name,
            schedule_expression=kwargs['expression'],
            description=kwargs["description"],
            handler_string=handler_string,
        )
        self.event_sources.append(event_source)

    def _register_authorizer(self, name: str, handler_string: str,
                             wrapped_handler: 'ChaliceAuthorizer',
                             kwargs: Any, **unused: Dict[str, Any]) -> None:
        actual_kwargs = kwargs.copy()
        ttl_seconds = actual_kwargs.pop('ttl_seconds', None)
        execution_role = actual_kwargs.pop('execution_role', None)
        header = actual_kwargs.pop('header', None)
        if actual_kwargs:
            raise TypeError(
                'TypeError: authorizer() got unexpected keyword '
                'arguments: %s' % ', '.join(list(actual_kwargs)))
        auth_config = BuiltinAuthConfig(
            name=name,
            handler_string=handler_string,
            ttl_seconds=ttl_seconds,
            execution_role=execution_role,
            header=header,
        )
        wrapped_handler.config = auth_config
        self.builtin_auth_handlers.append(auth_config)

    def _register_route(self, name: str, user_handler: UserHandlerFuncType,
                        kwargs: Any, **unused: Dict[str, Any]) -> None:
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
    authorizers: Dict[str, Dict[str, Any]]
    lambda_context: 'LambdaContext'
    current_request: Optional[Request]

    def __init__(self, app_name: str, debug: bool = False,
                 configure_logs: bool = True,
                 env: Optional[MutableMapping] = None) -> None:
        super(Chalice, self).__init__()
        self.app_name: str = app_name
        self.websocket_api: WebsocketAPI = WebsocketAPI()
        self._debug: bool = debug
        self.configure_logs: bool = configure_logs
        self.log: logging.Logger = logging.getLogger(self.app_name)
        if env is None:
            env = os.environ
        self._initialize(env)
        self.experimental_feature_flags: Set[str] = set()
        # This is marked as internal but is intended to be used by
        # any code within Chalice.
        self._features_used: Set[str] = set()

    def _initialize(self, env: MutableMapping) -> None:
        if self.configure_logs:
            self._configure_logging()
        env['AWS_EXECUTION_ENV'] = '%s aws-chalice/%s' % (
            env.get('AWS_EXECUTION_ENV', 'AWS_Lambda'),
            __version__,
        )

    @property
    def debug(self) -> bool:
        return self._debug

    @debug.setter
    def debug(self, value: bool) -> None:
        self._debug = value
        self._configure_log_level()

    def _configure_logging(self) -> None:
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

    def _already_configured(self, log: logging.Logger) -> bool:
        if not log.handlers:
            return False
        for handler in log.handlers:
            if isinstance(handler, logging.StreamHandler):
                if handler.stream == sys.stdout:
                    return True
        return False

    def _configure_log_level(self) -> None:
        if self._debug:
            level = logging.DEBUG
        else:
            level = logging.ERROR
        self.log.setLevel(level)

    def register_blueprint(self, blueprint: 'Blueprint',
                           name_prefix: Optional[str] = None,
                           url_prefix: Optional[str] = None) -> None:
        blueprint.register(self, options={'name_prefix': name_prefix,
                                          'url_prefix': url_prefix})

    def _register_handler(self, handler_type: str, name: str,
                          user_handler: UserHandlerFuncType,
                          wrapped_handler: Callable[..., Any],
                          kwargs: Any, options: Optional[Dict[Any, Any]] = None
                          ) -> None:
        self._do_register_handler(handler_type, name, user_handler,
                                  wrapped_handler, kwargs, options)

    # These are defined here on the Chalice class because we want all the
    # feature flag tracking to live in Chalice and not the DecoratorAPI.
    def _register_on_ws_connect(self, name: str,
                                user_handler: UserHandlerFuncType,
                                handler_string: str,
                                kwargs: Any, **unused: Dict[str, Any]) -> None:
        self._features_used.add('WEBSOCKETS')
        super(Chalice, self)._register_on_ws_connect(
            name, user_handler, handler_string, kwargs, **unused)

    def _register_on_ws_message(self, name: str,
                                user_handler: UserHandlerFuncType,
                                handler_string: str,
                                kwargs: Any, **unused: Dict[str, Any]) -> None:
        self._features_used.add('WEBSOCKETS')
        super(Chalice, self)._register_on_ws_message(
            name, user_handler, handler_string, kwargs, **unused)

    def _register_on_ws_disconnect(self, name: str,
                                   user_handler: UserHandlerFuncType,
                                   handler_string: str, kwargs: Any,
                                   **unused: Dict[str, Any]) -> None:
        self._features_used.add('WEBSOCKETS')
        super(Chalice, self)._register_on_ws_disconnect(
            name, user_handler, handler_string, kwargs, **unused)

    def _get_middleware_handlers(self, event_type: str) -> Any:
        # We're returning a generator here because we want to defer the
        # collection of all middleware until as last as possible (when
        # then handler is actually invoked).  This lets us pick up any
        # middleware that's registered after a handler has been defined,
        # which is the behavior you'd expect.
        return (func for func, filter_type in self.middleware_handlers if
                filter_type in [event_type, 'all'])

    def __call__(self, event: Any, context: Any) -> Dict[str, Any]:
        # For legacy reasons, we can't move the Rest API handler entry
        # point away from this Chalice.__call__ method . However, we can
        # try to extract as much as logic as possible to a separate handler
        # class we can call.  That way it's still structured somewhat similar
        # to the other event handlers which makes it more manageable to
        # implement shared functionality (e.g. middleware).
        self.lambda_context: 'LambdaContext' = context
        handler = RestAPIEventHandler(
            self.routes, self.api, self.log, self.debug,
            middleware_handlers=self._get_middleware_handlers('http'),
        )
        self.current_request: \
            Optional[Request] = handler.create_request_object(event, context)
        return handler(event, context)


class BuiltinAuthConfig(object):
    def __init__(self, name: str, handler_string: str,
                 ttl_seconds: Optional[int] = None,
                 execution_role: Optional[str] = None,
                 header: str = 'Authorization'):
        # We'd also support all the misc config options you can set.
        self.name: str = name
        self.handler_string: str = handler_string
        self.ttl_seconds: Optional[int] = ttl_seconds
        self.execution_role: Optional[str] = execution_role
        self.header: str = header


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
    def __init__(self, name: str, func: Callable[..., Any],
                 scopes: Optional[List[str]] = None) -> None:
        self.name: str = name
        self.func: Callable[
            ['AuthRequest'], Union['AuthResponse', Dict[str, Any]]
        ] = func
        self.scopes: List[str] = scopes or []
        # This is filled in during the @app.authorizer()
        # processing.
        self.config: BuiltinAuthConfig = None  # type: ignore

    def __call__(
            self,
            event: Dict[str, Any],
            context: Dict[str, Any]
    ) -> Dict[str, Any]:
        auth_request = self._transform_event(event)
        result = self.func(auth_request)
        if isinstance(result, AuthResponse):
            return result.to_dict(auth_request)
        return result

    def _transform_event(self, event: Dict[str, Any]) -> 'AuthRequest':
        return AuthRequest(event['type'],
                           event['authorizationToken'],
                           event['methodArn'])

    def with_scopes(self, scopes: List[str]) -> 'ChaliceAuthorizer':
        authorizer_with_scopes = copy.deepcopy(self)
        authorizer_with_scopes.scopes = scopes
        return authorizer_with_scopes


class AuthRequest(object):
    def __init__(self, auth_type: str, token: str, method_arn: str) -> None:
        self.auth_type: str = auth_type
        self.token: str = token
        self.method_arn: str = method_arn


class AuthResponse(object):
    ALL_HTTP_METHODS: List[str] = ['DELETE', 'HEAD', 'OPTIONS',
                                   'PATCH', 'POST', 'PUT', 'GET']

    def __init__(self, routes: List[Union[str, 'AuthRoute']],
                 principal_id: str, context: Optional[Dict[str, str]] = None):
        self.routes: List[Union[str, 'AuthRoute']] = routes
        self.principal_id: str = principal_id
        # The request is used to generate full qualified ARNs
        # that we need for the resource portion of the returned
        # policy.
        if context is None:
            context = {}
        self.context: Dict[str, str] = context

    def to_dict(self, request: AuthRequest) -> Dict[str, Any]:
        return {
            'context': self.context,
            'principalId': self.principal_id,
            'policyDocument': self._generate_policy(request),
        }

    def _generate_policy(self, request: AuthRequest) -> Dict[str, Any]:
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

    def _generate_allowed_resources(self, request: AuthRequest) -> List[str]:
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

    def _generate_arn(
            self,
            route: str,
            request: AuthRequest,
            method: str = '*'
    ) -> str:
        incoming_arn = request.method_arn
        # An incoming_arn would look like this:
        # "arn:aws:execute-api:us-west-2:123:rest-api-id/stage/GET/needs/auth"
        # Then we pull out the rest-api-id and stage, such that:
        #   base = ['rest-api-id', 'stage']
        #
        # We rely on the fact that the first part of the ARN format is fixed
        # as:    arn:<partition>:<service>:<region>:<account-id>:<resource>
        arn_parts = incoming_arn.split(':', 5)
        allowed_resource = arn_parts[-1].split('/')[:2]
        # Now we add in the path components and rejoin everything
        # back together to make a full arn.
        # We're also assuming all HTTP methods (via '*') for now.
        # To support per HTTP method routes the API will need to be updated.
        # We also need to strip off the leading ``/`` so it can be
        # '/'.join(...)'d properly.
        allowed_resource.extend([method, route[1:]])
        last_arn_segment = '/'.join(allowed_resource)
        if route == '*':
            # We also have to handle the '*' case which matches
            # all routes.
            last_arn_segment += route
        arn_parts[-1] = last_arn_segment
        final_arn = ':'.join(arn_parts)
        return final_arn


class AuthRoute(object):
    def __init__(self, path: str, methods: List[str]):
        self.path: str = path
        self.methods: List[str] = methods


class LambdaFunction(object):
    def __init__(self, func: Callable[..., Any], name: str,
                 handler_string: str):
        self.func: Callable[..., Any] = func
        self.name: str = name
        self.handler_string: str = handler_string

    def __call__(self, event: Dict[str, Any],
                 context: Dict[str, Any]
                 ) -> Callable[[Dict[str, Any], Dict[str, Any]], Any]:
        return self.func(event, context)


class BaseEventSourceConfig(object):
    def __init__(self, name: str, handler_string: str) -> None:
        self.name: str = name
        self.handler_string: str = handler_string


class ScheduledEventConfig(BaseEventSourceConfig):
    def __init__(self, name: str, handler_string: str,
                 schedule_expression: Union[str, 'ScheduleExpression'],
                 description: str):
        super(ScheduledEventConfig, self).__init__(name, handler_string)
        self.schedule_expression: \
            Union[str, 'ScheduleExpression'] = schedule_expression
        self.description: str = description


class CloudWatchEventConfig(BaseEventSourceConfig):

    def __init__(self, name: str, handler_string: str,
                 event_pattern: Dict[str, Any]):
        super(CloudWatchEventConfig, self).__init__(name, handler_string)
        self.event_pattern: Dict[str, Any] = event_pattern


class ScheduleExpression(object):
    def to_string(self) -> str:
        raise NotImplementedError("to_string")


class Rate(ScheduleExpression):
    MINUTES: str = 'MINUTES'
    HOURS: str = 'HOURS'
    DAYS: str = 'DAYS'

    def __init__(self, value: int, unit: str) -> None:
        self.value: int = value
        self.unit: str = unit

    def to_string(self) -> str:
        unit = self.unit.lower()
        if self.value == 1:
            # Remove the 's' from the end if it's singular.
            # This is required by the cloudwatch events API.
            unit = unit[:-1]
        return 'rate(%s %s)' % (self.value, unit)


class Cron(ScheduleExpression):
    def __init__(self, minutes: Union[str, int], hours: Union[str, int],
                 day_of_month: Union[str, int], month: Union[str, int],
                 day_of_week: Union[str, int], year: Union[str, int]):
        self.minutes: Union[str, int] = minutes
        self.hours: Union[str, int] = hours
        self.day_of_month: Union[str, int] = day_of_month
        self.month: Union[str, int] = month
        self.day_of_week: Union[str, int] = day_of_week
        self.year: Union[str, int] = year

    def to_string(self) -> str:
        return 'cron(%s %s %s %s %s %s)' % (
            self.minutes,
            self.hours,
            self.day_of_month,
            self.month,
            self.day_of_week,
            self.year,
        )


class S3EventConfig(BaseEventSourceConfig):
    def __init__(self, name: str, bucket: str, events: List[str], prefix: str,
                 suffix: str, handler_string: str):
        super(S3EventConfig, self).__init__(name, handler_string)
        self.bucket: str = bucket
        self.events: List[str] = events
        self.prefix: str = prefix
        self.suffix: str = suffix


class SNSEventConfig(BaseEventSourceConfig):

    def __init__(self, name: str, handler_string: str, topic: str):
        super(SNSEventConfig, self).__init__(name, handler_string)
        self.topic: str = topic


class SQSEventConfig(BaseEventSourceConfig):
    def __init__(self, name: str, handler_string: str, queue: Optional[str],
                 queue_arn: Optional[str], batch_size: int,
                 maximum_batching_window_in_seconds: int,
                 maximum_concurrency: Optional[int]):
        super(SQSEventConfig, self).__init__(name, handler_string)
        self.queue: Optional[str] = queue
        self.queue_arn: Optional[str] = queue_arn
        self.batch_size: int = batch_size
        self.maximum_batching_window_in_seconds: int = \
            maximum_batching_window_in_seconds
        self.maximum_concurrency: Optional[int] = maximum_concurrency


class KinesisEventConfig(BaseEventSourceConfig):
    def __init__(self, name: str, handler_string: str, stream: str,
                 batch_size: int, starting_position: str,
                 maximum_batching_window_in_seconds: int) -> None:
        super(KinesisEventConfig, self).__init__(name, handler_string)
        self.stream: str = stream
        self.batch_size: int = batch_size
        self.starting_position: str = starting_position
        self.maximum_batching_window_in_seconds: int = \
            maximum_batching_window_in_seconds


class DynamoDBEventConfig(BaseEventSourceConfig):
    def __init__(self, name: str, handler_string: str, stream_arn: str,
                 batch_size: int, starting_position: str,
                 maximum_batching_window_in_seconds: int) -> None:
        super(DynamoDBEventConfig, self).__init__(name, handler_string)
        self.stream_arn: str = stream_arn
        self.batch_size: int = batch_size
        self.starting_position: str = starting_position
        self.maximum_batching_window_in_seconds: int = \
            maximum_batching_window_in_seconds


class WebsocketConnectConfig(BaseEventSourceConfig):
    CONNECT_ROUTE: str = '$connect'

    def __init__(self, name: str, handler_string: str,
                 user_handler: UserHandlerFuncType):
        super(WebsocketConnectConfig, self).__init__(name, handler_string)
        self.route_key_handled = self.CONNECT_ROUTE
        self.handler_function = user_handler


class WebsocketMessageConfig(BaseEventSourceConfig):
    def __init__(self, name: str, route_key_handled: str, handler_string: str,
                 user_handler: UserHandlerFuncType) -> None:
        super(WebsocketMessageConfig, self).__init__(name, handler_string)
        self.route_key_handled: str = route_key_handled
        self.handler_function: Callable[..., Any] = user_handler


class WebsocketDisconnectConfig(BaseEventSourceConfig):
    DISCONNECT_ROUTE: str = '$disconnect'

    def __init__(self, name: str, handler_string: str,
                 user_handler: UserHandlerFuncType):
        super(WebsocketDisconnectConfig, self).__init__(name, handler_string)
        self.route_key_handled = self.DISCONNECT_ROUTE
        self.handler_function = user_handler


class PureLambdaWrapper(object):
    def __init__(self,
                 original_func: Callable[
                     [Dict[str, Any], Optional[Dict[str, Any]]], Any
                 ]
                 ):
        self._original_func = original_func

    def __call__(self, event: 'BaseLambdaEvent') -> Any:
        # The @app.lambda_function() expects an event dict
        # and a context argument so this class will is used to adapt
        # from the Chalice single-arg style function (which is used
        # in all the event handlers) to the low-level lambda api.
        return self._original_func(event.to_dict(), event.context)


class MiddlewareHandler(object):
    def __init__(self, handler: Callable[..., Any],
                 next_handler: Callable[..., Any]) -> None:
        self.handler: Callable[..., Any] = handler
        self.next_handler: Callable[..., Any] = next_handler

    def __call__(self, request: Any) -> Any:
        return self.handler(request, self.next_handler)


class BaseLambdaHandler(object):
    def __call__(self, event: Any, context: Any) -> Any:
        pass

    def _build_middleware_handlers(self, handlers: List[Callable[..., Any]],
                                   original_handler: Callable[..., Any]
                                   ) -> Callable[..., Any]:
        current = original_handler
        for handler in reversed(list(handlers)):
            current = MiddlewareHandler(handler=handler, next_handler=current)
        return current


class EventSourceHandler(BaseLambdaHandler):

    def __init__(
            self, func: Callable[..., Any], event_class: Any,
            middleware_handlers: Optional[List[Callable[..., Any]]] = None
    ) -> None:
        self.func: Callable[..., Any] = func
        self.event_class: Any = event_class
        if middleware_handlers is None:
            middleware_handlers = []
        self._middleware_handlers: \
            List[Callable[..., Any]] = middleware_handlers
        self.handler: Optional[Callable[..., Any]] = None

    @property
    def middleware_handlers(self) -> List[Callable[..., Any]]:
        return self._middleware_handlers

    @middleware_handlers.setter
    def middleware_handlers(self, value: List[Callable[..., Any]]) -> None:
        self._middleware_handlers = value

    def __call__(self, event: Any, context: Any) -> Any:
        event_obj = self.event_class(event, context)
        if self.handler is None:
            # Defer creating handlers so we have all middleware configured.
            self.handler = self._build_middleware_handlers(
                self._middleware_handlers, original_handler=self.func)
        return self.handler(event_obj)


class WebsocketEventSourceHandler(EventSourceHandler):
    WEBSOCKET_API_RESPONSE = {'statusCode': 200}

    def __init__(self, func: Callable[..., Any],
                 event_class: Any, websocket_api: WebsocketAPI,
                 middleware_handlers: Optional[List[Callable[..., Any]]] = None
                 ) -> None:
        super(WebsocketEventSourceHandler, self).__init__(func, event_class,
                                                          middleware_handlers)
        self.websocket_api: WebsocketAPI = websocket_api

    def __call__(self, event: Dict[str, Any],
                 context: Dict[str, Any]) -> Dict[str, Any]:
        self.websocket_api.configure_from_api_id(
            event['requestContext']['apiId'],
            event['requestContext']['stage'],
        )
        response = super(
            WebsocketEventSourceHandler, self).__call__(event, context)
        data = None
        if isinstance(response, Response):
            data = response.to_dict()
        elif isinstance(response, dict):
            data = response
            if "statusCode" not in data:
                data = {**self.WEBSOCKET_API_RESPONSE, **data}
        return data or self.WEBSOCKET_API_RESPONSE


class RestAPIEventHandler(BaseLambdaHandler):
    def __init__(self, route_table: Dict[str, Dict[str, RouteEntry]],
                 api: APIGateway, log: logging.Logger, debug: bool,
                 middleware_handlers: Optional[List[Callable[..., Any]]] = None
                 ) -> None:
        self.routes: Dict[str, Dict[str, RouteEntry]] = route_table
        self.api: APIGateway = api
        self.log: logging.Logger = log
        self.debug: bool = debug
        self.current_request: Optional[Request] = None
        self.lambda_context: Optional['LambdaContext'] = None
        if middleware_handlers is None:
            middleware_handlers = []
        self._middleware_handlers: \
            List[Callable[..., Any]] = middleware_handlers

    def _global_error_handler(self, event: Any,
                              get_response: Callable[..., Any]) -> Response:
        try:
            return get_response(event)
        except Exception:
            return self._unhandled_exception_to_response()

    def create_request_object(self, event: Any,
                              context: Any) -> Optional[Request]:
        # For legacy reasons, there's some initial validation that takes
        # place before we convert the input event to a python object.
        # We don't do this in event handlers we added later, so we *should*
        # be able to remove this code.  To be safe, we're keeping it in for
        # now to minimize the potential for breaking changes.
        resource_path = event.get('requestContext', {}).get('resourcePath')
        if resource_path is not None:
            self.current_request = Request(event, context)
            return self.current_request
        return None

    def __call__(self, event: Any, context: Any) -> Any:
        def wrapped_event(request: Request) -> Response:
            return self._main_rest_api_handler(event, context)

        final_handler = self._build_middleware_handlers(
            [self._global_error_handler] + list(self._middleware_handlers),
            original_handler=wrapped_event,
        )
        response = final_handler(self.current_request)
        return response.to_dict(self.api.binary_types)

    def _main_rest_api_handler(self, event: Any, context: Any) -> Response:
        resource_path = event.get('requestContext', {}).get('resourcePath')
        if resource_path is None:
            return error_response(error_code='InternalServerError',
                                  message='Unknown request.',
                                  http_status_code=500)
        http_method = event['requestContext']['httpMethod']
        if http_method not in self.routes[resource_path]:
            allowed_methods = ', '.join(self.routes[resource_path].keys())
            return error_response(
                error_code='MethodNotAllowedError',
                message='Unsupported method: %s' % http_method,
                http_status_code=405,
                headers={'Allow': allowed_methods})
        route_entry = self.routes[resource_path][http_method]
        view_function = route_entry.view_function
        function_args = {name: event['pathParameters'][name]
                         for name in route_entry.view_args}
        self.lambda_context = context
        # We're getting the CORS headers before validation to be able to
        # output desired headers with
        cors_headers = None
        if self._cors_enabled_for_route(route_entry):
            cors_headers = self._get_cors_headers(route_entry.cors)
        # We're doing the header validation after creating the request
        # so can leverage the case insensitive dict that the Request class
        # uses for headers.
        if self.current_request and route_entry.content_types:
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
        if self.current_request and not self._validate_binary_response(
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
        return response

    def _validate_binary_response(self,
                                  request_headers: CaseInsensitiveMapping,
                                  response_headers: CaseInsensitiveMapping
                                  ) -> bool:
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

    def _get_view_function_response(self, view_function: Callable[..., Any],
                                    function_args: Dict[str, Any]) -> Response:
        try:
            response = view_function(**function_args)
            if not isinstance(response, Response):
                response = Response(body=response)
            self._validate_response(response)
        except ChaliceUnhandledError:
            # Reraise this exception so that middleware has a chance
            # to handle the exception.
            raise
        except ChaliceViewError as e:
            # Any chalice view error should propagate.  These
            # get mapped to various HTTP status codes in API Gateway.
            response = Response(body={'Code': e.__class__.__name__,
                                      'Message': str(e)},
                                status_code=e.STATUS_CODE)
        except Exception:
            response = self._unhandled_exception_to_response()
        return response

    def _unhandled_exception_to_response(self) -> Response:
        headers: HeadersType = {}
        path = getattr(self.current_request, 'path', 'unknown')
        self.log.error("Caught exception for path %s", path, exc_info=True)
        if self.debug:
            # If the user has turned on debug mode,
            # we'll let the original exception propagate so
            # they get more information about what went wrong.
            stack_trace = ''.join(traceback.format_exc())
            body: Any = stack_trace
            headers['Content-Type'] = 'text/plain'
        else:
            body = {'Code': 'InternalServerError',
                    'Message': 'An internal server error occurred.'}
        response = Response(body=body, headers=headers, status_code=500)
        return response

    def _validate_response(self, response: Response) -> None:
        for header, value in response.headers.items():
            if '\n' in value:
                raise ChaliceError("Bad value for header '%s': %r" %
                                   (header, value))

    def _cors_enabled_for_route(self, route_entry: RouteEntry) -> bool:
        return route_entry.cors is not None

    def _get_cors_headers(self, cors: CORSConfig) -> Dict[str, Any]:
        return cors.get_access_control_headers()

    def _add_cors_headers(self, response: Response,
                          cors_headers: Dict[str, str]) -> None:
        for name, value in cors_headers.items():
            if name not in response.headers:
                response.headers[name] = value


# These classes contain all the event types that are passed
# in as arguments in the lambda event handlers.  These are
# part of Chalice's public API and must be backwards compatible.

class BaseLambdaEvent(object):
    def __init__(self, event_dict: Dict[str, Any],
                 context: Optional[Dict[str, Any]]) -> None:
        self._event_dict: Dict[str, Any] = event_dict
        self.context: Optional[Dict[str, Any]] = context
        self._extract_attributes(event_dict)

    def _extract_attributes(self, event_dict: Dict[str, Any]) -> None:
        raise NotImplementedError("_extract_attributes")

    def to_dict(self) -> Dict[str, Any]:
        return self._event_dict


# This class is only used for middleware handlers because
# we can't change the existing interface for @app.lambda_function().
# This could be a Chalice 2.0 thing where we make all the decorators
# have a consistent interface that takes a single event arg.
class LambdaFunctionEvent(BaseLambdaEvent):
    def __init__(self, event_dict: Dict[str, Any], context: Any) -> None:
        self.event: Dict[str, Any] = event_dict
        self.context: Optional[Dict[str, Any]] = context

    def _extract_attributes(self, event_dict: Dict[str, Any]) -> None:
        pass

    def to_dict(self) -> Dict[str, Any]:
        return self.event


class CloudWatchEvent(BaseLambdaEvent):
    def _extract_attributes(self, event_dict: Dict[str, Any]) -> None:
        self.version: str = event_dict['version']
        self.account: str = event_dict['account']
        self.region: str = event_dict['region']
        self.detail: Dict[str, Any] = event_dict['detail']
        self.detail_type: str = event_dict['detail-type']
        self.source: str = event_dict['source']
        self.time: str = event_dict['time']
        self.event_id: str = event_dict['id']
        self.resources: List[str] = event_dict['resources']


class WebsocketEvent(BaseLambdaEvent):
    def __init__(self, event_dict: Dict[str, Any], context: Any):
        super(WebsocketEvent, self).__init__(event_dict, context)
        self._json_body: Optional[Dict[str, Any]] = None

    def _extract_attributes(self, event_dict: Dict[str, Any]) -> None:
        request_context = event_dict['requestContext']
        self.domain_name: str = request_context['domainName']
        self.stage: str = request_context['stage']
        self.connection_id: str = request_context['connectionId']
        self.body: str = str(event_dict.get('body'))

    @property
    def json_body(self) -> Dict[str, Any]:
        if self._json_body is None:
            try:
                self._json_body = json.loads(self.body)
            except ValueError:
                raise BadRequestError('Error Parsing JSON')
        return self._json_body


class SNSEvent(BaseLambdaEvent):

    def _extract_attributes(self, event_dict: Dict[str, Any]) -> None:
        first_record = event_dict['Records'][0]
        self.message: str = first_record['Sns']['Message']
        self.subject: str = first_record['Sns']['Subject']
        self.message_attributes: Dict[str, Any] = \
            first_record['Sns']['MessageAttributes']


class S3Event(BaseLambdaEvent):
    def _extract_attributes(self, event_dict: Dict[str, Any]) -> None:
        s3 = event_dict['Records'][0]['s3']
        self.bucket: str = s3['bucket']['name']
        self.key: str = unquote_plus(s3['object']['key'])


class SQSEvent(BaseLambdaEvent):
    def _extract_attributes(self, event_dict: Dict[str, Any]) -> None:
        # We don't extract anything off the top level
        # event.
        pass

    def __iter__(self) -> Iterator['SQSRecord']:
        for record in self._event_dict['Records']:
            yield SQSRecord(record, self.context)


class SQSRecord(BaseLambdaEvent):

    def _extract_attributes(self, event_dict: Dict[str, Any]) -> None:
        self.body: str = event_dict['body']
        self.receipt_handle: str = event_dict['receiptHandle']


class KinesisEvent(BaseLambdaEvent):
    def _extract_attributes(self, event_dict: Dict[str, Any]) -> None:
        pass

    def __iter__(self) -> Iterator['KinesisRecord']:
        for record in self._event_dict['Records']:
            yield KinesisRecord(record, self.context)


class KinesisRecord(BaseLambdaEvent):
    def _extract_attributes(self, event_dict: Dict[str, Any]) -> None:
        kinesis = event_dict['kinesis']
        encoded_payload = kinesis['data']
        self.data: bytes = base64.b64decode(encoded_payload)
        self.sequence_number: str = kinesis['sequenceNumber']
        self.partition_key: str = kinesis['partitionKey']
        self.schema_version: str = kinesis['kinesisSchemaVersion']
        self.timestamp: datetime.datetime = datetime.datetime.utcfromtimestamp(
            kinesis['approximateArrivalTimestamp'])


class DynamoDBEvent(BaseLambdaEvent):
    def _extract_attributes(self, event_dict: Dict[str, Any]) -> None:
        pass

    def __iter__(self) -> Iterator['DynamoDBRecord']:
        for record in self._event_dict['Records']:
            yield DynamoDBRecord(record, self.context)


class DynamoDBRecord(BaseLambdaEvent):

    def _extract_attributes(self, event_dict: Dict[str, Any]) -> None:
        dynamodb = event_dict['dynamodb']
        self.timestamp: datetime.datetime = datetime.datetime.utcfromtimestamp(
            dynamodb['ApproximateCreationDateTime'])
        self.keys: Any = dynamodb.get('Keys')
        self.new_image: Any = dynamodb.get('NewImage')
        self.old_image: Any = dynamodb.get('OldImage')
        self.sequence_number: str = dynamodb['SequenceNumber']
        self.size_bytes: int = dynamodb['SizeBytes']
        self.stream_view_type: str = dynamodb['StreamViewType']
        # These are from the top level keys in a record.
        self.aws_region: str = event_dict['awsRegion']
        self.event_id: str = event_dict['eventID']
        self.event_name: str = event_dict['eventName']
        self.event_source_arn: str = event_dict['eventSourceARN']

    @property
    def table_name(self) -> str:
        # Converts:
        # "arn:aws:dynamodb:us-west-2:12345:table/MyTable/"
        # "stream/2020-09-28T16:49:14.209"
        #
        # into:
        # "MyTable"
        parts = self.event_source_arn.split(':', 5)
        if not len(parts) == 6:
            return ''
        full_name = parts[-1]
        name_parts = full_name.split('/')
        if len(name_parts) >= 2:
            return name_parts[1]
        return ''


class Blueprint(DecoratorAPI):
    def __init__(self, import_name: str) -> None:
        self._import_name = import_name
        self._deferred_registrations: \
            List[Callable[[Chalice, Dict[str, Any]], None]] = []
        self._current_app: Optional[Chalice] = None
        self._lambda_context = None

    @property
    def log(self) -> logging.Logger:
        if self._current_app is None:
            raise RuntimeError(
                "Can only access Blueprint.log if it's registered to an app."
            )
        return self._current_app.log

    @property
    def current_request(self) -> Request:
        if self._current_app is None or \
                self._current_app.current_request is None:
            raise RuntimeError(
                "Can only access Blueprint.current_request if it's registered "
                "to an app."
            )
        return self._current_app.current_request

    @property
    def current_app(self) -> Chalice:
        if self._current_app is None:
            raise RuntimeError(
                "Can only access Blueprint.current_app if it's registered "
                "to an app."
            )
        return self._current_app

    @property
    def lambda_context(self) -> 'LambdaContext':
        if self._current_app is None:
            raise RuntimeError(
                "Can only access Blueprint.lambda_context if it's registered "
                "to an app."
            )
        return self._current_app.lambda_context

    def register(self, app: Chalice, options: Dict[str, Any]) -> None:
        self._current_app = app
        all_options = options.copy()
        all_options['module_name'] = self._import_name
        for function in self._deferred_registrations:
            function(app, all_options)

    # Note on blueprints implementation.  One option we have for implementing
    # blueprints is to copy every decorator in our public API over to the
    # Blueprints class.  Instead what we do is inherit from DecoratorAPI so we
    # get new decorators for free.  The tradeoff is that need to add
    # implementations of the internal methods used to manage handler
    # registration that defer registration until we get an app object. While
    # these methods are not public in the sense that we don't want users to
    # call them, they're available for blueprints to use in order to avoid
    # boilerplate code.

    def register_middleware(self, func: Callable,
                            event_type: str = 'all') -> None:
        self._deferred_registrations.append(
            lambda app, options: app.register_middleware(
                func, event_type
            )
        )

    def _register_handler(self, handler_type: str, name: str,
                          user_handler: UserHandlerFuncType,
                          wrapped_handler: Any, kwargs: Dict[str, Any],
                          options: Optional[Dict[Any, Any]] = None
                          ) -> None:
        # If we go through the public API (app.route, app.schedule, etc) then
        # we have to duplicate either the methods or the params in this
        # class.  We're using _register_handler as a tradeoff for cutting
        # down on the duplication.
        def _register_blueprint_handler(app: Chalice,
                                        options: Dict[Any, Any]
                                        ) -> None:
            if handler_type in _EVENT_CLASSES:
                # pylint: disable=protected-access
                wrapped_handler.middleware_handlers = \
                    app._get_middleware_handlers(
                        _MIDDLEWARE_MAPPING[handler_type])
            # pylint: disable=protected-access
            app._register_handler(
                handler_type, name, user_handler, wrapped_handler,
                kwargs, options
            )
        self._deferred_registrations.append(_register_blueprint_handler)

    def _get_middleware_handlers(self, event_type: str) -> List:
        # This will get filled in later during the registration process.
        return []


# This class is used to convert any existing/3rd party decorators
# that work directly on lambda functions with the original signature
# of (event, context).  By using ConvertToMiddleware you can automatically
# apply this decorator to every lambda function in a Chalice app.
# Example:
#
# Before:
#
# @third_part.decorator
# def some_lambda_function(event, context): pass
#
# Now:
#
# app.register_middleware(ConvertToMiddleware(third_party.decorator))
#
#
class ConvertToMiddleware(object):
    def __init__(self, lambda_wrapper: Callable[..., Any]) -> None:
        self._wrapper = lambda_wrapper

    def __call__(self, event: Any, get_response: Callable[..., Any]) -> Any:
        original_event, context = self._extract_original_param(event)

        @functools.wraps(self._wrapper)
        def wrapped(original_event: Any, context: Any) -> Any:
            return get_response(event)
        return self._wrapper(wrapped)(original_event, context)

    def _extract_original_param(self, event: Any) -> Tuple[Any, Optional[Any]]:
        if isinstance(event, Request):
            return event.to_original_event(), event.lambda_context
        return event.to_dict(), event.context


_EVENT_CLASSES = {
    'on_s3_event': S3Event,
    'on_sns_message': SNSEvent,
    'on_sqs_message': SQSEvent,
    'on_cw_event': CloudWatchEvent,
    'on_kinesis_record': KinesisEvent,
    'on_dynamodb_record': DynamoDBEvent,
    'schedule': CloudWatchEvent,
    'lambda_function': LambdaFunctionEvent,
}


_MIDDLEWARE_MAPPING = {
    'on_s3_event': 's3',
    'on_sns_message': 'sns',
    'on_sqs_message': 'sqs',
    'on_cw_event': 'cloudwatch',
    'on_kinesis_record': 'kinesis',
    'on_dynamodb_record': 'dynamodb',
    'schedule': 'scheduled',
    'lambda_function': 'pure_lambda',
}
