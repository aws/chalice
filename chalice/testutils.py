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
        except ValueError:
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


class TestHTTPClient(object):
    METHODS = (
        'get', 'head', 'post', 'options', 'put',
        'delete', 'trace', 'patch', 'link', 'unlink')

    def __init__(self, app):
        # type: (Chalice) -> None
        self._local_gateway = LocalGateway(app, Config())

    def __getattr__(self, method):
        # type: (str) -> Callable
        if method not in self.METHODS:
            raise AttributeError(
                "'{}' object has no attribute '{}'".format(
                    self.__class__.__name__, method))

        def request(path, headers=None, body=''):
            # type: (str, Optional[Dict[str, str]], str) -> ResponseHandler
            headers = {} if headers is None else headers
            response = self._local_gateway.handle_request(
                method=method.upper(), path=path, headers=headers, body=body)
            return ResponseHandler(response)

        return request
