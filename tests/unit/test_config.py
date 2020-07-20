import os
import sys
import pytest

from chalice import __version__ as chalice_version
from chalice.config import Config
from chalice.config import DeployedResources
from chalice import Chalice


class FixedDataConfig(Config):
    def __init__(self, files_to_content, app_name='app'):
        self.files_to_content = files_to_content
        self._app_name = app_name

    @property
    def app_name(self):
        return self._app_name

    @property
    def project_dir(self):
        return '.'

    def _load_json_file(self, filename):
        return self.files_to_content.get(filename)


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


def test_can_lazy_load_chalice_app():

    app = Chalice(app_name='foo')
    calls = []

    def call_recorder(*args, **kwargs):
        calls.append((args, kwargs))
        return app

    c = Config.create(chalice_app=call_recorder)
    # Accessing the property multiple times will only
    # invoke the call once.
    assert isinstance(c.chalice_app, Chalice)
    assert isinstance(c.chalice_app, Chalice)
    assert len(calls) == 1


def test_lazy_load_chalice_app_must_be_callable():
    c = Config.create(chalice_app='not a callable')
    with pytest.raises(TypeError):
        c.chalice_app


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
    }

    default_params = {
        'api_gateway_stage': 'default_params',
        'app_name': 'default_params',
        'project_dir': 'default_params',
    }

    c = Config(chalice_stage='dev',
               user_provided_params=user_provided_params,
               config_from_disk=config_from_disk,
               default_params=default_params)
    assert c.api_gateway_stage == 'user_provided_params'
    assert c.app_name == 'config_from_disk'
    assert c.project_dir == 'default_params'

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


def test_can_chain_function_values():
    disk_config = {
        'lambda_timeout': 10,
        'lambda_functions': {
            'api_handler': {
                'lambda_timeout': 15,
                }
            },
        'stages': {
            'dev': {
                'lambda_timeout': 20,
                'lambda_functions': {
                    'api_handler': {
                        'lambda_timeout': 30,
                        }
                    }
                }
            }
        }
    c = Config(chalice_stage='dev',
               config_from_disk=disk_config)
    assert c.lambda_timeout == 30


def test_can_set_stage_independent_function_values():
    disk_config = {
        'lambda_timeout': 10,
        'lambda_functions': {
            'api_handler': {
                'lambda_timeout': 15,
                }
            }
        }
    c = Config(chalice_stage='dev',
               config_from_disk=disk_config)
    assert c.lambda_timeout == 15


def test_stage_overrides_function_values():
    disk_config = {
        'lambda_timeout': 10,
        'lambda_functions': {
            'api_handler': {
                'lambda_timeout': 15,
                }
            },
        'stages': {
            'dev': {
                'lambda_timeout': 20,
                }
            }
        }
    c = Config(chalice_stage='dev',
               config_from_disk=disk_config)
    assert c.lambda_timeout == 20


def test_can_create_scope_obj_with_new_function():
    disk_config = {
        'lambda_timeout': 10,
        'stages': {
            'dev': {
                'manage_iam_role': True,
                'iam_role_arn': 'role-arn',
                'autogen_policy': True,
                'iam_policy_file': 'policy.json',
                'environment_variables': {'env': 'stage'},
                'lambda_timeout': 1,
                'lambda_memory_size': 1,
                'tags': {'tag': 'stage'},
                'lambda_functions': {
                    'api_handler': {
                        'lambda_timeout': 30,
                    },
                    'myauth': {
                        # We're purposefully using different
                        # values for everything in the stage
                        # level config to ensure we can pull
                        # from function scoped config properly.
                        'manage_iam_role': True,
                        'iam_role_arn': 'auth-role-arn',
                        'autogen_policy': True,
                        'iam_policy_file': 'function.json',
                        'environment_variables': {'env': 'function'},
                        'lambda_timeout': 2,
                        'lambda_memory_size': 2,
                        'tags': {'tag': 'function'},
                    }
                }
            }
        }
    }
    c = Config(chalice_stage='dev', config_from_disk=disk_config)
    new_config = c.scope(chalice_stage='dev',
                         function_name='myauth')
    assert new_config.manage_iam_role
    assert new_config.iam_role_arn == 'auth-role-arn'
    assert new_config.autogen_policy
    assert new_config.iam_policy_file == 'function.json'
    assert new_config.environment_variables == {'env': 'function'}
    assert new_config.lambda_timeout == 2
    assert new_config.lambda_memory_size == 2
    assert new_config.tags['tag'] == 'function'


