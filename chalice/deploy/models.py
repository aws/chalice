import enum
from attr import attrs, attrib


class Placeholder(enum.Enum):
    BUILD_STAGE = 'build_stage'
    DEPLOY_STAGE = 'deploy_stage'


class Model(object):
    def dependencies(self):
        return []


@attrs
class ManagedModel(Model):
    resource_name = attrib()
    # Subclasses must fill in this attribute.
    resource_type = ''


@attrs
class Application(Model):
    stage = attrib()
    resources = attrib()

    def dependencies(self):
        return self.resources


@attrs
class DeploymentPackage(Model):
    filename = attrib()


@attrs
class IAMPolicy(Model):
    pass


@attrs
class FileBasedIAMPolicy(IAMPolicy):
    filename = attrib()


@attrs
class AutoGenIAMPolicy(IAMPolicy):
    document = attrib()


@attrs
class IAMRole(Model):
    pass


@attrs
class PreCreatedIAMRole(IAMRole):
    role_arn = attrib()


@attrs
class ManagedIAMRole(IAMRole, ManagedModel):
    resource_type = 'iam_role'
    role_arn = attrib()
    role_name = attrib()
    trust_policy = attrib()
    policy = attrib()

    def dependencies(self):
        return [self.policy]


@attrs
class LambdaFunction(ManagedModel):
    resource_type = 'lambda_function'
    function_name = attrib()
    deployment_package = attrib()
    environment_variables = attrib()
    runtime = attrib()
    handler = attrib()
    tags = attrib()
    timeout = attrib()
    memory_size = attrib()
    role = attrib()

    def dependencies(self):
        return [self.role, self.deployment_package]
