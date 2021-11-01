from typing import (
    Dict,
    List,
    Any,
    Callable,
    Union,
    Optional,
    Set,
    Type,
    Mapping,
    MutableMapping,
    Sequence,
    Iterator,
)
import logging
import datetime
from chalice.local import LambdaContext

__version__ = ... # type: str

class ChaliceError(Exception): ...
class ChaliceUnhandledError(ChaliceError): ...
class WebsocketDisconnectedError(Exception): ...
class ChaliceViewError(ChaliceError):
    __name__ = ... # type: str
    STATUS_CODE = ... # type: int
class BadRequestError(ChaliceViewError): ...
class UnauthorizedError(ChaliceViewError): ...
class ForbiddenError(ChaliceViewError): ...
class NotFoundError(ChaliceViewError): ...
class ConflictError(ChaliceViewError): ...
class UnprocessableEntityError(ChaliceViewError): ...
class TooManyRequestsError(ChaliceViewError): ...
class RequestTimeoutError(ChaliceViewError): ...


ALL_ERRORS = ... # type: List[ChaliceViewError]
_GET_RESPONSE = Callable[[Any], Any]
_MIDDLEWARE_FUNC = Callable[[Any, _GET_RESPONSE], Any]


class Authorizer:
    name = ... # type: str
    scopes = ... # type: List[str]
    def to_swagger(self) -> Dict[str, Any]: ...
    def with_scopes(self, scopes: List[str]) -> Authorizer: ... #pylint: disable=undefined-variable


class CognitoUserPoolAuthorizer(Authorizer):
    def __init__(
        self,
        name: str,
        provider_arns: List[str],
        header: Optional[str],
        scopes: Optional[List]
    ) -> None: ...

class IAMAuthorizer(Authorizer): ...

class CustomAuthorizer(Authorizer):

    def __init__(self, name: str=...,
                 authorizer_uri: str=...,
                 ttl_seconds: int=...,
                 header: str=...,
                 invoke_role_arn: Optional[str]=...,
                 scopes: Optional[List[str]]=...) -> None: ...


class CORSConfig:
    _REQUIRED_HEADERS = ... # type: List[str]
    allow_origin = ... # type: str
    allow_headers = ... # type: Optional[Sequence[str]]
    get_access_control_headers = ... # type: Callable[..., Dict[str, str]]

    def __init__(self, allow_origin: str=...,
                 allow_headers: Optional[Sequence[str]]=...,
                 expose_headers: Optional[Sequence[str]]=...,
                 max_age: Optional[int]=...,
                 allow_credentials: Optional[bool]=...) -> None: ...

    def __eq__(self, other: object) -> bool: ...


class Request:
    query_params = ... # type: Optional[Dict[str, str]]
    headers = ... # type: CaseInsensitiveMapping
    uri_params = ... # type: Optional[Dict[str, str]]
    method = ... # type: str
    body = ... # type: Any
    base64_body = ... # type: str
    context = ... # type: Dict[str, Any]
    stage_vars = ... # type: Optional[Dict[str, str]]
    json_body = ... # type: Any
    path = ... # type: str
    _json_body = ... # type: Optional[Any]
    raw_body = ... # type: Optional[Any]

    def __init__(
        self, event_dict: Dict[str, Any], lambda_context: Optional[Any]
    ) -> None: ...
    def to_dict(self) -> Dict[Any, Any]: ...


class Response:
    headers = ... # type: Dict[str, Union[str, List[str]]]
    body = ...  # type: Any
    status_code = ... # type: int

    def __init__(self,
                 body: Any,
                 headers: Optional[Dict[str, Union[str, List[str]]]]=...,
                 status_code: int=...) -> None: ...

    def to_dict(self,
                binary_types: Optional[List[str]]=...) -> Dict[str, Any]: ...


