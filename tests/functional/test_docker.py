import time

import docker
import pytest
from mock import Mock

from chalice.docker import ContainerException, LambdaContainer


@pytest.fixture
def mock_docker_container():
    mock_docker_container = Mock(spec=docker.models.containers.Container)
    return mock_docker_container


@pytest.fixture
def mock_docker_client(mock_docker_container):
    mock_docker_client = Mock(spec=docker.client.DockerClient)
    mock_docker_client.containers.run.return_value = mock_docker_container
    return mock_docker_client


class TestLambdaContainer(object):
    @pytest.fixture
    def lambda_container(self, mock_docker_client):
        return LambdaContainer(
            ui=None,
            port=8000,
            handler='handler',
            code_dir='/dir/',
            layers_dir=None,
            image='image',
            startup_timeout=1.0,
            poll_interval=0.5,
            docker_client=mock_docker_client,
        )

    class AttachWrapper(object):
        def __init__(self, attach_output):
            self._times_called = 0
            self._output = attach_output

        def attach(self, **kwargs):
            output = self._output[self._times_called % len(self._output)]
            self._times_called = self._times_called + 1
            return output

    def test_wait_for_initialize_timeout(self, lambda_container,
                                         mock_docker_container):
        attach_wrapper = self.AttachWrapper([b'hello world'])
        mock_docker_container.attach = attach_wrapper.attach
        lambda_container.run()
        start_time = time.time()
        with pytest.raises(ContainerException):
            lambda_container.wait_for_initialize()
        end_time = time.time()
        assert end_time-start_time < 1.3 * 1.0

    def test_wait_for_initialize_success(self, lambda_container,
                                         mock_docker_container):
        attach_wrapper = self.AttachWrapper(
            [b'hello world', b'Lambda API listening on port 6'])
        mock_docker_container.attach = attach_wrapper.attach
        lambda_container.run()
        lambda_container.wait_for_initialize()
