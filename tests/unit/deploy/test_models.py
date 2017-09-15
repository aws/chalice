from chalice.deploy import models


def test_can_instantiate_empty_application():
    app = models.Application(stage='dev', resources=[])
    assert app.dependencies() == []


def test_can_instantiate_app_with_deps():
    role = models.PreCreatedIAMRole(role_arn='foo')
    app = models.Application(stage='dev', resources=[role])
    assert app.dependencies() == [role]
