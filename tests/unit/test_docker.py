import sys

import pytest
from mock import Mock, call
import docker
from docker.errors import NotFound, APIError, ImageNotFound

from chalice.docker import (
    Container,
    LambdaImageBuilder,
    LambdaContainer,
)
from chalice.utils import UI


@pytest.fixture
def mock_docker_container():
    mock_docker_container = Mock(spec=docker.models.containers.Container)
    output_iterator = [
        (b"stdout1", None),
        (None, b"stderr1"),
        (b"stdout2", b"stderr2"),
        (b"Lambda API listening on port 9001...", None),
        (None, None)]
    mock_docker_container.attach.return_value = output_iterator
    return mock_docker_container


@pytest.fixture
def mock_docker_client(mock_docker_container):
    mock_docker_client = Mock(spec=docker.client.DockerClient)
    mock_docker_client.containers.run.return_value = mock_docker_container
    return mock_docker_client


class TestContainer(object):
    @pytest.fixture
    def sample_container(self, mock_docker_client):
        return Container(
            ui=Mock(spec=UI),
            image="image",
            cmd=["cmd1", "cmd2"],
            working_dir="/dir/dir/dir",
            host_dir="/dir/dir",
            docker_client=mock_docker_client,
        )

    def test_run_container_with_required_values(self, mock_docker_client,
                                                mock_docker_container):
        image = "image"
        cmd = ["cmd1", "cmd2"]
        working_dir = "/dir/dir/dir"
        host_dir = "/dir/dir"
        expected_volumes = {
            host_dir: {
                "bind": working_dir,
                "mode": "ro,delegated"
            }
        }

        container = Container(
            Mock(spec=UI),
            image,
            cmd,
            working_dir,
            host_dir,
            docker_client=mock_docker_client,
        )

        container.run()

        mock_docker_client.containers.run.assert_called_with(
            image,
            command=cmd,
            working_dir=working_dir,
            volumes=expected_volumes,
            tty=False,
            use_config_proxy=True,
            detach=True
        )

    def test_run_container_with_all_values(self, mock_docker_client,
                                           mock_docker_container):
        image = "image"
        cmd = ["cmd1", "cmd2"]
        working_dir = "/dir/dir/dir"
        host_dir = "/dir/dir"
        memory_limit_mb = 6
        exposed_ports = {8000: 8000}
        env_vars = {"hello": "world"}

        expected_volumes = {
            host_dir: {
                "bind": working_dir,
                "mode": "ro,delegated"
            }
        }

        container = Container(
            Mock(spec=UI),
            image,
            cmd,
            working_dir,
            host_dir,
            memory_limit_mb=memory_limit_mb,
            exposed_ports=exposed_ports,
            env_vars=env_vars,
            docker_client=mock_docker_client,
        )

        container.run()

        mock_docker_client.containers.run.assert_called_with(
            image,
            command=cmd,
            working_dir=working_dir,
            volumes=expected_volumes,
            tty=False,
            use_config_proxy=True,
            mem_limit="{}m".format(memory_limit_mb),
            environment=env_vars,
            ports=exposed_ports,
            detach=True,
        )

    def test_delete_container(self, mock_docker_client, sample_container,
                              mock_docker_container):
        sample_container.run()
        mock_docker_container.remove.return_value = Mock(spec=None)

        sample_container.delete()

        mock_docker_container.remove.assert_called_with(force=True)
        assert not sample_container.is_created()

    def test_delete_container_not_found(self, mock_docker_client,
                                        sample_container,
                                        mock_docker_container):
        sample_container.run()
        mock_docker_container.remove.side_effect = NotFound("msg")

        sample_container.delete()

        assert not sample_container.is_created()

    def test_delete_container_in_progress(self, mock_docker_client,
                                          sample_container,
                                          mock_docker_container):
        sample_container.run()
        mock_docker_container.remove.side_effect = \
            APIError("removal of container is already in progress")

        sample_container.delete()

        assert not sample_container.is_created()

    def test_delete_container_raise_docker_errors(self, mock_docker_client,
                                                  sample_container,
                                                  mock_docker_container):
        sample_container.run()

        mock_docker_container.remove.side_effect = APIError("error")

        with pytest.raises(APIError):
            sample_container.delete()

        assert sample_container.is_created()

    def test_stream_logs_to_output(self, mock_docker_client, sample_container,
                                   mock_docker_container):
        sample_container.run()

        mock_stdout = Mock(spec=sys.stdout)
        mock_stderr = Mock(spec=sys.stderr)

        sample_container.stream_logs_to_output(stdout=mock_stdout,
                                               stderr=mock_stderr)

        mock_docker_container.attach.assert_called_with(stream=True,
                                                        logs=True,
                                                        demux=True)
        mock_stdout.write.assert_has_calls(
            [call("stdout1"), call("stdout2"),
             call("Lambda API listening on port 9001...")])
        mock_stderr.write.assert_has_calls([call("stderr1"), call("stderr2")])

    def test_stream_logs_to_output_no_streams(self,
                                              mock_docker_client,
                                              sample_container,
                                              mock_docker_container):
        sample_container.run()

        sample_container.stream_logs_to_output()

        mock_docker_container.attach.assert_not_called()

    def test_stream_logs_to_output_only_stdout(self, sample_container):
        sample_container.run()

        mock_stdout = Mock(spec=sys.stdout)

        sample_container.stream_logs_to_output(stdout=mock_stdout)

        mock_stdout.write.assert_has_calls(
            [call("stdout1"), call("stdout2"),
             call("Lambda API listening on port 9001...")])

    def test_stream_logs_to_output_only_stderr(self, sample_container):
        sample_container.run()

        mock_stderr = Mock(spec=sys.stderr)

        sample_container.stream_logs_to_output(stderr=mock_stderr)

        mock_stderr.write.assert_has_calls([call("stderr1"), call("stderr2")])

    def test_is_created(self, sample_container):
        assert sample_container.is_created() is False
        sample_container.run()
        assert sample_container.is_created() is True