@pytest.mark.parametrize('stage_name,function_name,expected', [
    ('dev', 'api_handler', 'dev-api-handler'),
    ('dev', 'myauth', 'dev-myauth'),
    ('beta', 'api_handler', 'beta-api-handler'),
    ('beta', 'myauth', 'beta-myauth'),
    ('prod', 'api_handler', 'prod-stage'),
    ('prod', 'myauth', 'prod-stage'),
    ('foostage', 'api_handler', 'global'),
    ('foostage', 'myauth', 'global'),
])
def test_can_create_scope_new_stage_and_function(stage_name, function_name,
                                                 expected):
    disk_config = {
        'environment_variables': {'from': 'global'},
        'stages': {
            'dev': {
                'environment_variables': {'from': 'dev-stage'},
                'lambda_functions': {
                    'api_handler': {
                        'environment_variables': {
                            'from': 'dev-api-handler',
                        }
                    },
                    'myauth': {
                        'environment_variables': {
                            'from': 'dev-myauth',
                        }
                    }
                }
            },
            'beta': {
                'environment_variables': {'from': 'beta-stage'},
                'lambda_functions': {
                    'api_handler': {
                        'environment_variables': {
                            'from': 'beta-api-handler',
                        }
                    },
                    'myauth': {
                        'environment_variables': {
                            'from': 'beta-myauth',
                        }
                    }
                }
            },
            'prod': {
                'environment_variables': {'from': 'prod-stage'},
            }
        }
    }
    c = Config(chalice_stage='dev', config_from_disk=disk_config)
    new_config = c.scope(chalice_stage=stage_name,
                         function_name=function_name)
    assert new_config.environment_variables == {'from': expected}


def test_new_scope_config_is_separate_copy():
    original = Config(chalice_stage='dev', function_name='foo')
    new_config = original.scope(chalice_stage='prod', function_name='bar')

    # The original should not have been mutated.
    assert original.chalice_stage == 'dev'
    assert original.function_name == 'foo'

    assert new_config.chalice_stage == 'prod'
    assert new_config.function_name == 'bar'


def test_environment_from_top_level():
    config_from_disk = {'environment_variables': {"foo": "bar"}}
    c = Config('dev', config_from_disk=config_from_disk)
    assert c.environment_variables == config_from_disk['environment_variables']


def test_environment_from_stage_level():
    config_from_disk = {
        'stages': {
            'prod': {
                'environment_variables': {"foo": "bar"}
            }
        }
    }
    c = Config('prod', config_from_disk=config_from_disk)
    assert c.environment_variables == (
        config_from_disk['stages']['prod']['environment_variables'])


def test_env_vars_chain_merge():
    config_from_disk = {
        'environment_variables': {
            'top_level': 'foo',
            'shared_stage_key': 'from-top',
            'shared_stage': 'from-top',
        },
        'stages': {
            'prod': {
                'environment_variables': {
                    'stage_var': 'bar',
                    'shared_stage_key': 'from-stage',
                    'shared_stage': 'from-stage',
                },
                'lambda_functions': {
                    'api_handler': {
                        'environment_variables': {
                            'function_key': 'from-function',
                            'shared_stage': 'from-function',
                        }
                    }
                }
            }
        }
    }
    c = Config('prod', config_from_disk=config_from_disk)
    resolved = c.environment_variables
    assert resolved == {
        'top_level': 'foo',
        'stage_var': 'bar',
        'shared_stage': 'from-function',
        'function_key': 'from-function',
        'shared_stage_key': 'from-stage',
    }


def test_can_load_python_version():
    c = Config('dev')
    major, minor = sys.version_info[0], sys.version_info[1]
    if major == 2:
        expected_runtime = 'python2.7'
    elif minor <= 6:
        expected_runtime = 'python3.6'
    elif minor <= 7:
        expected_runtime = 'python3.7'
    else:
        expected_runtime = 'python3.8'
    assert c.lambda_python_version == expected_runtime


class TestConfigureMinimumCompressionSize(object):
    def test_not_set(self):
        c = Config('dev', config_from_disk={})
        assert c.minimum_compression_size is None

    def test_set_minimum_compression_size_global(self):
        config_from_disk = {
            'minimum_compression_size': 5000
        }
        c = Config('dev', config_from_disk=config_from_disk)
        assert c.minimum_compression_size == 5000

    def test_set_minimum_compression_size_stage(self):
        config_from_disk = {
            'stages': {
                'dev': {
                    'minimum_compression_size': 5000
                }
            }
        }
        c = Config('dev', config_from_disk=config_from_disk)
        assert c.minimum_compression_size == 5000

    def test_set_minimum_compression_size_override(self):
        config_from_disk = {
            'minimum_compression_size': 0,
            'stages': {
                'dev': {
                    'minimum_compression_size': 5000
                }
            }
        }
        c = Config('dev', config_from_disk=config_from_disk)
        assert c.minimum_compression_size == 5000


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
                'sharedkey': 'globalvalue',
                'sharedstage': 'globalvalue',
            },
            'stages': {
                'dev': {
                    'tags': {
                        'sharedkey': 'stagevalue',
                        'sharedstage': 'stagevalue',
                        'onlystagekey': 'stagevalue',
                    },
                    'lambda_functions': {
                        'api_handler': {
                            'tags': {
                                'sharedkey': 'functionvalue',
                                'onlyfunctionkey': 'functionvalue',
                            }
                        }
                    }
                }
            }
        }
        c = Config('dev', config_from_disk=config_from_disk)
        assert c.tags == {
            'onlyglobalkey': 'globalvalue',
            'onlystagekey': 'stagevalue',
            'onlyfunctionkey': 'functionvalue',
            'sharedstage': 'stagevalue',
            'sharedkey': 'functionvalue',
            'aws-chalice': 'version=%s:stage=dev:app=myapp' % chalice_version
        }

    def test_tags_specified_does_not_override_chalice_tag(self):
        c = Config.create(
            chalice_stage='dev', app_name='myapp',
            tags={'aws-chalice': 'attempted-override'})
        assert c.tags == {
            'aws-chalice': 'version=%s:stage=dev:app=myapp' % chalice_version,
        }


