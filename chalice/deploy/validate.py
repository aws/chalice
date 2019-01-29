import sys
import warnings

from typing import Dict, List, Set, Iterator, Optional  # noqa

from chalice import app  # noqa
from chalice.config import Config  # noqa
from chalice.constants import EXPERIMENTAL_ERROR_MSG


class ExperimentalFeatureError(Exception):
    def __init__(self, features_missing_opt_in):
        # type: (Set[str]) -> None
        self.features_missing_opt_in = features_missing_opt_in
        msg = self._generate_msg(features_missing_opt_in)
        super(ExperimentalFeatureError, self).__init__(msg)

    def _generate_msg(self, missing_features):
        # type: (Set[str]) -> str
        opt_in_line = (
            'app.experimental_feature_flags.update([\n'
            '%s\n'
            '])\n' % ',\n'.join(["    '%s'" % feature
                                 for feature in missing_features]))
        return EXPERIMENTAL_ERROR_MSG % opt_in_line


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
    validate_feature_flags(config.chalice_app)


def validate_feature_flags(chalice_app):
    # type: (app.Chalice) -> None
    missing_opt_in = set()
    # pylint: disable=protected-access
    for feature in chalice_app._features_used:
        if feature not in chalice_app.experimental_feature_flags:
            missing_opt_in.add(feature)
    if missing_opt_in:
        raise ExperimentalFeatureError(missing_opt_in)


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
