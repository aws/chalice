from pytest import fixture
from attr import evolve

from chalice.deploy import models


@fixture
def lambda_function():
    return models.LambdaFunction(
        resource_name='foo',
        function_name='app-stage-foo',
        deployment_package=None,
        environment_variables={},
        runtime='python2.7',
        handler='app.app',
        tags={},
        timeout=None,
        memory_size=None,
        role=models.PreCreatedIAMRole(role_arn='foobar'),
        security_group_ids=[],
        subnet_ids=[],
        reserved_concurrency=None,
    )


def test_can_instantiate_empty_application():
    app = models.Application(stage='dev', resources=[])
    assert app.dependencies() == []


def test_can_instantiate_app_with_deps():
    role = models.PreCreatedIAMRole(role_arn='foo')
    app = models.Application(stage='dev', resources=[role])
    assert app.dependencies() == [role]


def test_can_default_to_no_auths_in_rest_api(lambda_function):
    rest_api = models.RestAPI(
        resource_name='rest_api',
        swagger_doc={'swagger': '2.0'},
        api_gateway_stage='api',
        lambda_function=lambda_function,
    )
    assert rest_api.dependencies() == [lambda_function]


def test_can_add_authorizers_to_dependencies(lambda_function):
    auth1 = evolve(lambda_function, resource_name='auth1')
    auth2 = evolve(lambda_function, resource_name='auth2')
    rest_api = models.RestAPI(
        resource_name='rest_api',
        swagger_doc={'swagger': '2.0'},
        api_gateway_stage='api',
        lambda_function=lambda_function,
        authorizers=[auth1, auth2],
    )
    assert rest_api.dependencies() == [lambda_function, auth1, auth2]
