# -*- coding: utf-8 -*-
"""
This is intended only for `pytest-chalice`.

https://github.com/studio3104/pytest-chalice
"""

import json
import re

from logging import getLogger
from typing import Any, Callable, Dict, Optional  # noqa

from chalice import Chalice  # noqa
from chalice.config import Config
from chalice.local import LocalGateway
from chalice.local import EventType, HeaderType  # noqa

logger = getLogger(__name__)

# Python 3.4 or older don't have JSONDecodeError within json module
try:
    JSONDecodeError = json.JSONDecodeError  # type: ignore
except AttributeError:
    JSONDecodeError = ValueError  # type: ignore


class InternalLocalGateway(LocalGateway):
    def __init__(self, *args, **kwargs):
        # type: (Any, Any) -> None
        self.__custom_context = {}  # type: Dict
        super(InternalLocalGateway, self).__init__(*args, **kwargs)

    @property
    def custom_context(self):
        # type: () -> Dict[str, Any]
        return self.__custom_context

    @custom_context.setter
    def custom_context(self, context):
        # type: (Dict[str, Any]) -> None
        self.__custom_context = context

    def _generate_lambda_event(self, method, path, headers, body):
        # type: (str, str, HeaderType, Optional[str])-> EventType
        event = super(
            InternalLocalGateway, self)._generate_lambda_event(
                method, path, headers, body)
        event['requestContext'].update(self.custom_context)
        return event


UPPERCASE_PATTERN = re.compile('([A-Z])')


class ResponseHandler(object):
    def __init__(self, values):
        # type: (Dict[str, Any]) -> None
        self.values = {}  # type: Dict

        for key, value in values.items():
            snake_key = re.sub(
                UPPERCASE_PATTERN, lambda x: '_' + x.group(1).lower(), key)
            self.values[snake_key] = value

        try:
            self.values['json'] = json.loads(self.values['body'])
        except JSONDecodeError:  # type: ignore
            logger.info(
                'Response body is NOT JSON decodable: %s',
                self.values['body'])

    def __getattr__(self, key):
        # type: (str) -> Any
        try:
            return self.values[key]
        except KeyError:
            raise AttributeError(
                "'%s' object has no attribute '%s'" % (
                    self.__class__.__name__, key))


class RequestHandler(object):
    METHODS = (
        'get', 'head', 'post', 'options', 'put',
        'delete', 'trace', 'patch', 'link', 'unlink')

    def __init__(self, app):
        # type: (Chalice) -> None
        self.local_gateway = InternalLocalGateway(app, Config())

    @property
    def custom_context(self):
        # type: () -> Dict[str, Any]
        return self.local_gateway.custom_context

    # As of Chalice version 1.8.0,
    # LocalGateway object doesn't handle Cognito's context
    # like as the warning message below shows,
    #
    # "UserWarning: CognitoUserPoolAuthorizer is not a supported in local mode.
    # All requests made against a route will be authorized
    # to allow local testing."
    #
    # Not only for this purpose,
    # it's an interface provided to allow custom contexts in unit tests.
    @custom_context.setter
    def custom_context(self, context):
        # type: (Dict[str, Any]) -> None
        self.local_gateway.custom_context = context

    def __getattr__(self, method):
        # type: (str) -> Callable
        if method not in self.METHODS:
            raise AttributeError(
                "'{}' object has no attribute '{}'".format(
                    self.__class__.__name__, method))

        def request(path, headers=None, body=''):
            # type: (str, Optional[Dict[str, str]], str) -> ResponseHandler
            headers = {} if headers is None else headers
            response = self.local_gateway.handle_request(
                method=method.upper(), path=path, headers=headers, body=body)
            return ResponseHandler(response)

        return request