class RouteEntry(object):
    view_function = ... # type: Callable[..., Any]
    view_name = ... # type: str
    method = ... # type: str
    uri_pattern = ... # type: str
    authorizer_name = ... # type: str
    authorizer = ... # type: Optional[Authorizer]
    api_key_required = ... # type: bool
    content_types = ... # type: List[str]
    view_args = ... # type: List[str]
    cors = ... # type: CORSConfig

    def __init__(self,
                 view_function: Callable[..., Any],
                 view_name: str,
                 path: str,
                 method: str,
                 api_key_required: Optional[bool]=...,
                 content_types: Optional[List[str]]=...,
                 authorizer: Optional[Union[Authorizer,
                                            ChaliceAuthorizer]]=...,
                 cors: Union[bool, CORSConfig]=...) -> None: ...

    def _parse_view_args(self) -> List[str]: ...

    def __eq__(self, other: object) -> bool: ...


class APIGateway(object):
    cors = ... # type: Union[bool, CORSConfig]
    binary_types = ... # type: List[str]
    default_binary_types = ... # type: List[str]


class WebsocketAPI(object):
    session = ... # type: Optional[Any]

    def configure(self,
                  domain_name: str,
                  stage: str) -> None: ...

    def send(self,
             connection_id: str,
             message: str) -> None: ...


class DecoratorAPI(object):
    def register_middleware(self,
                            func: _MIDDLEWARE_FUNC,
                            event_type: str=...) -> None: ...

    def middleware(self, event_type: str=...) -> Callable[..., Any]: ...

    def authorizer(self,
                   ttl_seconds: Optional[int]=...,
                   execution_role: Optional[str]=...,
                   name: Optional[str]=...,
                   header: Optional[str]=...) -> Callable[..., Any]: ...

    def on_s3_event(self,
                    bucket: str,
                    events: Optional[List[str]]=...,
                    prefix: Optional[str]=...,
                    suffix: Optional[str]=...,
                    name: Optional[str]=...) -> Callable[..., Any]: ...

    def on_sns_message(self,
                      topic: str,
                      name: Optional[str]=...) -> Callable[..., Any]: ...

    def on_sqs_message(self,
                       queue: str,
                       batch_size: int=...,
                       name: Optional[str]=...) -> Callable[..., Any]: ...

    def on_cw_event(self,
                    event_pattern: Dict[str, Any],
                    name: Optional[str]=None) -> Callable[..., Any]: ...

    def on_kinesis_record(self,
                          stream: str,
                          batch_size: int=...,
                          startition_position: str=...,
                          name: Optional[str]=...) -> Callable[..., Any]: ...

    def on_dynamodb_record(self,
                           stream_arn: str,
                           batch_size: int=...,
                           startition_position: str=...,
                           name: Optional[str]=...) -> Callable[..., Any]: ...

    def schedule(self,
                 expression: Union[str, Cron, Rate],
                 name: Optional[str]=...,
                 description: Optional[str]=...) -> Callable[..., Any]: ...

    def route(self, path: str, **kwargs: Any) -> Callable[..., Any]: ...

    def lambda_function(self, name: Optional[str]=...) -> Callable[..., Any]: ...

    def on_ws_connect(self, name: Optional[str] = ...) -> Callable[..., Any]: ...

    def on_ws_disconnect(self, name: Optional[str] = ...) -> Callable[..., Any]: ...

    def on_ws_message(self, name: Optional[str] = ...) -> Callable[..., Any]: ...


class Chalice(DecoratorAPI):
    app_name = ... # type: str
    api = ... # type: APIGateway
    routes = ... # type: Dict[str, Dict[str, RouteEntry]]
    websocket_api = ... # type: WebsocketAPI
    websocket_handlers = ... # type: Dict[str, Any]
    current_request = ... # type: Request
    lambda_context = ... # type: LambdaContext
    debug = ... # type: bool
    configure_logs = ... # type: bool
    log = ... # type: logging.Logger
    authorizers = ... # type: Dict[str, Dict[str, Any]]
    builtin_auth_handlers = ... # type: List[BuiltinAuthConfig]
    event_sources = ... # type: List[Type[BaseEventSourceConfig]]
    pure_lambda_functions = ... # type: List[LambdaFunction]
    handler_map = ... # type: Dict[str, Callable[..., Any]]
    # Used for feature flag validation
    _features_used = ... # type: Set[str]
    experimental_feature_flags = ... # type: Set[str]
    FORMAT_STRING = ... # type: str

    def __init__(self, app_name: str, debug: bool=...,
                 configure_logs: bool=...,
                 env: Optional[Dict[str, str]]=...) -> None: ...

    def __call__(self, event: Any, context: Any) -> Any: ...
    def register_blueprint(self, blueprint: Blueprint,
                           name_prefix: Optional[str] = ...,
                           url_prefix: Optional[str] = ...) -> None: ...


