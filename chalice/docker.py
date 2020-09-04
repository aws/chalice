"""Docker integration for local testing."""
from __future__ import absolute_import

import time
from enum import Enum
import logging

import docker
from docker.types import CancellableStream
from six import ensure_str
from typing import (
    Dict,
    List,
    Any,
    Optional,
    IO,
    cast
)

from chalice.utils import UI


LOGGER = logging.getLogger(__name__)


class ContainerException(Exception):
    pass


class Container(object):

    def __init__(
        self,
        ui,                     # type: UI
        image,                  # type: str
        cmd,                    # type: List[Optional[str]]
        working_dir,            # type: str
        host_dir,               # type: str
        memory_limit_mb=None,   # type: int
        exposed_ports=None,     # type: Dict[int, int]
        env_vars=None,          # type: Dict[str, Any]
        other_volumes=None,     # type: Dict[str, Dict[str, str]]
        docker_client=None      # type: docker.client
    ):
        # type: (...) -> None
        self._ui = ui
        self._image = image
        self._cmd = cmd
        self._working_dir = working_dir
        self._host_dir = host_dir
        self._memory_limit_mb = memory_limit_mb
        self._exposed_ports = exposed_ports
        self._env_vars = env_vars
        self._other_volumes = other_volumes

        self._docker_client = docker_client or docker.from_env()
        self._docker_container = None

    def run(self):
        # type: () -> None
        if self._docker_container is not None:
            return

        LOGGER.debug("Mounting %s as %s:ro,delegated inside runtime container",
                     self._host_dir, self._working_dir)

        kwargs = {
            "command": self._cmd,
            "working_dir": self._working_dir,
            "volumes": {
                self._host_dir: {
                    "bind": self._working_dir,
                    "mode": "ro,delegated",
                }
            },
            "tty": False,
            "use_config_proxy": True,
            "detach": True,
        }

        if self._env_vars is not None:
            kwargs["environment"] = self._env_vars

        if self._exposed_ports is not None:
            kwargs["ports"] = self._exposed_ports

        if self._memory_limit_mb is not None:
            kwargs["mem_limit"] = "{}m".format(self._memory_limit_mb)

        if self._other_volumes is not None:
            volumes = cast(Dict[str, Dict[str, str]], kwargs["volumes"])
            volumes.update(self._other_volumes)

        self._docker_container = self._docker_client.containers\
            .run(self._image, **kwargs)

    def delete(self):
        # type: () -> None
        if self._docker_container is None:
            return

        try:
            self._docker_container.remove(force=True)
        except docker.errors.NotFound:
            self._ui.write("Container {} does not exist, skipping deletion\n"
                           .format(self._docker_container.id))
        except docker.errors.APIError as ex:
            # Ignore exception thrown when removal is already in progress
            msg = str(ex)
            removal_in_progress = ("removal of container" in msg) and \
                                  ("is already in progress" in msg)
            if not removal_in_progress:
                raise ex

        self._docker_container = None

    def stream_logs_to_output(self, stdout=None, stderr=None):
        # type: (Optional[IO[str]], Optional[IO[str]]) -> None
        if stdout is None and stderr is None:
            return
        if self._docker_container is None:
            return

        logs_itr = self._docker_container\
            .attach(stream=True, logs=True, demux=True)
        self._write_container_output(logs_itr, stdout=stdout, stderr=stderr)

    def _write_container_output(self,
                                logs_iterator,    # type: CancellableStream
                                stdout=None,      # type: Optional[IO[str]]
                                stderr=None,      # type: Optional[IO[str]]
                                ):
        # type: (...) -> None
        for stdout_data, stderr_data in logs_iterator:
            if stdout_data and stdout:
                stdout.write(ensure_str(stdout_data))

            if stderr_data and stderr:
                stderr.write(ensure_str(stderr_data))

    def is_created(self):
        # type: () -> bool
        return self._docker_container is not None


