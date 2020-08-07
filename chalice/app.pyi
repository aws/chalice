from typing import Dict, List, Any, Callable, Union, Optional, Set, TypedDict
import logging
from chalice.local import LambdaContext

__version__ = ... # type: str

class ChaliceError(Exception): ...
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


ALL_ERRORS = ... # type: List[ChaliceViewError]
_BUILTIN_AUTH_FUNC = Callable[
    Union[AuthRequest, RequestAuthorizerRequest], Union[AuthResponse, Dict[str, Any]]]


class Authorizer:
    name = ... # type: str
    scopes = ... # type: List[str]
    def to_swagger(self) -> Dict[str, Any]: ...
    def with_scopes(self, scopes: List[str]) -> Authorizer: ...


class CognitoUserPoolAuthorizer(Authorizer): ...

class IAMAuthorizer(Authorizer): ...

class CustomAuthorizer(Authorizer): ...


class CORSConfig:
    _REQUIRED_HEADERS = ... # type: List[str]
    allow_origin = ... # type: str
    allow_headers = ... # type: str
    get_access_control_headers = ... # type: Callable[..., Dict[str, str]]

    def __init__(self, allow_origin: str='*', allow_headers: Set[str]=None,
                 expose_headers: Set[str]=None, max_age: Optional[int]=None,
                 allow_credentials: Optional[bool]=None) -> None: ...

    def __eq__(self, other: object) -> bool: ...


class Request:
    query_params = ... # type: Dict[str, str]
    headers = ... # type: Dict[str, str]
    uri_params = ... # type: Dict[str, str]
    method = ... # type: str
    body = ... # type: Any
    base64_body = ... # type: str
    context = ... # type: Dict[str, str]
    stage_vars = ... # type: Dict[str, str]

    def __init__(
        self,
        query_params: Dict[str, str],
        headers: Dict[str, str],
        uri_params: Dict[str, str],
        method: str,
        body: Any,
        base64_body: str,
        context: Dict[str, str],
        stage_vars: Dict[str, str]) -> None: ...
    def to_dict(self) -> Dict[Any, Any]: ...


class Response:
    headers = ... # type: Dict[str, Union[str, List[str]]]
    body = ...  # type: Any
    status_code = ... # type: int

    def __init__(self,
                 body: Any,
                 headers: Dict[str, str]=None,
                 status_code: int=200) -> None: ...

    def to_dict(self,
                binary_types: Optional[List[str]]=None) -> Dict[str, Any]: ...


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
                 api_key_required: Optional[bool]=None,
                 content_types: Optional[List[str]]=None,
                 authorizer: Optional[Union[Authorizer,
                                            ChaliceAuthorizer,
                                            ChaliceRequestPayloadAuthorizer]]=None,
                 cors: Union[bool, CORSConfig]=False) -> None: ...

    def _parse_view_args(self) -> List[str]: ...

    def __eq__(self, other: object) -> bool: ...


class APIGateway(object):
    binary_types = ... # type: List[str]


class WebsocketAPI(object):
    session = ... # type: Optional[Any]

    def configure(self,
                  domain_name: str,
                  stage: str) -> None: ...

    def send(self,
             connection_id: str,
             message: str) -> None: ...


class DecoratorAPI(object):
    def authorizer(self,
                   ttl_seconds: Optional[int]=None,
                   execution_role: Optional[str]=None,
                   name: Optional[str]=None) -> Callable[..., Any]: ...

    def request_authorizer(self,
               identity_sources: IdentitySources,
               ttl_seconds: Optional[int]=None,
               execution_role: Optional[str]=None,
               name: Optional[str]=None) -> Callable[..., Any]: ...

    def on_s3_event(self,
                    bucket: str,
                    events: Optional[List[str]]=None,
                    prefix: Optional[str]=None,
                    suffix: Optional[str]=None,
                    name: Optional[str]=None) -> Callable[..., Any]: ...

    def on_sns_message(self,
                      topic: str,
                      name: Optional[str]=None) -> Callable[..., Any]: ...

    def on_sqs_message(self,
                       queue: str,
                       batch_size: int=1,
                       name: Optional[str]=None) -> Callable[..., Any]: ...

    def schedule(self,
                 expression: str,
                 name: Optional[str]=None,
                 description: Optional[str]="") -> Callable[..., Any]: ...

    def route(self, path: str, **kwargs: Any) -> Callable[..., Any]: ...

    def lambda_function(self, name: Optional[str]=None) -> Callable[..., Any]: ...


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
    event_sources = ... # type: List[BaseEventSourceConfig]
    pure_lambda_functions = ... # type: List[LambdaFunction]
    # Used for feature flag validation
    _features_used = ... # type: Set[str]
    experimental_feature_flags = ... # type: Set[str]

    def __init__(self, app_name: str, debug: bool=False,
                 configure_logs: bool=True,
                 env: Optional[Dict[str, str]]=None) -> None: ...

    def __call__(self, event: Any, context: Any) -> Any: ...
    def _get_view_function_response(self,
                                    view_function: Callable[..., Any],
                                    function_args: Dict[str, Any]) -> Response: ...


