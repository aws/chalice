"""Deploy module for chalice apps.

Handles Lambda and API Gateway deployments.

"""
import textwrap
import socket
import logging

import botocore.exceptions
from botocore.vendored.requests import ConnectionError as \
    RequestsConnectionError
from typing import Optional  # noqa

from chalice.compat import is_broken_pipe_error
from chalice.awsclient import DeploymentPackageTooLargeError
from chalice.awsclient import LambdaClientError
from chalice.constants import MAX_LAMBDA_DEPLOYMENT_SIZE


OPT_STR = Optional[str]
LOGGER = logging.getLogger(__name__)


_AWSCLIENT_EXCEPTIONS = (
    botocore.exceptions.ClientError, LambdaClientError
)


class ChaliceDeploymentError(Exception):
    def __init__(self, error):
        # type: (Exception) -> None
        self.original_error = error
        where = self._get_error_location(error)
        msg = self._wrap_text(
            'ERROR - %s, received the following error:' % where
        )
        msg += '\n\n'
        msg += self._wrap_text(self._get_error_message(error), indent=' ')
        msg += '\n\n'
        suggestion = self._get_error_suggestion(error)
        if suggestion is not None:
            msg += self._wrap_text(suggestion)
        super(ChaliceDeploymentError, self).__init__(msg)

    def _get_error_location(self, error):
        # type: (Exception) -> str
        where = 'While deploying your chalice application'
        if isinstance(error, LambdaClientError):
            where = (
                'While sending your chalice handler code to Lambda to %s '
                'function "%s"' % (
                    self._get_verb_from_client_method(
                        error.context.client_method_name),
                    error.context.function_name
                )
            )
        return where

    def _get_error_message(self, error):
        # type: (Exception) -> str
        msg = str(error)
        if isinstance(error, LambdaClientError):
            if isinstance(error.original_error, RequestsConnectionError):
                msg = self._get_error_message_for_connection_error(
                    error.original_error)
        return msg

    def _get_error_message_for_connection_error(self, connection_error):
        # type: (RequestsConnectionError) -> str

        # To get the underlying error that raised the
        # requests.ConnectionError it is required to go down two levels of
        # arguments to get the underlying exception. The instantiation of
        # one of these exceptions looks like this:
        #
        # requests.ConnectionError(
        #     urllib3.exceptions.ProtocolError(
        #         'Connection aborted.', <SomeException>)
        # )
        message = connection_error.args[0].args[0]
        underlying_error = connection_error.args[0].args[1]

        if is_broken_pipe_error(underlying_error):
            message += (
                ' Lambda closed the connection before chalice finished '
                'sending all of the data.'
            )
        elif isinstance(underlying_error, socket.timeout):
            message += ' Timed out sending your app to Lambda.'
        return message

    def _get_error_suggestion(self, error):
        # type: (Exception) -> OPT_STR
        suggestion = None
        if isinstance(error, DeploymentPackageTooLargeError):
            suggestion = (
                'To avoid this error, decrease the size of your chalice '
                'application by removing code or removing '
                'dependencies from your chalice application.'
            )
            deployment_size = error.context.deployment_size
            if deployment_size > MAX_LAMBDA_DEPLOYMENT_SIZE:
                size_warning = (
                    'This is likely because the deployment package is %s. '
                    'Lambda only allows deployment packages that are %s or '
                    'less in size.' % (
                        self._get_mb(deployment_size),
                        self._get_mb(MAX_LAMBDA_DEPLOYMENT_SIZE)
                    )
                )
                suggestion = size_warning + ' ' + suggestion
        return suggestion

    def _wrap_text(self, text, indent=''):
        # type: (str, str) -> str
        return '\n'.join(
            textwrap.wrap(
                text, 79, replace_whitespace=False, drop_whitespace=False,
                initial_indent=indent, subsequent_indent=indent
            )
        )

    def _get_verb_from_client_method(self, client_method_name):
        # type: (str) -> str
        client_method_name_to_verb = {
            'update_function_code': 'update',
            'create_function': 'create'
        }
        return client_method_name_to_verb.get(
            client_method_name, client_method_name)

    def _get_mb(self, value):
        # type: (int) -> str
        return '%.1f MB' % (float(value) / (1024 ** 2))