class TestLambdaImageBuilder(object):
    @pytest.fixture
    def sample_image_builder(self, mock_docker_client):
        return LambdaImageBuilder(Mock(spec=UI()),
                                  "layer_downloader",
                                  docker_client=mock_docker_client)

    def test_build_have_base_image(self, mock_docker_client,
                                   sample_image_builder):
        expected_image_name = "lambci/lambda:python3.7"
        mock_docker_client.images.get.return_value = \
            Mock(spec=docker.models.images.Image)

        image_name = sample_image_builder.build("python3.7", [])

        mock_docker_client.images.get.assert_called_with(expected_image_name)
        assert image_name == expected_image_name
        mock_docker_client.images.pull.assert_not_called()

    def test_build_missing_base_image(self, mock_docker_client,
                                      sample_image_builder):
        expected_image_name = "lambci/lambda:python3.7"
        mock_docker_client.images.get.side_effect = ImageNotFound("msg")

        image_name = sample_image_builder.build("python3.7", [])

        mock_docker_client.images.pull\
            .assert_called_with("lambci/lambda", tag="python3.7")
        assert image_name == expected_image_name

    def test_build_unsupported_runtime(self, sample_image_builder):
        with pytest.raises(ValueError):
            sample_image_builder.build("dummy_runtime", [])


class TestLambda(object):
    @pytest.fixture
    def lambda_container(self, mock_docker_client):

        return LambdaContainer(
            ui=None,
            port=8000,
            handler='handler',
            code_dir='/dir/',
            image='image',
            docker_client=mock_docker_client,
        )

    def test_run_lambda_container(self, mock_docker_client,
                                  mock_docker_container):
        ui = Mock(spec=UI)
        port = 8001
        handler = "hello"
        code_dir = "/dir/dir/dir"
        image = "image_str"
        memory_limit_mb = 6
        stay_open = True
        env_vars = {
            "var1": 1,
            "var2": False,
            "var3": "hello",
        }

        expected_env_vars = {
            "DOCKER_LAMBDA_STAY_OPEN": stay_open,
            "var1": 1,
            "var2": False,
            "var3": "hello",
        }

        expected_volumes = {
            code_dir: {
                "bind": "/var/task",
                "mode": "ro,delegated",
            }
        }

        lambda_container = LambdaContainer(
            ui=ui,
            port=port,
            handler=handler,
            code_dir=code_dir,
            image=image,
            env_vars=env_vars,
            memory_limit_mb=memory_limit_mb,
            stay_open=stay_open,
            docker_client=mock_docker_client,
        )

        assert lambda_container.api_port == port

        lambda_container.run()

        mock_docker_client.containers.run.assert_called_with(
            image,
            command=[handler],
            working_dir="/var/task",
            volumes=expected_volumes,
            mem_limit="{}m".format(memory_limit_mb),
            environment=expected_env_vars,
            ports={9001: port},
            detach=True,
            tty=False,
            use_config_proxy=True,
        )

    def test_run_lambda_container_only_required(self, mock_docker_client,
                                                mock_docker_container):
        ui = Mock(spec=UI)
        port = 8001
        handler = "hello"
        code_dir = "/dir/dir/dir"
        image = "image_str"

        expected_env_vars = {
            "DOCKER_LAMBDA_STAY_OPEN": False,
        }

        expected_volumes = {
            code_dir: {
                "bind": "/var/task",
                "mode": "ro,delegated",
            }
        }

        lambda_container = LambdaContainer(
            ui=ui,
            port=port,
            handler=handler,
            code_dir=code_dir,
            image=image,
            docker_client=mock_docker_client,
        )

        assert lambda_container.api_port == port

        lambda_container.run()

        mock_docker_client.containers.run.assert_called_with(
            image,
            command=[handler],
            working_dir="/var/task",
            volumes=expected_volumes,
            mem_limit="{}m".format(128),
            environment=expected_env_vars,
            ports={9001: port},
            detach=True,
            tty=False,
            use_config_proxy=True,
        )

    def test_wait_for_initialize(self, lambda_container,
                                 mock_docker_container):
        mock_docker_container.attach.return_value = \
            b"Lambda API listening on port 9001"
        lambda_container.run()
        lambda_container.wait_for_initialize()
        mock_docker_container.attach.assert_called_with(stream=False,
                                                        logs=True,
                                                        stdout=True)

    def test_wait_for_initialize_not_running(self, lambda_container,
                                             mock_docker_container):
        lambda_container.wait_for_initialize()
        mock_docker_container.attach.assert_not_called()
