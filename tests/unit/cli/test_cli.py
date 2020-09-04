import mock
import pytest
import re

from chalice import cli
from chalice.cli.factory import CLIFactory
from chalice.config import Config
from chalice.local import LocalDevServer, ProxyServerRunner


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
        cli.run_local_server(factory, 'localhost', 8000, local_stage_test)
    assert str(e.value) == 'Route cannot end with a trailing slash: foobar/'


def test_run_proxy_server_creates_necessary_resources():
    factory = mock.Mock(spec=CLIFactory)
    config = mock.Mock(spec=Config)
    server_runner = mock.Mock(spec=ProxyServerRunner)
    config.chalice_app.routes = {}
    factory.create_config_obj.return_value = config
    factory.create_container_proxy_resource_manager.return_value = 5
    factory.create_proxy_server_runner.return_value = server_runner
    cli.run_proxy_server(factory, 'localhost', 8000, 'local_test')
    factory.create_container_proxy_resource_manager.assert_called_once()
    factory.create_proxy_server_runner.assert_called_with(
        config, 'local_test', 'localhost', 8000, 5, use_container=True)
    server_runner.run.assert_called_once()


def test_get_system_info():
    system_info = cli.get_system_info()
    assert re.match(r'python\s*([\d.]+),?\s*(.*) (.*)', system_info)
