import mock
import pytest

from chalice import cli
from chalice.cli.factory import CLIFactory
from chalice.local import LocalDevServer


def test_run_local_server():
    env = {}
    local_stage_test = 'local_test'
    factory = mock.Mock(spec=CLIFactory)
    factory.create_config_obj.return_value.environment_variables = {
        'foo': 'bar',
    }
    factory.create_config_obj.return_value.chalice_app.routes = {}
    local_server = mock.Mock(spec=LocalDevServer)
    factory.create_local_server.return_value = local_server
    cli.run_local_server(factory, '127.0.0.1', 8000, local_stage_test, env)

    local_server.serve_forever.assert_called_with()
    factory.create_config_obj.assert_called_with(
        chalice_stage_name=local_stage_test, env={})


def test_cannot_run_local_mode_with_trailing_slash_route():
    local_stage_test = 'local_test'
    factory = mock.Mock(spec=CLIFactory)
    factory.create_config_obj.return_value.environment_variables = {}
    factory.create_config_obj.return_value.chalice_app.routes = {
        'foobar/': None
    }
    local_server = mock.Mock(spec=LocalDevServer)
    factory.create_local_server.return_value = local_server
    with pytest.raises(ValueError) as e:
        cli.run_local_server(factory, 'localhost', 8000, local_stage_test, {})
    assert str(e.value) == 'Route cannot end with a trailing slash: foobar/'
