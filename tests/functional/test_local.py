import os
import socket
import contextlib
from threading import Thread
from threading import Event
import json
import subprocess
from contextlib import contextmanager

import pytest
import requests
from urllib3.util.retry import Retry
from requests.adapters import HTTPAdapter

from chalice import app
from chalice.local import LocalDevServer
from chalice.config import Config


ENV_APP_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), 'envapp',
)


@contextmanager
def cd(path):
    try:
        original_dir = os.getcwd()
        os.chdir(path)
        yield
    finally:
        os.chdir(original_dir)


class ThreadedLocalServer(Thread):
    def __init__(self, port, host='localhost'):
        super(ThreadedLocalServer, self).__init__()
        self._app_object = None
        self._config = None
        self._host = host
        self._port = port
        self._server = None
        self._server_ready = Event()

    def wait_for_server_ready(self):
        self._server_ready.wait()

    def configure(self, app_object, config):
        self._app_object = app_object
        self._config = config

    def run(self):
        self._server = LocalDevServer(
            self._app_object, self._config, self._host, self._port)
        self._server_ready.set()
        self._server.serve_forever()

    def make_call(self, method, path, port, timeout=0.5):
        self._server_ready.wait()
        return method('http://{host}:{port}{path}'.format(
            path=path, host=self._host, port=port), timeout=timeout)

    def shutdown(self):
        if self._server is not None:
            self._server.server.shutdown()


@pytest.fixture
def config():
    return Config()


@pytest.fixture()
def unused_tcp_port():
    with contextlib.closing(socket.socket()) as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


@pytest.fixture()
def local_server_factory(unused_tcp_port):
    threaded_server = ThreadedLocalServer(unused_tcp_port)

    def create_server(app_object, config):
        threaded_server.configure(app_object, config)
        threaded_server.start()
        return threaded_server, unused_tcp_port

    try:
        yield create_server
    finally:
        threaded_server.shutdown()


@pytest.fixture
def sample_app():
    demo = app.Chalice('demo-app')

    @demo.route('/', methods=['GET'])
    def index():
        return {'hello': 'world'}

    @demo.route('/test-cors', methods=['POST'], cors=True)
    def test_cors():
        return {'hello': 'world'}

    return demo


def test_can_accept_get_request(config, sample_app, local_server_factory):
    local_server, port = local_server_factory(sample_app, config)
    response = local_server.make_call(requests.get, '/', port)
    assert response.status_code == 200
    assert response.text == '{"hello": "world"}'


def test_can_accept_options_request(config, sample_app, local_server_factory):
    local_server, port = local_server_factory(sample_app, config)
    response = local_server.make_call(requests.options, '/test-cors', port)
    assert response.headers['Content-Length'] == '0'
    assert response.headers['Access-Control-Allow-Methods'] == 'POST,OPTIONS'
    assert response.text == ''


def test_can_accept_multiple_options_request(config, sample_app,
                                             local_server_factory):
    local_server, port = local_server_factory(sample_app, config)

    response = local_server.make_call(requests.options, '/test-cors', port)
    assert response.headers['Content-Length'] == '0'
    assert response.headers['Access-Control-Allow-Methods'] == 'POST,OPTIONS'
    assert response.text == ''

    response = local_server.make_call(requests.options, '/test-cors', port)
    assert response.headers['Content-Length'] == '0'
    assert response.headers['Access-Control-Allow-Methods'] == 'POST,OPTIONS'
    assert response.text == ''


def test_can_accept_multiple_connections(config, sample_app,
                                         local_server_factory):
    # When a GET request is made to Chalice from a browser, it will send the
    # connection keep-alive header in order to hold the connection open and
    # reuse it for subsequent requests. If the conncetion close header is sent
    # back by the server the connection will be closed, but the browser will
    # reopen a new connection just in order to have it ready when needed.
    # In this case, since it does not send any content we do not have the
    # opportunity to send a connection close header back in a response to
    # force it to close the socket.
    # This is an issue in Chalice since the single threaded local server will
    # now be blocked waiting for IO from the browser socket. If a request from
    # any other source is made it will be blocked until the browser sends
    # another request through, giving us a chance to read from another socket.
    local_server, port = local_server_factory(sample_app, config)
    local_server.wait_for_server_ready()
    # We create a socket here to emulate a browser's open connection and then
    # make a request. The request should succeed.
    socket.create_connection(('localhost', port), timeout=1)
    try:
        response = local_server.make_call(requests.get, '/', port)
    except requests.exceptions.ReadTimeout:
        assert False, (
            'Read timeout occured, the socket is blocking the next request '
            'from going though.'
        )
    assert response.status_code == 200
    assert response.text == '{"hello": "world"}'


def test_can_import_env_vars(unused_tcp_port):
    with cd(ENV_APP_DIR):
        p = subprocess.Popen(['chalice', 'local', '--port',
                              str(unused_tcp_port)],
                             stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE)
        _wait_for_server_ready(p)
        try:
            _assert_env_var_loaded(unused_tcp_port)
        finally:
            p.terminate()


def _wait_for_server_ready(process):
    if process.poll() is not None:
        raise AssertionError(
            'Local server immediately exited with rc: %s' % process.poll()
        )


def _assert_env_var_loaded(port_number):
    session = _get_requests_session_with_timeout()
    response = session.get('http://localhost:%s/' % port_number)
    response.raise_for_status()
    assert json.loads(response.content) == {'hello': 'bar'}


def _get_requests_session_with_timeout():
    session = requests.Session()
    retry = Retry(
        # How many connection-related errors to retry on.
        connect=5,
        # How many connection-related errors to retry on.
        # A backoff factor to apply between attempts after the second try.
        backoff_factor=2,
    )
    session.mount('http://', HTTPAdapter(max_retries=retry))
    return session
