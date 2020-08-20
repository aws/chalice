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
import mock
import requests
from urllib3.util.retry import Retry
from requests.adapters import HTTPAdapter

from chalice import app
from chalice.awsclient import TypedAWSClient
from chalice.deploy.models import LambdaFunction
from chalice.deploy.packager import LambdaDeploymentPackager
from chalice.deploy.packager import LayerDeploymentPackager
from chalice.docker import LambdaImageBuilder
from chalice.local import create_local_server, DockerPackager
from chalice.local import ContainerProxyResourceManager
from chalice.local import LambdaLayerDownloader
from chalice.config import Config
from chalice.utils import OSUtils, UI

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


def test_container_proxy_resource_manager_build(basic_app, config):
    class DummyLambda(LambdaFunction):
        def __init__(self, handler, function_name):
            self.handler = handler
            self.function_name = function_name
            self.resource_name = function_name

    ui = mock.Mock(spec=UI)
    osutils = mock.Mock(spec=OSUtils)
    packager = mock.Mock(spec=DockerPackager)
    image_builder = mock.Mock(spec=LambdaImageBuilder)
    packager.package_layers.return_value = {
        "a": "/path/a",
        "b": "/path/b"
    }
    with cd(basic_app):
        resource_manager = ContainerProxyResourceManager(
            config, ui, osutils, packager, image_builder)
        lambda_functions = [DummyLambda("1", "a"), DummyLambda("2", "b")]
        containers = resource_manager.build_resources(lambda_functions)

        packager.package_app.assert_called_with()
        packager.package_layers.assert_called_with(lambda_functions)
        image_builder.build.assert_called_with(config.lambda_python_version)
        assert len(containers) == 2
        assert 'a' in containers
        assert 'b' in containers


def test_container_proxy_resource_manager_cleanup_nothing_no_errors():
    config = Config(config_from_disk={"project_dir": "path"})
    osutils = mock.Mock(spec=OSUtils)
    resource_manager = ContainerProxyResourceManager(
        config, None, osutils, None, None
    )
    resource_manager.cleanup()


class TestLambdaLayerDownloader(object):
    @pytest.fixture
    def lambda_client(self):
        client = mock.Mock(spec=TypedAWSClient)
        client.get_layer_version.return_value = {
            "Content": {
                "Location": "uri"
            }
        }
        return client

    @pytest.fixture
    def osutils(self):
        osutils = mock.Mock(spec=OSUtils)
        osutils.joinpath = os.path.join
        osutils.file_exists.return_value = False
        return osutils

    @pytest.fixture
    def session(self):
        session = mock.Mock(spec=requests.Session)
        session.get.return_value.iter_content.return_value = []
        return session

    @pytest.fixture
    def layer_downloader(self, config, lambda_client, osutils, session):
        ui = mock.Mock(spec=UI)
        layer_downloader = LambdaLayerDownloader(config, ui, lambda_client,
                                                 osutils, session)
        return layer_downloader

    def test_layer_downloader_download_all(self, osutils, lambda_client,
                                           session, layer_downloader,
                                           basic_app, config):
        layer_arns = {"arn1", "arn2", "arn3"}
        with cd(basic_app):
            cache_dir = os.path.join(basic_app, "cache")
            os.mkdir(cache_dir)
            paths = layer_downloader.download_all(layer_arns, cache_dir)
            files = os.listdir(cache_dir)
            for file in files:
                assert file.startswith("layer-")
                python_version = config.lambda_python_version
                assert file.endswith("-" + python_version + ".zip")
                assert os.path.join(cache_dir, file) in paths
            assert len(files) == len(layer_arns)
        assert osutils.file_exists.call_count == len(layer_arns)
        assert lambda_client.get_layer_version.call_count == len(layer_arns)
        assert session.get.call_count == len(layer_arns)
        assert len(paths) == len(layer_arns)

    def test_layer_downloader_download_one(self, osutils, lambda_client,
                                           session, layer_downloader,
                                           basic_app, config):
        with cd(basic_app):
            cache_dir = os.path.join(basic_app, "cache")
            os.mkdir(cache_dir)
            path = layer_downloader.download("layer", cache_dir)
            files = os.listdir(cache_dir)
            assert len(files) == 1
            file = files[0]
            assert file.startswith("layer-")
            python_version = config.lambda_python_version
            assert file.endswith("-" + python_version + ".zip")
            assert os.path.join(cache_dir, file) == path
        osutils.file_exists.assert_called_once()
        lambda_client.get_layer_version.assert_called_once()
        session.get.assert_called_once()

    def test_layer_downloader_ignores_cached(self, osutils, lambda_client,
                                             session, layer_downloader,
                                             basic_app):
        osutils.file_exists.return_value = True
        with cd(basic_app):
            cache_dir = os.path.join(basic_app, "cache")
            os.mkdir(cache_dir)
            osutils.file_exists.return_value = True
            layer_downloader.download("hello", cache_dir)
            files = os.listdir(cache_dir)
            assert len(files) == 0
        osutils.file_exists.assert_called_once()
        lambda_client.get_layer_version.assert_not_called()
        session.get.assert_not_called()

    def test_layer_downloader_download_invalid_arn_raises_error(
            self, lambda_client, layer_downloader, basic_app):
        lambda_client.get_layer_version.return_value = {}
        with cd(basic_app):
            cache_dir = os.path.join(basic_app, "cache")
            os.mkdir(cache_dir)
            with pytest.raises(ValueError) as e:
                layer_downloader.download("hello", cache_dir)
            files = os.listdir(cache_dir)
            assert len(files) == 0
        assert "Invalid layer arn" in str(e.value)


