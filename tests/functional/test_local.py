import os
import socket
import time
import contextlib
from threading import Thread
from threading import Event
from threading import Lock
import json
import subprocess
from contextlib import contextmanager

import pytest
import requests
from urllib3.util.retry import Retry
from requests.adapters import HTTPAdapter

from chalice import app
from chalice.local import create_local_server
from chalice.config import Config
from chalice.utils import OSUtils


APPS_DIR = os.path.dirname(os.path.abspath(__file__))
ENV_APP_DIR = os.path.join(APPS_DIR, 'envapp')
BASIC_APP = os.path.join(APPS_DIR, 'basicapp')


NEW_APP_VERSION = """
from chalice import Chalice

app = Chalice(app_name='basicapp')


@app.route('/')
def index():
    return {'version': 'reloaded'}
"""


@contextmanager
def cd(path):
    try:
        original_dir = os.getcwd()
        os.chdir(path)
        yield
    finally:
        os.chdir(original_dir)


@pytest.fixture()
def basic_app(tmpdir):
    tmpdir = str(tmpdir.mkdir('basicapp'))
    OSUtils().copytree(BASIC_APP, tmpdir)
    return tmpdir


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
        self._server = create_local_server(
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
def http_session():
    session = requests.Session()
    retry = Retry(
        # How many connection-related errors to retry on.
        connect=10,
        # A backoff factor to apply between attempts after the second try.
        backoff_factor=2,
        method_whitelist=['GET', 'POST', 'PUT'],
    )
    session.mount('http://', HTTPAdapter(max_retries=retry))
    return HTTPFetcher(session)


class HTTPFetcher(object):
    def __init__(self, session):
        self.session = session

    def json_get(self, url):
        response = self.session.get(url)
        response.raise_for_status()
        return json.loads(response.content)


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

    thread_safety_check = []
    lock = Lock()

    @demo.route('/', methods=['GET'])
    def index():
        return {'hello': 'world'}

    @demo.route('/test-cors', methods=['POST'], cors=True)
    def test_cors():
        return {'hello': 'world'}

    @demo.route('/count', methods=['POST'])
    def record_counter():
        # An extra delay helps ensure we consistently fail if we're
        # not thread safe.
        time.sleep(0.001)
        count = int(demo.current_request.json_body['counter'])
        with lock:
            thread_safety_check.append(count)

    @demo.route('/count', methods=['GET'])
    def get_record_counter():
        return thread_safety_check[:]

    return demo


def test_has_thread_safe_current_request(config, sample_app,
                                         local_server_factory):
    local_server, port = local_server_factory(sample_app, config)
    local_server.wait_for_server_ready()

    num_requests = 25
    num_threads = 5

    # The idea here is that each requests.post() has a unique 'counter'
    # integer.  If the current request is thread safe we should see a number
    # for each 0 - (num_requests * num_threads).  If it's not thread safe
    # we'll see missing numbers and/or duplicates.
    def make_requests(counter_start):
        for i in range(counter_start * num_requests,
                       (counter_start + 1) * num_requests):
            # We're slowing the sending rate down a bit.  The threaded
            # http server is good, but not great.  You can still overwhelm
            # it pretty easily.
            time.sleep(0.001)
            requests.post(
                'http://localhost:%s/count' % port, json={'counter': i})

    threads = []
    for i in range(num_threads):
        threads.append(Thread(target=make_requests, args=(i,)))
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    response = requests.get('http://localhost:%s/count' % port)
    assert len(response.json()) == len(range(num_requests * num_threads))
    assert sorted(response.json()) == list(range(num_requests * num_threads))


def test_can_accept_get_request(config, sample_app, local_server_factory):
    local_server, port = local_server_factory(sample_app, config)
    response = local_server.make_call(requests.get, '/', port)
    assert response.status_code == 200
    assert response.text == '{"hello":"world"}'


def test_can_get_unicode_string_content_length(
        config, local_server_factory):
    demo = app.Chalice('app-name')

    @demo.route('/')
    def index_view():
        return u'\u2713'

    local_server, port = local_server_factory(demo, config)
    response = local_server.make_call(requests.get, '/', port)
    assert response.headers['Content-Length'] == '3'


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
            'Read timeout occurred, the socket is blocking the next request '
            'from going though.'
        )
    assert response.status_code == 200
    assert response.text == '{"hello":"world"}'


def test_can_import_env_vars(unused_tcp_port, http_session):
    with cd(ENV_APP_DIR):
        p = subprocess.Popen(['chalice', 'local', '--port',
                              str(unused_tcp_port)],
                             stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE)
        _wait_for_server_ready(p)
        try:
            _assert_env_var_loaded(unused_tcp_port, http_session)
        finally:
            p.terminate()


def _wait_for_server_ready(process):
    if process.poll() is not None:
        raise AssertionError(
            'Local server immediately exited with rc: %s' % process.poll()
        )


def _assert_env_var_loaded(port_number, http_session):
    response = http_session.json_get('http://localhost:%s/' % port_number)
    assert response == {'hello': 'bar'}


def test_can_reload_server(unused_tcp_port, basic_app, http_session):
    with cd(basic_app):
        p = subprocess.Popen(['chalice', 'local', '--port',
                              str(unused_tcp_port)],
                             stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE)
        _wait_for_server_ready(p)
        url = 'http://localhost:%s/' % unused_tcp_port
        try:
            assert http_session.json_get(url) == {'version': 'original'}
            # Updating the app should trigger a reload.
            with open(os.path.join(basic_app, 'app.py'), 'w') as f:
                f.write(NEW_APP_VERSION)
            time.sleep(2)
            assert http_session.json_get(url) == {'version': 'reloaded'}
        finally:
            p.terminate()
