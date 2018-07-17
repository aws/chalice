"""Abstraction for invoking a lambda function.
"""
import json
import base64

from typing import Optional, Dict  # noqa


_OPT_STR = Optional[str]


class NoSuchFunctionError(Exception):
    """The specified function could not be found."""
    def __init__(self, name):
        # type: (str) -> None
        self.name = name
        super(NoSuchFunctionError, self).__init__()


class LambdaInvoker(object):
    def __init__(self, deployed_resources, client):
        self._deployed_resources = deployed_resources
        self._client = client

    def invoke(self, name, payload=None, context=None):
        # type: (str, _OPT_STR, _OPT_STR) -> None
        try:
            resource = self._deployed_resources.resource_values(name)
            lambda_arn = resource['lambda_arn']
        except (ValueError, KeyError):
            raise NoSuchFunctionError(name)

        # The context needs to be base64 encoded JSON. This also needs to be
        # nested in the custom key or it won't get propogated, so we do that
        # for the user so they don't have to.
        if context is not None:
            custom = json.dumps({'custom': json.loads(context)})
            context = base64.b64encode(custom.encode('utf-8')).decode('utf-8')
        # TODO For now we just let the error propogate. It might be useful
        # later to inspect the type of the resource we are invoking to know
        # its event source and look at the error and know if we can safely
        # retry.
        return self._client.invoke_function(
            lambda_arn,
            payload=payload,
            context=context
        )