class BuiltinAuthorizer(object):
    name = ... # type: str
    func = ... # type: _BUILTIN_AUTH_FUNC
    scopes = ... # type: List[str]
    config = ... # type: BuiltinAuthConfig


class ChaliceAuthorizer(object):
    def with_scopes(self, scopes: List[str]) -> ChaliceAuthorizer: ...


class ChaliceRequestPayloadAuthorizer(BuiltinAuthorizer):
    def with_scopes(self, scopes: List[str]) -> ChaliceRequestPayloadAuthorizer: ...
    def stringify_identity_sources(self) -> str: ...


class BuiltinAuthConfig(object):
    name = ... # type: str
    handler_string = ... # type: str
    ttl_seconds = ... # type: int
    execution_role = ... # type: str
    identity_sources = ... # type: dict


class AuthRequest(object):
    auth_type = ... # type: str
    token = ... # type: str
    method_arn = ... # type: str


class RequestAuthorizerRequest(object):
    auth_type =  ... # type: str
    method_arn =  ... # type: str
    headers =  ... # type: Optional[Dict[str, str]]
    query_params =  ... # type: Optional[Dict[str, str]]
    stage_variables =  ... # type: Optional[Dict[str, str]]
    request_context =  ... # type: Optional[Dict[str, str]]


class AuthRoute(object):
    path = ... # type: str
    methods = ... # type: List[str]


class AuthResponse(object):
    ALL_HTTP_METHODS = ... # type: List[str]
    routes = ... # type: Union[str, AuthRoute]
    principal_id = ... # type: str
    context = ... # type: Optional[Dict[str, str]]


class ScheduleExpression(object):
    def to_string(self) -> str: ...


class Rate(ScheduleExpression):
    value = ... # type: int
    unit = ... # type: str

    def to_string(self) -> str: ...


class Cron(ScheduleExpression):
    minutes = ... # type: Union[str, int]
    hours = ... # type: Union[str, int]
    day_of_month = ... # type: Union[str, int]
    month = ... # type: Union[str, int]
    day_of_week = ... # type: Union[str, int]
    year = ... # type: Union[str, int]

    def to_string(self) -> str: ...


class LambdaFunction(object):
    name = ... # type: str
    handler_string = ... # type: str
    func = ... # type: Callable[..., Any]


class BaseEventSourceConfig(object):
    name = ... # type: str
    handler_string = ... # type: str


class S3EventConfig(BaseEventSourceConfig):
    bucket = ... # type: str
    events = ... # type: List[str]
    prefix = ... # type: str
    suffix = ... # type: str


class SNSEventConfig(BaseEventSourceConfig):
    topic = ... # type: str


class SQSEventConfig(BaseEventSourceConfig):
    queue = ... # type: str
    batch_size = ... # type: int


class ScheduledEventConfig(BaseEventSourceConfig):
    schedule_expression = ...  # type: Union[str, ScheduleExpression]
    description = ...  # type: str


class CloudWatchEventConfig(BaseEventSourceConfig):
    event_pattern = ...  # type: Dict


class Blueprint(DecoratorAPI):
    current_request = ... # type: Request
    lambda_context = ... # type: LambdaContext


class IdentitySources(TypedDict):
    headers = ... # type: Optional[List[str]]
    query_strings = ... # type: Optional[List[str]]
    stage_variables = ... # type: Optional[List[str]]
    context = ... # type: Optional[List[str]]