class ChaliceAuthorizer(object):
    name = ... # type: str
    func = ... # type: Callable[[AuthRequest], Union[AuthResponse, Dict[str, Any]]]
    scopes = ... # type: List[str]
    config = ... # type: BuiltinAuthConfig
    def with_scopes(self, scopes: List[str]) -> ChaliceAuthorizer: ...


class BuiltinAuthConfig(object):
    name = ... # type: str
    handler_string = ... # type: str
    ttl_seconds = ... # type: Optional[int]
    execution_role = ... # type: Optional[str]
    header = ... # type: str
    def __init__(self, name: str, handler_string: str,
                 ttl_seconds: Optional[int] = ...,
                 execution_role: Optional[str] = ...,
                 header: str = ...) -> None: ...


class AuthRequest(object):
    auth_type = ... # type: str
    token = ... # type: str
    method_arn = ... # type: str

    def __init__(self, auth_type: str, token: str, method_arn: str) -> None: ...


class AuthRoute(object):
    path = ... # type: str
    methods = ... # type: List[str]

    def __init__(self, path: str, methods: List[str]) -> None: ...


class AuthResponse(object):
    ALL_HTTP_METHODS = ... # type: List[str]
    routes = ... # type: List[Union[str, AuthRoute]]
    principal_id = ... # type: str
    context = ... # type: Optional[Dict[str, str]]

    def __init__(
        self,
        routes: List[Union[str, AuthRoute]],
        principal_id: str,
        context: Optional[Dict[str, str]] = ...
    ) -> None: ...

    def to_dict(self, request: AuthRequest) -> Dict[str, Any]: ...


class ScheduleExpression(object):
    def to_string(self) -> str: ...


class Rate(ScheduleExpression):
    MINUTES = ...  # type: str
    HOURS = ...  # type: str
    DAYS = ...  # type: str
    value = ... # type: int
    unit = ... # type: str

    def __init__(self, value: int, unit: str) -> None: ...
    def to_string(self) -> str: ...


class Cron(ScheduleExpression):
    minutes = ... # type: Union[str, int]
    hours = ... # type: Union[str, int]
    day_of_month = ... # type: Union[str, int]
    month = ... # type: Union[str, int]
    day_of_week = ... # type: Union[str, int]
    year = ... # type: Union[str, int]

    def __init__(
        self,
        minutes: Union[str, int], hours: Union[str, int],
        day_of_month: Union[str, int], month: Union[str, int],
        day_of_week: Union[str, int], year: Union[str, int]
    ) -> None: ...
    def to_string(self) -> str: ...


class LambdaFunction(object):
    name = ... # type: str
    handler_string = ... # type: str
    func = ... # type: Callable[..., Any]


class BaseEventSourceConfig(object):
    name = ... # type: str
    handler_string = ... # type: str
    def __init__(self, name: str, handler_string: str) -> None: ...


class S3EventConfig(BaseEventSourceConfig):
    bucket = ... # type: str
    events = ... # type: List[str]
    prefix = ... # type: str
    suffix = ... # type: str


class SNSEventConfig(BaseEventSourceConfig):
    topic = ... # type: str


