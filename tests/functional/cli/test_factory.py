import os
import sys
import json
import logging

import pytest
from pytest import fixture

from chalice.cli import factory
from chalice.deploy.deployer import Deployer, DeploymentReporter
from chalice.config import Config
from chalice import local
from chalice.utils import UI


@fixture
def clifactory(tmpdir):
    appdir = tmpdir.mkdir('app')
    appdir.join('app.py').write(
        '# Test app\n'
        'import chalice\n'
        'app = chalice.Chalice(app_name="test")\n'
    )
    chalice_dir = appdir.mkdir('.chalice')
    chalice_dir.join('config.json').write('{}')
    return factory.CLIFactory(str(appdir))


def assert_has_no_request_body_filter(log_name):
    log = logging.getLogger(log_name)
    assert not any(
        isinstance(f, factory.LargeRequestBodyFilter) for f in log.filters)


def assert_request_body_filter_in_log(log_name):
    log = logging.getLogger(log_name)
    assert any(
        isinstance(f, factory.LargeRequestBodyFilter) for f in log.filters)


def test_can_create_botocore_session():
    session = factory.create_botocore_session()
    assert session.user_agent().startswith('aws-chalice/')
    assert session.get_default_client_config() is None


def test_can_create_botocore_session_debug():
    log_name = 'botocore.endpoint'
    assert_has_no_request_body_filter(log_name)

    factory.create_botocore_session(debug=True)

    assert_request_body_filter_in_log(log_name)
    assert logging.getLogger('').level == logging.DEBUG


def test_can_create_botocore_session_connection_timeout():
    session = factory.create_botocore_session(connection_timeout=100)
    assert vars(session.get_default_client_config())['connect_timeout'] == 100


def test_can_create_botocore_session_cli_factory(clifactory):
    clifactory.profile = 'myprofile'
    session = clifactory.create_botocore_session()
    assert session.profile == 'myprofile'


def test_can_create_deletion_deployer(clifactory):
    session = clifactory.create_botocore_session()
    deployer = clifactory.create_deletion_deployer(session, UI())
    assert isinstance(deployer, Deployer)


def test_can_create_config_obj(clifactory):
    obj = clifactory.create_config_obj()
    assert isinstance(obj, Config)


def test_can_create_config_obj_default_autogen_policy_true(clifactory):
    config = clifactory.create_config_obj()
    assert config.autogen_policy is True


def test_provided_autogen_policy_overrides_config_file(clifactory):
    config_file = os.path.join(
        clifactory.project_dir, '.chalice', 'config.json')
    with open(config_file, 'w') as f:
        f.write('{"autogen_policy": false}')
    config = clifactory.create_config_obj(autogen_policy=True)
    assert config.autogen_policy is True


def test_can_create_config_obj_with_override_autogen(clifactory):
    config = clifactory.create_config_obj(autogen_policy=False)
    assert config.autogen_policy is False


def test_config_file_override_autogen_policy(clifactory):
    config_file = os.path.join(
        clifactory.project_dir, '.chalice', 'config.json')
    with open(config_file, 'w') as f:
        f.write('{"autogen_policy": false}')
    config = clifactory.create_config_obj()
    assert config.autogen_policy is False


def test_can_create_config_obj_with_api_gateway_stage(clifactory):
    config = clifactory.create_config_obj(api_gateway_stage='custom-stage')
    assert config.api_gateway_stage == 'custom-stage'


def test_can_create_config_obj_with_default_api_gateway_stage(clifactory):
    config = clifactory.create_config_obj()
    assert config.api_gateway_stage == 'api'


def test_cant_load_config_obj_with_bad_project(clifactory):
    clifactory.project_dir = 'nowhere-asdfasdfasdfas'
    with pytest.raises(RuntimeError):
        clifactory.create_config_obj()


def test_error_raised_on_unknown_config_version(clifactory):
    filename = os.path.join(
        clifactory.project_dir, '.chalice', 'config.json')
    with open(filename, 'w') as f:
        f.write(json.dumps({"version": "100.0"}))

    with pytest.raises(factory.UnknownConfigFileVersion):
        clifactory.create_config_obj()


def test_filename_and_lineno_included_in_syntax_error(clifactory):
    filename = os.path.join(clifactory.project_dir, 'app.py')
    with open(filename, 'w') as f:
        f.write("this is a syntax error\n")
    # If this app has been previously imported in another app
    # we need to remove it from the cached modules to ensure
    # we get the syntax error on import.
    sys.modules.pop('app', None)
    with pytest.raises(RuntimeError) as excinfo:
        clifactory.load_chalice_app()
    message = str(excinfo.value)
    assert 'app.py' in message
    assert 'line 1' in message


def test_can_import_vendor_package(clifactory):
    # Tests that vendor packages can be imported during config loading.
    vendor_lib = os.path.join(clifactory.project_dir, 'vendor')
    vendedlib_dir = os.path.join(vendor_lib, 'vendedlib')
    os.makedirs(vendedlib_dir)
    open(os.path.join(vendedlib_dir, '__init__.py'), 'a').close()
    with open(os.path.join(vendedlib_dir, 'submodule.py'), 'a') as f:
        f.write('CONST = "foo bar"\n')
    app_py = os.path.join(clifactory.project_dir, 'app.py')
    with open(app_py, 'a') as f:
        f.write('from vendedlib import submodule\n')
        f.write('app.imported_value = submodule.CONST\n')
    app = clifactory.load_chalice_app()
    assert app.imported_value == 'foo bar'
    assert sys.path[-1] == vendor_lib


def test_error_raised_on_invalid_config_json(clifactory):
    filename = os.path.join(
        clifactory.project_dir, '.chalice', 'config.json')
    with open(filename, 'w') as f:
        f.write("INVALID_JSON")

    with pytest.raises(RuntimeError):
        clifactory.create_config_obj()


def test_can_create_local_server(clifactory):
    app = clifactory.load_chalice_app()
    config = clifactory.create_config_obj()
    server = clifactory.create_local_server(app, config, '0.0.0.0', 8000)
    assert isinstance(server, local.LocalDevServer)
    assert server.host == '0.0.0.0'
    assert server.port == 8000


def test_can_create_deployment_reporter(clifactory):
    ui = UI()
    reporter = clifactory.create_deployment_reporter(ui=ui)
    assert isinstance(reporter, DeploymentReporter)
