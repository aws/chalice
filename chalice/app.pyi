from typing import Dict, List, Any, Callable, Union, Optional
from chalice.local import LambdaContext

__version__ = ... # type: str

class ChaliceError(Exception): ...
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
    [AuthRequest], Union[AuthResponse, Dict[str, Any]]]


class Authorizer:
    name = ... # type: str
    def to_swagger(self) -> Dict[str, Any]: ...


class CognitoUserPoolAuthorizer(Authorizer): ...

class IAMAuthorizer(Authorizer): ...

class CustomAuthorizer(Authorizer): ...


class CORSConfig:
    allow_origin = ... # type: str
    allow_headers = ... # type: str
    get_access_control_headers = ... # type: Callable[..., Dict[str, str]]

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
    headers = ... # type: Dict[str, str]
    body = ...  # type: Any
    status_code = ... # type: int

    def __init__(self,
                 body: Any,
                 headers: Dict[str, str],
                 status_code: int) -> None: ...

    def to_dict(self) -> Dict[str, Any]: ...


class RouteEntry(object):
    # TODO: How so I specify *args, where args is a tuple of strings.
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

    def __init__(self, view_function: Callable[..., Any],
                 view_name: str, path: str, methods: List[str],
                 authorizer_name: str=None,
                 api_key_required: bool=None,
                 content_types: List[str]=None,
                 cors: Union[bool, CORSConfig]=False) -> None: ...

    def _parse_view_args(self) -> List[str]: ...

    def __eq__(self, other: object) -> bool: ...


class APIGateway(object):
    binary_types = ... # type: List[str]


class Chalice(object):
    app_name = ... # type: str
    api = ... # type: APIGateway
    routes = ... # type: Dict[str, Dict[str, RouteEntry]]
    current_request = ... # type: Request
    lambda_context = ... # type: LambdaContext
    debug = ... # type: bool
    authorizers = ... # type: Dict[str, Dict[str, Any]]
    builtin_auth_handlers = ... # type: List[BuiltinAuthConfig]
    event_sources = ... # type: List[CloudWatchEventSource]
    pure_lambda_functions = ... # type: List[LambdaFunction]

    def __init__(self, app_name: str) -> None: ...

    def route(self, path: str, **kwargs: Any) -> Callable[..., Any]: ...
    def _add_route(self, path: str, view_func: Callable[..., Any], **kwargs: Any) -> None: ...
    def __call__(self, event: Any, context: Any) -> Any: ...
    def _get_view_function_response(self,
                                    view_function: Callable[..., Any],
                                    function_args: List[Any]) -> Response: ...


class ChaliceAuthorizer(object):
    name = ... # type: str
    func = ... # type: _BUILTIN_AUTH_FUNC
    config = ... # type: BuiltinAuthConfig


class BuiltinAuthConfig(object):
    name = ... # type: str
    handler_string = ... # type: str


class AuthRequest(object):
    auth_type = ... # type: str
    token = ... # type: str
    method_arn = ... # type: str


class AuthRoute(object):
    path = ... # type: str
    methods = ... # type: List[str]


class AuthResponse(object):
    ALL_HTTP_METHODS = ... # type: List[str]
    routes = ... # type: Union[str, AuthRoute]
    principal_id = ... # type: str
    context = ... # type: Optional[Dict[str, str]]


class EventSource(object):
    name = ...  # type: str
    handler_string = ...  # type: str


class CloudWatchEventSource(EventSource):
    schedule_expression = ...  # type: Union[str, ScheduleExpression]


class ScheduleExpression(object):
    def to_string(self) -> str: ...


class Rate(ScheduleExpression):
    unit = ... # type: int
    value = ... # type: str

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