class SQSEventConfig(BaseEventSourceConfig):
    queue = ...                              # type: Optional[str]
    queue_arn = ...                          # type: Optional[str]
    batch_size = ...                         # type: int
    maximum_batching_window_in_seconds = ... # type: int

    def __init__(
        self, name: str, handler_string: str, queue: Optional[str],
        queue_arn: Optional[str], batch_size: int, maximum_batching_window_in_seconds: int,
    ) -> None: ...


class ScheduledEventConfig(BaseEventSourceConfig):
    schedule_expression = ...  # type: Union[str, ScheduleExpression]
    description = ...  # type: str


class CloudWatchEventConfig(BaseEventSourceConfig):
    event_pattern = ...  # type: Dict[str, Any]


class KinesisEventConfig(BaseEventSourceConfig):
    stream = ...                             # type: str
    batch_size = ...                         # type: int
    starting_position = ...                  # type: str
    maximum_batching_window_in_seconds = ... # type: int


class DynamoDBEventConfig(BaseEventSourceConfig):
    stream_arn = ...                         # type: str
    batch_size = ...                         # type: int
    starting_position = ...                  # type: str
    maximum_batching_window_in_seconds = ... # type: int


class Blueprint(DecoratorAPI):
    current_request = ... # type: Request
    lambda_context = ... # type: LambdaContext
    current_app = ... # type: Chalice
    log = ... # type: logging.Logger

    def __init__(self, import_name: str) -> None: ...

    def register(self, app: Chalice, options: Dict[str, Any]) -> None: ...

    def register_middleware(self, func: Callable,
                            event_type: str = ...) -> None: ...


class ConvertToMiddleware:
    def __init__(self,
                 lambda_wrapper: Callable[..., Any]) -> None: ...


class MiddlewareHandler(object):
    handler = ... # type: Callable[..., Any]
    next_handler = ... # type: Callable[..., Any]

    def __init__(
        self, handler: Callable[..., Any], next_handler: Callable[..., Any]
    ) -> None: ...
    def __call__(self, request: Any) -> Any: ...


class BaseLambdaHandler(object):
    def __call__(self, event: Any, context: Any) -> Any: ...
    def _build_middleware_handlers(
        self, handlers: List[Callable[..., Any]], original_handler: Callable[..., Any]
    ) -> MiddlewareHandler: ...


class RestAPIEventHandler(BaseLambdaHandler):
    api = ... # type: APIGateway
    routes = ... # type: Dict[str, Dict[str, RouteEntry]]
    debug = ... # type: bool
    log = ... # type: logging.Logger
    current_request = ... # type: Optional[Request]
    lambda_context = ... # type: Optional[LambdaContext]
    _middleware_handlers = ... # type: Optional[List[MiddlewareHandler]]

    def __init__(
        self,
        route_table: Dict[str, Dict[str, RouteEntry]],
        api: APIGateway,
        log: logging.Logger,
        debug: bool,
        middleware_handlers: Optional[List[MiddlewareHandler]]
    ) -> None: ...
    def _global_error_handler(
        self, event: Any, get_response: Callable[..., Any]
    ) -> Response: ...
    def create_request_object(self, event: Any, context: Any) -> Optional[Request]: ...
    def __call__(self, event: Any, context: Any) -> Any: ...
    def _main_rest_api_handler(self, event: Any, context: Any) -> Response: ...
    def _validate_binary_response(
        self, request_headers: Dict[str, str], response_headers: CaseInsensitiveMapping
    ) -> bool: ...
    def _get_view_function_response(
        self, view_function: Callable[..., Any], function_args: Dict[str, Any]
    ) -> Response: ...
    def _unhandled_exception_to_response(self) -> Response: ...
    def _validate_response(self, response: Response) -> None: ...
    def _cors_enabled_for_route(self, route_entry: RouteEntry) -> bool: ...
    def _get_cors_headers(self, cors: CORSConfig) -> Dict[str, Any]: ...
    def _add_cors_headers(self, response: Response, cors_headers: Dict[str, str]) -> None: ...


