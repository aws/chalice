"""Deploys and fetches keys from the SSM Parameter Store."""
from __future__ import print_function
import botocore.session  # noqa

from chalice.awsclient import TypedAWSClient
from chalice.awsclient import ResourceDoesNotExistError


class ParameterStoreError(Exception):
    pass


def create_default_parameter_store(session, app_name):
    # type: (botocore.session.Session, str) -> ParameterStore
    aws_client = TypedAWSClient(session)
    return ParameterStore(aws_client, app_name)


class ParameterStore(object):
    def __init__(self, aws_client, app_name):
        # type: (TypedAWSClient, str) -> None
        self._aws_client = aws_client
        self._app_name = app_name

    def _key_prefix(self):
        # type: () -> str
        return 'chalice.%s' % self._app_name

    def _full_key_name(self, key):
        # type: (str) -> str
        return '%s.%s' % (self._key_prefix(), key)

    def set_param(self, key, value, overwrite, param_type):
        # type: (str, str, bool, str) -> None
        key = self._full_key_name(key)
        self._aws_client.ssm_put_param(key, value, overwrite, param_type)

    def get_param(self, key, decrypt):
        # type: (str, bool) -> str
        key = self._full_key_name(key)
        result = self._aws_client.ssm_get_param(key, decrypt)
        return result

    def delete_param(self, key):
        # type: (str) -> None
        key = self._full_key_name(key)
        try:
            self._aws_client.ssm_delete_param(key)
        except ResourceDoesNotExistError as e:
            raise ParameterStoreError(e)
