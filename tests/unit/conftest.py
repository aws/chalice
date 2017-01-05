from pytest import fixture


@fixture(autouse=True)
def ensure_no_local_config(no_local_config):
    pass