class EventSourceHandler(BaseLambdaHandler):
    func = ... # type: Callable[..., Any]
    event_class = ... # type: Any
    handler = ... # type: Optional[Callable[..., Any]]
    middleware_handlers = ... # type: List[Callable[..., Any]]
    _middleware_handlers = ... # type: List[Callable[..., Any]]

    def __init__(
        self,
        func: Callable[..., Any],
        event_class: Any,
        middleware_handlers: Optional[List[Callable[..., Any]]]
    ) -> None: ...
    def __call__(self, event: Any, context: Any) -> Any: ...


class BaseLambdaEvent(object):
    _event_dict = ... # type: Dict[Any, Any]
    context = ... # type: Optional[Dict[str, Any]]

    def __init__(self, event_dict: Dict[str, Any], context: Any) -> None: ...
    def _extract_attributes(self, event_dict: Dict[str, Any]) -> None: ...
    def to_dict(self) -> Dict[str, Any]: ...


class LambdaFunctionEvent(BaseLambdaEvent):
    event = ... # type: Dict[str, Any]
    context = ...  # type: Optional[Dict[str, Any]]

    def __init__(self, event_dict: Dict[str, Any], context: Any) -> None: ...


class CloudWatchEvent(BaseLambdaEvent):
    version = ... # type: str
    account = ... # type: str
    region = ... # type: str
    detail = ... # type: Dict[str, Any]
    detail_type = ... # type: str
    source = ... # type: str
    time = ... # type: str
    event_id = ... # type: str
    resources = ... # type: List[str]


class SQSRecord(BaseLambdaEvent):
    body = ... # type: str
    receipt_handle = ... # type: str


class SQSEvent(BaseLambdaEvent):
    def __iter__(self) -> Iterator[SQSRecord]: ...


class SNSEvent(BaseLambdaEvent):
    message = ... # type: str
    subject = ... # type: str


class S3Event(BaseLambdaEvent):
    bucket = ... # type: str
    key = ... # type: str


class KinesisRecord(BaseLambdaEvent):
    data = ... # type: bytes
    sequence_number = ... # type: str
    partition_key = ... # type: str
    schema_version = ... # type: str
    timestamp = ... # type: datetime.datetime


class KinesisEvent(BaseLambdaEvent):
    def __iter__(self) -> Iterator[KinesisRecord]: ...


class DynamoDBRecord(BaseLambdaEvent):
    @property
    def table_name(self) -> str: ...

    timestamp = ... # type: datetime.datetime
    keys = ... # type: Any
    new_image = ... # type: Any
    old_image = ... # type: Any
    sequence_number = ... # type: str
    size_bytes = ... # type: int
    stream_view_type = ... # type: str
    aws_region = ... # type: str
    event_id = ... # type: str
    event_name = ... # type: str
    event_source_arn = ... # type: str


class DynamoDBEvent(BaseLambdaEvent):
    def __iter__(self) -> Iterator[DynamoDBRecord]: ...


class MultiDict(MutableMapping):
    _dict = ...  # type: Dict[Any, Any]

    def __init__(self, mapping: Dict[Any, Any]) -> None: ...
    def __getitem__(self, k: str) -> Optional[Any]: ...
    def __setitem__(self, k: str, v: Any) -> None: ...
    def __delitem__(self, k: str) -> None: ...
    def getlist(self, k: str) -> List[Any]: ...
    def __len__(self) -> int: ...
    def __iter__(self) -> Any: ...
    def __repr__(self) -> str: ...
    def __str__(self) -> str: ...


class CaseInsensitiveMapping(Mapping):
    _dict = ... # type: Dict[Any, Any]

    def __init__(self, mapping: Dict[Any, Any]) -> None: ...
    def __getitem__(self, key: str) -> Any: ...
    def __iter__(self) -> Any: ...
    def __len__(self) -> int: ...
    def __repr__(self) -> str: ...


class WebsocketEvent(BaseLambdaEvent):
    domain_name = ... # type: str
    stage = ... # type: str
    connection_id = ... # type: str
    body = ... # type: str


unquote_str = ... # type: Callable[..., Any]