class Runtime(Enum):
    python27 = "python2.7"
    python36 = "python3.6"
    python37 = "python3.7"
    python38 = "python3.8"
    provided = "provided"

    @classmethod
    def has_value(cls, value):
        # type: (str) -> bool
        return any(value == item.value for item in cls)


class LambdaImageBuilder(object):
    _DOCKER_LAMBDA_REPO_NAME = "lambci/lambda"

    def __init__(self, ui, docker_client=None):
        # type: (UI, docker.client) -> None
        self._ui = ui
        self._docker_client = docker_client or docker.from_env()

    def build(self, runtime):
        # type: (str) -> str
        if not Runtime.has_value(runtime):
            raise ValueError("Unsupported Lambda runtime {}".format(runtime))

        base_image_name = "{}:{}"\
            .format(self._DOCKER_LAMBDA_REPO_NAME, runtime)
        try:
            self._docker_client.images.get(base_image_name)
        except docker.errors.ImageNotFound:
            self._ui.write("Docker Image {} not found, pulling image...\n"
                           .format(base_image_name))
            self._ui.write("This may take a few minutes but will only be run" +
                           " during the initial setup.\n")
            self._docker_client.images.pull(self._DOCKER_LAMBDA_REPO_NAME,
                                            tag=runtime)
        return base_image_name


class LambdaContainer(Container):
    _WORKING_DIR = "/var/task"
    _LAYERS_DIR = "/opt"
    _ENV_VAR_STAY_OPEN = "DOCKER_LAMBDA_STAY_OPEN"
    _LAMBDA_API_PORT = 9001

    _DEFAULT_STARTUP_TIMEOUT = 3.0
    _DEFAULT_STARTUP_POLL_INTERVAL = 1.0

    def __init__(
            self,
            ui,                     # type: UI
            port,                   # type: int
            handler,                # type: Optional[str]
            code_dir,               # type: str
            layers_dir,             # type: Optional[str]
            image,                  # type: str
            env_vars=None,          # type: Optional[Dict[str, Any]]
            memory_limit_mb=128,    # type: int
            stay_open=False,        # type: bool
            startup_timeout=None,   # type: float
            poll_interval=None,     # type: float
            docker_client=None      # type: docker.client
    ):
        # type: (...) -> None
        if env_vars is None:
            env_vars = {}
        if startup_timeout is None:
            startup_timeout = self._DEFAULT_STARTUP_TIMEOUT
        if poll_interval is None:
            poll_interval = self._DEFAULT_STARTUP_POLL_INTERVAL

        self.api_port = port
        self._startup_timeout = startup_timeout
        self._poll_interval = poll_interval

        ports = {self._LAMBDA_API_PORT: port}
        env_vars.update({
            self._ENV_VAR_STAY_OPEN: stay_open,
        })
        layer_volume = {
            layers_dir: {
                "bind": self._LAYERS_DIR,
                "mode": "ro,delegated",
            }
        } if layers_dir is not None else None

        super(LambdaContainer, self).__init__(
            ui,
            image,
            [handler],
            self._WORKING_DIR,
            code_dir,
            memory_limit_mb=memory_limit_mb,
            exposed_ports=ports,
            env_vars=env_vars,
            other_volumes=layer_volume,
            docker_client=docker_client,
        )

    def wait_for_initialize(self):
        # type: () -> None
        if self._docker_container is None:
            return
        elapsed_time = 0
        initialized = False
        while not initialized and elapsed_time < self._startup_timeout:
            logs = self._docker_container.attach(stdout=True,
                                                 stream=False,
                                                 logs=True)
            if b'Lambda API listening on port' in logs:
                initialized = True
            else:
                time.sleep(self._poll_interval)
                elapsed_time = elapsed_time + self._poll_interval
        if not initialized:
            raise ContainerException(
                'Timeout: Lambda container failed to start API server.')
