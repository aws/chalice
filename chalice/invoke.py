"""Abstraction for invoking a lambda function."""
import json

from typing import Any, Optional, Dict, List, Union, Tuple  # noqa

from chalice.config import DeployedResources  # noqa
from chalice.awsclient import TypedAWSClient  # noqa
from chalice.utils import UI  # noqa
from chalice.compat import StringIO


OptBytes = Optional[bytes]
_ERROR_KEY = 'FunctionError'
_ERROR_VALUE = 'Unhandled'


def _response_is_error(response):
    # type: (Dict[str, Any]) -> bool
    return response.get(_ERROR_KEY) == _ERROR_VALUE


class UnhandledLambdaError(Exception):
    pass


class LambdaInvokeHandler(object):
    """Handler class to coordinate making an invoke call to lambda.

    This class takes a LambdaInvoker, a LambdaResponseFormatter, and a UI
    object in order to make an invoke call against lambda, format the response
    and render it to the UI.
    """
    def __init__(self, invoker, formatter, ui):
        # type: (LambdaInvoker, LambdaResponseFormatter, UI) -> None
        self._invoker = invoker
        self._formatter = formatter
        self._ui = ui

    def invoke(self, payload=None):
        # type: (OptBytes) -> None
        response = self._invoker.invoke(payload)
        formatted_response = self._formatter.format_response(response)
        if _response_is_error(response):
            self._ui.error(formatted_response)
            raise UnhandledLambdaError()
        self._ui.write(formatted_response)


class LambdaInvoker(object):
    def __init__(self, lambda_arn, client):
        # type: (str, TypedAWSClient) -> None
        self._lambda_arn = lambda_arn
        self._client = client

    def invoke(self, payload=None):
        # type: (OptBytes) -> Dict[str, Any]
        return self._client.invoke_function(
            self._lambda_arn,
            payload=payload
        )


class LambdaResponseFormatter(object):
    _PAYLOAD_KEY = 'Payload'

    _TRACEBACK_HEADING = 'Traceback (most recent call last):\n'

    def format_response(self, response):
        # type: (Dict[str, Any]) -> str
        formatted = StringIO()
        payload = response[self._PAYLOAD_KEY].read()
        if _response_is_error(response):
            self._format_error(formatted, payload)
        else:
            self._format_success(formatted, payload)
        return str(formatted.getvalue())

    def _format_error(self, formatted, payload):
        # type: (StringIO, bytes) -> None
        loaded_error = json.loads(payload)
        error_message = loaded_error['errorMessage']
        error_type = loaded_error.get('errorType')
        stack_trace = loaded_error.get('stackTrace')

        if stack_trace is not None:
            self._format_stacktrace(formatted, stack_trace)

        if error_type is not None:
            formatted.write('{}: {}\n'.format(error_type, error_message))
        else:
            formatted.write('{}\n'.format(error_message))

    def _format_stacktrace(self, formatted, stack_trace):
        # type: (StringIO, List[List[Union[str, int]]]) -> None
        formatted.write(self._TRACEBACK_HEADING)
        for frame in stack_trace:
            self._format_frame(formatted, frame)

    def _format_frame(self, formatted, frame):
        # type: (StringIO, Union[str, List[Union[str, int]]]) -> None
        if isinstance(frame, list):
            # If the output is a list, it came from a 4-tuple as a result of
            # an extract_tb call. This is the behavior up to and including
            # python 3.6.
            path, lineno, function, code = frame
            formatted.write(
                '  File "{}", line {}, in {}\n'.format(path, lineno, function))
            formatted.write(
                '    {}\n'.format(code))
        else:
            # If it is not a list, its a string. This is because the 4-tuple
            # was replaced with a FrameSummary object which is serialized as
            # a string by Lambda. In this case we can just print it directly.
            formatted.write(frame)

    def _format_success(self, formatted, payload):
        # type: (StringIO, bytes) -> None
        formatted.write('{}\n'.format(str(payload.decode('utf-8'))))
