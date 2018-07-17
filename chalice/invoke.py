"""Abstraction for invoking a lambda function."""
import json

from typing import Any, Optional, Dict, List, Union  # noqa

from chalice.config import DeployedResources  # noqa
from chalice.awsclient import TypedAWSClient  # noqa
from chalice.utils import UI  # noqa

_OPT_STR = Optional[str]


class NoSuchFunctionError(Exception):
    """The specified function could not be found."""
    def __init__(self, name):
        # type: (str) -> None
        self.name = name
        super(NoSuchFunctionError, self).__init__()


class LambdaInvoker(object):
    def __init__(self, deployed_resources, client):
        # type: (DeployedResources, TypedAWSClient) -> None
        self._deployed_resources = deployed_resources
        self._client = client

    def invoke(self, name, payload=None):
        # type: (str, _OPT_STR) -> Dict[str, Any]
        try:
            resource = self._deployed_resources.resource_values(name)
            lambda_arn = resource['lambda_arn']
        except (ValueError, KeyError):
            raise NoSuchFunctionError(name)

        # TODO For now we just let the error propogate. It might be useful
        # later to inspect the type of the resource we are invoking to know
        # its event source and look at the error and know if we can safely
        # retry.
        return self._client.invoke_function(
            lambda_arn,
            payload=payload
        )


class LambdaResponseFormatter(object):
    _ERROR_KEY = 'FunctionError'
    _ERROR_VALUE = 'Unhandled'
    _PAYLOAD_KEY = 'Payload'

    _TRACEBACK_HEADING = 'Traceback (most recent call last):\n'

    def __init__(self, ui):
        # type: (UI) -> None
        self._ui = ui

    def format_response(self, response):
        # type: (Dict[str, Any]) -> None
        payload = response[self._PAYLOAD_KEY].read()
        if self._ERROR_KEY in response and \
           response[self._ERROR_KEY] == self._ERROR_VALUE:
            self._format_error(payload)
        else:
            self._format_success(payload)

    def _format_error(self, payload):
        # type: (bytes) -> None
        loaded_error = json.loads(payload)
        error_message = loaded_error['errorMessage']
        error_type = loaded_error['errorType']
        stack_trace = loaded_error['stackTrace']

        self._ui.error(self._TRACEBACK_HEADING)
        for frame in stack_trace:
            self._format_frame(frame)
        self._ui.error('{}: {}\n'.format(error_type, error_message))

    def _format_frame(self, frame):
        # type: (List[Union[str, int]]) -> None
        path, lineno, function, code = frame
        self._ui.error(
            '  File "{}", line {}, in {}\n'.format(path, lineno, function))
        self._ui.error(
            '    {}\n'.format(code))

    def _format_success(self, payload):
        # type: (bytes) -> None
        self._ui.write(str(payload.decode('utf-8')))
        self._ui.write('\n')
