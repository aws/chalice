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

    c = Config('dev', user_provided_params, config_from_disk, default_params)
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
