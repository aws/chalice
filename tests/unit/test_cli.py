from chalice import cli


def test_get_env_variables():
    config = {'environment_variables': {'test': 'true'}}
    env_variables = cli.get_env_variables(config)
    assert env_variables == config['environment_variables']