class TestDockerPackager(object):
    @pytest.fixture
    def config(self, basic_app):
        config = Config(
            config_from_disk={
                'project_dir': basic_app,
                'layers': ['hello', 'world', 'layers']
            }
        )

        def dummy_scope(stage, function):
            return config
        config.scope = dummy_scope
        return config

    @pytest.fixture
    def autolayer_config(self, basic_app):
        config = Config(
            config_from_disk={
                'project_dir': basic_app,
                'layers': ['hello', 'world', 'layers'],
                'automatic_layer': True
            }
        )

        def dummy_scope(stage, function):
            return config
        config.scope = dummy_scope
        return config

    @pytest.fixture
    def layer_downloader(self):
        layer_downloader = mock.Mock(spec=LambdaLayerDownloader)
        layer_downloader.download_all.return_value = [
            'hello.zip', 'world.zip', 'layers.zip'
        ]
        return layer_downloader

    @pytest.fixture
    def app_packager(self):
        app_packager = mock.Mock(spec=LambdaDeploymentPackager)
        app_packager.create_deployment_package.return_value = "app.zip"
        return app_packager

    @pytest.fixture
    def layer_packager(self):
        layer_packager = mock.Mock(spec=LayerDeploymentPackager)
        layer_packager.create_deployment_package.return_value = "layer.zip"
        return layer_packager

    @pytest.fixture
    def docker_packager(self, config, osutils, app_packager,
                        layer_packager, layer_downloader):
        return DockerPackager(config, osutils, app_packager,
                              layer_packager, layer_downloader)

    @pytest.fixture
    def osutils(self):
        osutils = mock.Mock(spec=OSUtils)
        osutils.joinpath = os.path.join
        osutils.makedirs = os.makedirs
        osutils.directory_exists.return_value = False
        osutils.file_exists.return_value = False
        return osutils

    class DummyLambda(LambdaFunction):
        def __init__(self, handler, function_name):
            self.handler = handler
            self.function_name = function_name
            self.resource_name = function_name

    def test_package_app_not_existing(self, basic_app, osutils, config,
                                      app_packager, docker_packager):
        with cd(basic_app):
            cache_dir = os.path.join(basic_app, ".chalice", "deployments")
            path = docker_packager.package_app()
            files = os.listdir(cache_dir)
            assert "app" in files
            expected_path = os.path.join(cache_dir, "app")
            assert path == expected_path
            assert osutils.extract_zipfile.called_with("app", expected_path)
        python_version = config.lambda_python_version
        app_packager.create_deployment_package.assert_called_with(
            basic_app, python_version)

    def test_package_app_already_exists(self, basic_app, osutils, config,
                                        app_packager, docker_packager):
        osutils.directory_exists.return_value = True
        with cd(basic_app):
            cache_dir = os.path.join(basic_app, ".chalice", "deployments")
            os.makedirs(cache_dir)
            path = docker_packager.package_app()
            files = os.listdir(cache_dir)
            assert len(files) == 0
            expected_path = os.path.join(cache_dir, "app")
            assert path == expected_path
        osutils.extract_zipfile.assert_not_called()

    def test_package_layers_no_auto_layer(self, basic_app, osutils, config,
                                          layer_packager, docker_packager):
        osutils.directory_exists = os.path.isdir
        with cd(basic_app):
            prefix = os.path.join(basic_app, ".chalice",
                                  "deployments", "layers-")
            lambdas = [
                self.DummyLambda("1", "a"),
                self.DummyLambda("2", "b"),
                self.DummyLambda("3", "c"),
            ]
            path_map = docker_packager.package_layers(lambdas)
            assert len(path_map) == 3
            assert path_map["a"] == path_map["b"] == path_map["c"]
            assert path_map["a"].startswith(prefix)
            python_version = config.lambda_python_version
            assert path_map["a"].endswith("-" + python_version)
        layer_packager.create_deployment_package.assert_not_called()

    def test_package_layers_with_auto_layer(self, basic_app, osutils,
                                            autolayer_config, app_packager,
                                            layer_packager, layer_downloader):

        docker_packager = DockerPackager(autolayer_config, osutils,
                                         app_packager, layer_packager,
                                         layer_downloader)
        with cd(basic_app):
            docker_packager.package_layers([self.DummyLambda("1", "a")])
        python_version = autolayer_config.lambda_python_version
        layer_packager.create_deployment_package.assert_called_with(
            basic_app, python_version)

    def test_create_layer_directory_not_existing(self, basic_app, config,
                                                 docker_packager, osutils,
                                                 layer_downloader):
        with cd(basic_app):
            cache_dir = os.path.join(basic_app, ".chalice", "deployments")
            layer_arns = ["arn1", "arn2", "arn3"]
            path = docker_packager.create_layer_directory(layer_arns, "/path")
            files = os.listdir(cache_dir)
            assert len(files) == 1
            assert files[0].startswith("layers")
            python_version = config.lambda_python_version
            assert files[0].endswith("-" + python_version)
            expected_path = os.path.join(cache_dir, files[0])
            assert path == expected_path
            unzip_calls = [
                mock.call("/path", path),
                mock.call("hello.zip", path),
                mock.call("world.zip", path),
                mock.call("layers.zip", path)
            ]
            osutils.extract_zipfile.assert_has_calls(unzip_calls)
            assert osutils.extract_zipfile.call_count == 4
            layer_downloader.download_all.assert_called_with(layer_arns,
                                                             cache_dir)

    def test_create_layer_directory_already_exists(self, basic_app, config,
                                                   docker_packager, osutils,
                                                   layer_downloader):
        osutils.directory_exists.return_value = True
        with cd(basic_app):
            cache_dir = os.path.join(basic_app, ".chalice", "deployments")
            os.makedirs(cache_dir)
            layer_arns = ["arn1", "arn2", "arn3"]
            path = docker_packager.create_layer_directory(layer_arns, "/path")
            files = os.listdir(cache_dir)
            assert len(files) == 0
            expected_prefix = os.path.join(cache_dir, "layers-")
            assert path.startswith(expected_prefix)
            python_version = config.lambda_python_version
            assert path.endswith("-" + python_version)
        osutils.extract_zipfile.assert_not_called()

    def test_create_layer_directory_no_autolayer(self, basic_app, config,
                                                 docker_packager, osutils,
                                                 layer_downloader):
        with cd(basic_app):
            cache_dir = os.path.join(basic_app, ".chalice", "deployments")
            layer_arns = ["arn1", "arn2", "arn3"]
            path = docker_packager.create_layer_directory(layer_arns, "")
            files = os.listdir(cache_dir)
            assert len(files) == 1
            assert files[0].startswith("layers")
            python_version = config.lambda_python_version
            assert files[0].endswith("-" + python_version)
            expected_path = os.path.join(cache_dir, files[0])
            assert path == expected_path
            unzip_calls = [
                mock.call("hello.zip", path),
                mock.call("world.zip", path),
                mock.call("layers.zip", path)
            ]
            osutils.extract_zipfile.assert_has_calls(unzip_calls)
            assert osutils.extract_zipfile.call_count == 3
            layer_downloader.download_all.assert_called_with(layer_arns,
                                                             cache_dir)

    def test_create_layer_directory_different_output_on_autolayer_mismatch(
            self, basic_app, docker_packager, osutils):
        osutils.directory_exists = os.path.isdir
        with cd(basic_app):
            layer_arns = ["arn1", "arn2", "arn3"]
            path1 = docker_packager.create_layer_directory(layer_arns, "")
            path2 = docker_packager.create_layer_directory(layer_arns, "path")
            assert path1 != path2

    def test_create_layer_directory_does_not_raise_filename_too_long(
            self, basic_app, layer_downloader, docker_packager, osutils):
        with cd(basic_app):
            cache_dir = os.path.join(basic_app, ".chalice", "deployments")
            filename = "zip" * 25
            layer_arns = [filename, filename, filename, filename, filename]
            docker_packager.create_layer_directory(layer_arns, "/path")
            files = os.listdir(cache_dir)
            assert len(files) == 1
            assert files[0].startswith("layers-")

    def test_creates_cache_dir_if_nonexistent(
            self, osutils, docker_packager, basic_app):
        osutils.directory_exists.return_value = False
        with cd(basic_app):
            docker_packager.package_app()
            chalice_dir = os.path.join(basic_app, ".chalice")
            assert 'deployments' in os.listdir(chalice_dir)
