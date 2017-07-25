import mock

from chalice import cli
from chalice.cli.factory import CLIFactory
from chalice.local import LocalDevServer


def test_run_local_server():
    env = {}
    factory = mock.Mock(spec=CLIFactory)
    factory.create_config_obj.return_value.environment_variables = {
        'foo': 'bar',
    }
    local_server = mock.Mock(spec=LocalDevServer)
    factory.create_local_server.return_value = local_server
    cli.run_local_server(factory, 8000, env)
    assert env['foo'] == 'bar'
    local_server.serve_forever.assert_called_with()
