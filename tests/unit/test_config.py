from chalice.config import Config


def test_config_create_method():
    c = Config.create(app_name='foo')
    assert c.app_name == 'foo'
    # Otherwise attributes default to None meaning 'not set'.
    assert c.lambda_arn is None
    assert c.profile is None
    assert c.stage is None


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
        'stage': 'user_provided_params',
        'lambda_arn': 'user_provided_params',
    }

    config_from_disk = {
        'stage': 'config_from_disk',
        'lambda_arn': 'config_from_disk',
        'app_name': 'config_from_disk',
    }

    default_params = {
        'stage': 'default_params',
        'app_name': 'default_params',
        'project_dir': 'default_params',
    }

    c = Config(user_provided_params, config_from_disk, default_params)
    assert c.stage == 'user_provided_params'
    assert c.lambda_arn == 'user_provided_params'
    assert c.app_name == 'config_from_disk'
    assert c.project_dir == 'default_params'

    assert c.config_from_disk == config_from_disk


def test_user_params_is_optional():
    c = Config(config_from_disk={'stage': 'config_from_disk'},
               default_params={'stage': 'default_params'})
    assert c.stage == 'config_from_disk'
