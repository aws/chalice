from pytest import fixture

from chalice import app
from chalice.config import Config
from chalice.local import LocalDevServer


@fixture
def sample_app():
    demo = app.Chalice('demo-app')
    demo.debug = True

    @demo.route('/index', methods=['GET'])
    def index():
        return {'hello': 'world'}


def test_does_use_daemon_threads(sample_app):
    server = LocalDevServer(
        sample_app, Config(), '0.0.0.0', 8000
    )

    assert server.server.daemon_threads is True
