import sys

from chalice import __version__ as chalice_version
from chalice.config import Config, DeployedResources


def test_config_create_method():
    c = Config.create(app_name='foo')
    assert c.app_name == 'foo'
    # Otherwise attributes default to None meaning 'not set'.
    assert c.profile is None
    assert c.api_gateway_stage is None


def test_default_chalice_stage():
    c = Config()
    assert c.chalice_stage == 'dev'


def test_version_defaults_to_1_when_missing():
    c = Config()
    assert c.config_file_version == '1.0'


def test_default_value_of_manage_iam_role():
    c = Config.create()
    assert c.manage_iam_role


def test_default_value_of_ssm_parameters():
    c = Config()
    assert c.ssm_parameters == []


def test_manage_iam_role_explicitly_set():
    c = Config.create(manage_iam_role=False)
    assert not c.manage_iam_role
    c = Config.create(manage_iam_role=True)
    assert c.manage_iam_role


def test_can_chain_lookup():
    user_provided_params = {
        'api_gateway_stage': 'user_provided_params',
    }

    config_from_disk = {
        'api_gateway_stage': 'config_from_disk',
        'app_name': 'config_from_disk',
        'ssm_parameters': ['param_a', 'param_b']
    }

    default_params = {
        'api_gateway_stage': 'default_params',
        'app_name': 'default_params',
        'project_dir': 'default_params',
    }

    c = Config('dev', user_provided_params, config_from_disk, default_params)
    assert c.api_gateway_stage == 'user_provided_params'
    assert c.app_name == 'config_from_disk'
    assert c.project_dir == 'default_params'
    assert c.ssm_parameters == ['param_a', 'param_b']

    assert c.config_from_disk == config_from_disk


def test_user_params_is_optional():
    c = Config(config_from_disk={'api_gateway_stage': 'config_from_disk'},
               default_params={'api_gateway_stage': 'default_params'})
    assert c.api_gateway_stage == 'config_from_disk'


def test_can_chain_chalice_stage_values():
    disk_config = {
        'api_gateway_stage': 'dev',
        'stages': {
            'dev': {
            },
            'prod': {
                'api_gateway_stage': 'prod',
                'iam_role_arn': 'foobar',
                'manage_iam_role': False,
            }
        }
    }
    c = Config(chalice_stage='dev',
               config_from_disk=disk_config)
    assert c.api_gateway_stage == 'dev'
    assert c.manage_iam_role

    prod = Config(chalice_stage='prod',
                  config_from_disk=disk_config)
    assert prod.api_gateway_stage == 'prod'
    assert prod.iam_role_arn == 'foobar'
    assert not prod.manage_iam_role


def test_can_create_deployed_resource_from_dict():
    d = DeployedResources.from_dict({
        'backend': 'api',
        'api_handler_arn': 'arn',
        'api_handler_name': 'name',
        'rest_api_id': 'id',
        'api_gateway_stage': 'stage',
        'region': 'region',
        'chalice_version': '1.0.0',
    })
    assert d.backend == 'api'
    assert d.api_handler_arn == 'arn'
    assert d.api_handler_name == 'name'
    assert d.rest_api_id == 'id'
    assert d.api_gateway_stage == 'stage'
    assert d.region == 'region'
    assert d.chalice_version == '1.0.0'


def test_environment_from_top_level():
    config_from_disk = {'environment_variables': {"foo": "bar"}}
    c = Config('dev', config_from_disk=config_from_disk)
    assert c.environment_variables == config_from_disk['environment_variables']


def test_environment_from_stage_leve():
    config_from_disk = {
        'stages': {
            'prod': {
                'environment_variables': {"foo": "bar"}
            }
        }
    }
    c = Config('prod', config_from_disk=config_from_disk)
    assert c.environment_variables == \
            config_from_disk['stages']['prod']['environment_variables']


def test_env_vars_chain_merge():
    config_from_disk = {
        'environment_variables': {
            'top_level': 'foo',
            'shared_key': 'from-top',
        },
        'stages': {
            'prod': {
                'environment_variables': {
                    'stage_var': 'bar',
                    'shared_key': 'from-stage',
                }
            }
        }
    }
    c = Config('prod', config_from_disk=config_from_disk)
    resolved = c.environment_variables
    assert resolved == {
        'top_level': 'foo',
        'stage_var': 'bar',
        'shared_key': 'from-stage',
    }


