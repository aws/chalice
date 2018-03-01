import enum
from attr import attrs, attrib


class Placeholder(enum.Enum):
    BUILD_STAGE = 'build_stage'
    DEPLOY_STAGE = 'deploy_stage'


class Instruction(object):
    pass


@attrs(frozen=True)
class APICall(Instruction):
    method_name = attrib()
    params = attrib()
    resource = attrib(default=None)


@attrs(frozen=True)
class StoreValue(Instruction):
    name = attrib()


@attrs(frozen=True)
class LoadValue(Instruction):
    varname = attrib()


@attrs(frozen=True)
class RecordResource(Instruction):
    resource_type = attrib()
    resource_name = attrib()
    name = attrib()


@attrs(frozen=True)
class RecordResourceVariable(RecordResource):
    variable_name = attrib()


@attrs(frozen=True)
class RecordResourceValue(RecordResource):
    value = attrib()


@attrs(frozen=True)
class Push(Instruction):
    value = attrib()


@attrs(frozen=True)
class Pop(Instruction):
    pass


@attrs(frozen=True)
class JPSearch(Instruction):
    expression = attrib()


@attrs(frozen=True)
class BuiltinFunction(Instruction):
    function_name = attrib()
    args = attrib()


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


@attrs
class ScheduledEvent(ManagedModel):
    resource_type = 'scheduled_event'
    rule_name = attrib()
    schedule_expression = attrib()
    lambda_function = attrib()

    def dependencies(self):
        return [self.lambda_function]


@attrs
class RestAPI(ManagedModel):
    resource_type = 'rest_api'
    swagger_doc = attrib()
    api_gateway_stage = attrib()
    lambda_function = attrib()

    def dependencies(self):
        return [self.lambda_function]
