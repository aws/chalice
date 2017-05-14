import mock
import pytest
from pytest import fixture

from chalice.awsclient import TypedAWSClient
from chalice.awsclient import ResourceDoesNotExistError
from chalice.deploy.paramstore import ParameterStore
from chalice.deploy.paramstore import ParameterStoreError


@fixture
def param_store():
    aws_client = mock.Mock(spec=TypedAWSClient)
    param_store = ParameterStore(aws_client, 'test')
    return aws_client, param_store


def test_set_param(param_store):
    aws_client, store = param_store
    store.set_param('foo', 'bar', False, 'String')
    aws_client.ssm_put_param.assert_called_with(
        'chalice.test.foo', 'bar', False, 'String')


def test_get_param(param_store):
    aws_client, store = param_store
    aws_client.ssm_get_param.return_value = 'bar'
    result = store.get_param('foo', False)
    aws_client.ssm_get_param.assert_called_with('chalice.test.foo', False)
    assert result == 'bar'


def test_delete_param(param_store):
    aws_client, store = param_store
    store.delete_param('foo')
    aws_client.ssm_delete_param.assert_called_with('chalice.test.foo')


def test_delete_param_error(param_store):
    aws_client, store = param_store
    aws_client.ssm_delete_param.side_effect = ResourceDoesNotExistError
    with pytest.raises(ParameterStoreError):
        store.delete_param('foo')
    aws_client.ssm_delete_param.assert_called_with('chalice.test.foo')