def test_can_load_python_version():
    c = Config('dev')
    expected_runtime = {
        2: 'python2.7',
        3: 'python3.6',
    }[sys.version_info[0]]
    assert c.lambda_python_version == expected_runtime


class TestConfigureLambdaMemorySize(object):
    def test_not_set(self):
        c = Config('dev', config_from_disk={})
        assert c.lambda_memory_size is None

    def test_set_lambda_memory_size_global(self):
        config_from_disk = {
            'lambda_memory_size': 256
        }
        c = Config('dev', config_from_disk=config_from_disk)
        assert c.lambda_memory_size == 256

    def test_set_lambda_memory_size_stage(self):
        config_from_disk = {
            'stages': {
                'dev': {
                    'lambda_memory_size': 256
                }
            }
        }
        c = Config('dev', config_from_disk=config_from_disk)
        assert c.lambda_memory_size == 256

    def test_set_lambda_memory_size_override(self):
        config_from_disk = {
            'lambda_memory_size': 128,
            'stages': {
                'dev': {
                    'lambda_memory_size': 256
                }
            }
        }
        c = Config('dev', config_from_disk=config_from_disk)
        assert c.lambda_memory_size == 256


class TestConfigureLambdaTimeout(object):
    def test_not_set(self):
        c = Config('dev', config_from_disk={})
        assert c.lambda_timeout is None

    def test_set_lambda_timeout_global(self):
        config_from_disk = {
            'lambda_timeout': 120
        }
        c = Config('dev', config_from_disk=config_from_disk)
        assert c.lambda_timeout == 120

    def test_set_lambda_memory_size_stage(self):
        config_from_disk = {
            'stages': {
                'dev': {
                    'lambda_timeout': 120
                }
            }
        }
        c = Config('dev', config_from_disk=config_from_disk)
        assert c.lambda_timeout == 120

    def test_set_lambda_memory_size_override(self):
        config_from_disk = {
            'lambda_timeout': 60,
            'stages': {
                'dev': {
                    'lambda_timeout': 120
                }
            }
        }
        c = Config('dev', config_from_disk=config_from_disk)
        assert c.lambda_timeout == 120


class TestConfigureTags(object):
    def test_default_tags(self):
        c = Config('dev', config_from_disk={'app_name': 'myapp'})
        assert c.tags == {
            'aws-chalice': 'version=%s:stage=dev:app=myapp' % chalice_version
        }

    def test_tags_global(self):
        config_from_disk = {
            'app_name': 'myapp',
            'tags': {'mykey': 'myvalue'}
        }
        c = Config('dev', config_from_disk=config_from_disk)
        assert c.tags == {
            'mykey': 'myvalue',
            'aws-chalice': 'version=%s:stage=dev:app=myapp' % chalice_version
        }

    def test_tags_stage(self):
        config_from_disk = {
            'app_name': 'myapp',
            'stages': {
                'dev': {
                    'tags': {'mykey': 'myvalue'}
                }
            }
        }
        c = Config('dev', config_from_disk=config_from_disk)
        assert c.tags == {
            'mykey': 'myvalue',
            'aws-chalice': 'version=%s:stage=dev:app=myapp' % chalice_version
        }

    def test_tags_merge(self):
        config_from_disk = {
            'app_name': 'myapp',
            'tags': {
                'onlyglobalkey': 'globalvalue',
                'sharedkey': 'globalvalue'
            },
            'stages': {
                'dev': {
                    'tags': {
                        'sharedkey': 'stagevalue',
                        'onlystagekey': 'stagevalue'
                    }
                }
            }
        }
        c = Config('dev', config_from_disk=config_from_disk)
        assert c.tags == {
            'onlyglobalkey': 'globalvalue',
            'sharedkey': 'stagevalue',
            'onlystagekey': 'stagevalue',
            'aws-chalice': 'version=%s:stage=dev:app=myapp' % chalice_version
        }

    def test_tags_specified_does_not_override_chalice_tag(self):
        c = Config.create(
            chalice_stage='dev', app_name='myapp',
            tags={'aws-chalice': 'attempted-override'})
        assert c.tags == {
            'aws-chalice': 'version=%s:stage=dev:app=myapp' % chalice_version,
        }