def test_deployed_resource_does_not_exist():
    deployed = DeployedResources(
        {'resources': [{'name': 'foo'}]}
    )
    with pytest.raises(ValueError):
        deployed.resource_values('bar')


def test_deployed_api_mapping_resource():
    deployed = DeployedResources(
        {'resources': [
            {'name': 'foo'},
            {
                "name": "api_gateway_custom_domain",
                "resource_type": "domain_name",
                "api_mapping": [
                    {
                        "key": "path_key"
                    }
                ]
            }
        ]}
    )

    name = 'api_gateway_custom_domain.api_mapping.path_key'
    result = deployed.resource_values(name)
    assert result == {
        "name": "api_gateway_custom_domain",
        "resource_type": "domain_name",
        "api_mapping": [
            {
                "key": "path_key"
            }
        ]
    }


def test_deployed_resource_exists():
    deployed = DeployedResources(
        {'resources': [{'name': 'foo'}]}
    )
    assert deployed.resource_values('foo') == {'name': 'foo'}
    assert deployed.resource_names() == ['foo']


class TestUpgradeNewDeployer(object):
    def setup_method(self):
        # This is the "old deployer" format.
        deployed = {
            "region": "us-west-2",
            "api_handler_name": "app-dev",
            "api_handler_arn": (
                "arn:aws:lambda:us-west-2:123:function:app-dev"),
            "rest_api_id": "my_rest_api_id",
            "lambda_functions": {
                "app-dev-foo": {
                    "type": "pure_lambda",
                    "arn": (
                        "arn:aws:lambda:us-west-2:123:function:app-dev-foo"
                    )},
            },
            "chalice_version": "1.1.1",
            "api_gateway_stage": "api",
            "backend": "api",
        }
        self.old_deployed = {"dev": deployed}
        # This is "new deployer" format.  The deployed resources
        # are just a list of resources.
        resources = [
            {"role_name": "app-dev",
             "role_arn": "arn:aws:iam::123:role/app-dev",
             "name": "default-role",
             "resource_type": "iam_role"},
            {"lambda_arn": "arn:aws:lambda:us-west-2:123:function:app-dev-foo",
             "name": "foo",
             "resource_type": "lambda_function"},
            {"lambda_arn": (
                "arn:aws:lambda:us-west-2:123:function:app-dev"),
             "name": "api_handler",
             "resource_type": "lambda_function"},
            {"rest_api_id": "my_rest_api_id",
             "name": "rest_api",
             "resource_type": "rest_api"}
        ]
        self.new_deployed = {
            'stages': {
                'dev': {
                    'resources': resources
                }
            },
            'schema_version': '2.0',
        }
        self.deployed_filename = os.path.join('.', '.chalice', 'deployed.json')
        self.config = FixedDataConfig(
            {self.deployed_filename: self.old_deployed},
        )

    def test_can_upgrade_rest_api(self):
        resources = self.config.deployed_resources('dev')
        # The 'default-role' isn't in this list because
        # it's not in the old deployed.json so it's filled
        # in on the first deploy with the new deployer.
        assert sorted(resources.resource_names()) == [
             'api_handler', 'foo', 'rest_api',
        ]
        assert resources.resource_values('rest_api') == {
            'rest_api_id': 'my_rest_api_id',
            'name': 'rest_api',
            'resource_type': 'rest_api',
        }

    def test_upgrade_for_new_stage_gives_empty_values(self):
        resources = self.config.deployed_resources('prod')
        assert resources.resource_names() == []

    def test_can_upgrade_pre10_lambda_functions(self):
        deployed = {
            "region": "us-west-2",
            "api_handler_name": "app-dev",
            "api_handler_arn": (
                "arn:aws:lambda:us-west-2:123:function:app-dev"),
            "rest_api_id": "my_rest_api_id",
            "lambda_functions": {
                # This is the old < 1.0 style where the
                # value was just the lambda arn.
                "app-dev-foo": "my-lambda-arn",
            },
            "chalice_version": "0.10.0",
            "api_gateway_stage": "api",
            "backend": "api",
        }
        self.old_deployed = {"dev": deployed}
        self.config = FixedDataConfig(
            {self.deployed_filename: self.old_deployed},
        )
        resources = self.config.deployed_resources('dev')
        assert sorted(resources.resource_names()) == [
            'api_handler', 'foo', 'rest_api',
        ]
        assert resources.resource_values('foo') == {
            'lambda_arn': 'my-lambda-arn',
            'name': 'foo',
            'resource_type': 'lambda_function',
        }
