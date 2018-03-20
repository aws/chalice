"""Deploy module for chalice apps.

Handles Lambda and API Gateway deployments.

"""
import sys
import textwrap
import socket
import logging
import warnings

import botocore.exceptions
from botocore.vendored.requests import ConnectionError as \
    RequestsConnectionError
from typing import List, Dict, Optional, Set, Iterator  # noqa

from chalice import app  # noqa
from chalice.compat import is_broken_pipe_error
from chalice.awsclient import DeploymentPackageTooLargeError
from chalice.awsclient import LambdaClientError
from chalice.config import Config  # noqa
from chalice.constants import MAX_LAMBDA_DEPLOYMENT_SIZE


OPT_STR = Optional[str]
LOGGER = logging.getLogger(__name__)


_AWSCLIENT_EXCEPTIONS = (
    botocore.exceptions.ClientError, LambdaClientError
)


def validate_configuration(config):
    # type: (Config) -> None
    """Validate app configuration.

    The purpose of this method is to provide a fail fast mechanism
    for anything we know is going to fail deployment.
    We can detect common error cases and provide the user with helpful
    error messages.

    """
    routes = config.chalice_app.routes
    validate_routes(routes)
    validate_route_content_types(routes, config.chalice_app.api.binary_types)
    _validate_manage_iam_role(config)
    validate_python_version(config)
    validate_unique_function_names(config)


def validate_routes(routes):
    # type: (Dict[str, Dict[str, app.RouteEntry]]) -> None
    # We're trying to validate any kind of route that will fail
    # when we send the request to API gateway.
    # We check for:
    #
    # * any routes that end with a trailing slash.
    for route_name, methods in routes.items():
        if not route_name:
            raise ValueError("Route cannot be the empty string")
        if route_name != '/' and route_name.endswith('/'):
            raise ValueError("Route cannot end with a trailing slash: %s"
                             % route_name)
        _validate_cors_for_route(route_name, methods)


def validate_python_version(config, actual_py_version=None):
    # type: (Config, Optional[str]) -> None
    """Validate configuration matches a specific python version.

    If the ``actual_py_version`` is not provided, it will default
    to the major/minor version of the currently running python
    interpreter.

    :param actual_py_version: The major/minor python version in
        the form "pythonX.Y", e.g "python2.7", "python3.6".

    """
    lambda_version = config.lambda_python_version
    if actual_py_version is None:
        actual_py_version = 'python%s.%s' % sys.version_info[:2]
    if actual_py_version != lambda_version:
        # We're not making this a hard error for now, but we may
        # turn this into a hard fail.
        warnings.warn("You are currently running %s, but the closest "
                      "supported version on AWS Lambda is %s\n"
                      "Please use %s, otherwise you may run into "
                      "deployment issues. " %
                      (actual_py_version, lambda_version, lambda_version),
                      stacklevel=2)


def validate_route_content_types(routes, binary_types):
    # type: (Dict[str, Dict[str, app.RouteEntry]], List[str]) -> None
    for methods in routes.values():
        for route_entry in methods.values():
            _validate_entry_content_type(route_entry, binary_types)


def _validate_entry_content_type(route_entry, binary_types):
    # type: (app.RouteEntry, List[str]) -> None
    binary, non_binary = [], []
    for content_type in route_entry.content_types:
        if content_type in binary_types:
            binary.append(content_type)
        else:
            non_binary.append(content_type)
    if binary and non_binary:
        # A routes content_types be homogeneous in their binary support.
        raise ValueError(
            'In view function "%s", the content_types %s support binary '
            'and %s do not. All content_types must be consistent in their '
            'binary support.' % (route_entry.view_name, binary, non_binary))


def _validate_cors_for_route(route_url, route_methods):
    # type: (str, Dict[str, app.RouteEntry]) -> None
    entries_with_cors = [
        entry for entry in route_methods.values() if entry.cors
    ]
    if entries_with_cors:
        # If the user has enabled CORS, they can't also have an OPTIONS
        # method because we'll create one for them.  API gateway will
        # raise an error about duplicate methods.
        if 'OPTIONS' in route_methods:
            raise ValueError(
                "Route entry cannot have both cors=True and "
                "methods=['OPTIONS', ...] configured.  When "
                "CORS is enabled, an OPTIONS method is automatically "
                "added for you.  Please remove 'OPTIONS' from the list of "
                "configured HTTP methods for: %s" % route_url)

        if not all(entries_with_cors[0].cors == entry.cors for entry in
                   entries_with_cors):
            raise ValueError(
                "Route may not have multiple differing CORS configurations. "
                "Please ensure all views for \"%s\" that have CORS configured "
                "have the same CORS configuration." % route_url
            )


def _validate_manage_iam_role(config):
    # type: (Config) -> None
    # We need to check if manage_iam_role is None because that's the value
    # it the user hasn't specified this value.
    # However, if the manage_iam_role value is not None, the user set it
    # to something, in which case we care if they set it to False.
    if not config.manage_iam_role:
        # If they don't want us to manage the role, they
        # have to specify an iam_role_arn.
        if not config.iam_role_arn:
            raise ValueError(
                "When 'manage_iam_role' is set to false, you "
                "must provide an 'iam_role_arn' in config.json."
            )


def validate_unique_function_names(config):
    # type: (Config) -> None
    names = set()   # type: Set[str]
    for name in _get_all_function_names(config.chalice_app):
        if name in names:
            raise ValueError("Duplicate function name detected: %s\n"
                             "Names must be unique across all lambda "
                             "functions in your Chalice app." % name)
        names.add(name)


def _get_all_function_names(chalice_app):
    # type: (app.Chalice) -> Iterator[str]
    for auth_handler in chalice_app.builtin_auth_handlers:
        yield auth_handler.name
    for event in chalice_app.event_sources:
        yield event.name
    for function in chalice_app.pure_lambda_functions:
        yield function.name


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
