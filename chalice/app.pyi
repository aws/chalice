from typing import Dict, List, Any, Callable

class ChaliceError(Exception): ...
class ChaliceViewError(ChaliceError):
    __name__ = ... # type: str
    STATUS_CODE = ... # type: int
class BadRequestError(ChaliceViewError): ...
class UnauthorizedError(ChaliceViewError): ...
class ForbiddenError(ChaliceViewError): ...
class NotFoundError(ChaliceViewError): ...
class ConflictError(ChaliceViewError): ...
class TooManyRequestsError(ChaliceViewError): ...


ALL_ERRORS = ... # type: List[ChaliceViewError]

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


class RouteEntry(object):
    # TODO: How so I specify *args, where args is a tuple of strings.
    view_function = ... # type: Callable[..., Any]
    view_name = ... # type: str
    uri_pattern = ... # type: str
    methods = ... # type: List[str]
    view_args = ... # type: List[str]
    def __init__(self, view_function: Callable[..., Any],
                 view_name: str, path: str, methods: List[str],
                 authorization_type: str=None,
                 authorizer_id: str=None,
                 api_key_required: bool=None,
                 content_types: List[str]=None) -> None: ...

    def _parse_view_args(self) -> List[str]: ...

    def __eq__(self, other: object) -> bool: ...


class Chalice(object):
    app_name = ... # type: str
    routes = ... # type: Dict[str, RouteEntry]
    current_request = ... # type: Request
    debug = ... # type: bool
    def __init__(self, app_name: str) -> None: ...

    def route(self, path: str, **kwargs: Any) -> Callable[..., Any]: ...
    def _add_route(self, path: str, view_func: Callable[..., Any], **kwargs: Any) -> None: ...
    def __call__(self, event: Any, context: Any) -> Any: ...
