import enum
from typing import List, Dict, Optional, Any, TypeVar, Union, Set  # noqa
from typing import cast
from attr import attrs, attrib, Factory


class Placeholder(enum.Enum):
    BUILD_STAGE = 'build_stage'


class Instruction(object):
    pass


class RoleTraits(enum.Enum):
    VPC_NEEDED = 'vpc_needed'


Type = TypeVar('Type')
DV = Union[Placeholder, Type]
StrMap = Dict[str, str]


@attrs
class Plan(object):
    instructions = attrib(default=Factory(list))  # type: List[Instruction]
    messages = attrib(default=Factory(dict))      # type: Dict[int, str]


@attrs(frozen=True)
class APICall(Instruction):
    method_name = attrib()             # type: str
    params = attrib()                  # type: Dict[str, Any]
    output_var = attrib(default=None)  # type: Optional[str]


@attrs(frozen=True)
class StoreValue(Instruction):
    name = attrib()   # type: str
    value = attrib()  # type: Any


@attrs(frozen=True)
class CopyVariable(Instruction):
    from_var = attrib()  # type: str
    to_var = attrib()    # type: str


@attrs(frozen=True)
class RecordResource(Instruction):
    resource_type = attrib()  # type: str
    resource_name = attrib()  # type: str
    name = attrib()           # type: str


@attrs(frozen=True)
class RecordResourceVariable(RecordResource):
    variable_name = attrib()  # type: str


@attrs(frozen=True)
class RecordResourceValue(RecordResource):
    value = attrib()  # type: Any


@attrs(frozen=True)
class JPSearch(Instruction):
    expression = attrib()  # type: Any
    input_var = attrib()   # type: Any
    output_var = attrib()  # type: Any


@attrs(frozen=True)
class BuiltinFunction(Instruction):
    function_name = attrib()  # type: str
    args = attrib()           # type: List[Any]
    output_var = attrib()     # type: str


class Model(object):
    def dependencies(self):
        # type: () -> List[Model]
        return []


@attrs
class ManagedModel(Model):
    resource_name = attrib()  # type: str
    # Subclasses must fill in this attribute.
    resource_type = ''        # type: str


@attrs
class Application(Model):
    stage = attrib()      # type: str
    resources = attrib()  # type: List[Model]

    def dependencies(self):
        # type: () -> List[Model]
        return self.resources


@attrs
class DeploymentPackage(Model):
    filename = attrib()  # type: DV[str]


@attrs
class IAMPolicy(Model):
    document = attrib()  # type: DV[Dict[str, Any]]


@attrs
class FileBasedIAMPolicy(IAMPolicy):
    filename = attrib()  # type: str


@attrs
class AutoGenIAMPolicy(IAMPolicy):
    traits = attrib(default=Factory(set))  # type: Set[RoleTraits]


@attrs
class IAMRole(Model):
    pass


@attrs
class PreCreatedIAMRole(IAMRole):
    role_arn = attrib()  # type: str


@attrs
class ManagedIAMRole(IAMRole, ManagedModel):
    resource_type = 'iam_role'
    role_name = attrib()     # type: str
    trust_policy = attrib()  # type: Dict[str, Any]
    policy = attrib()        # type: IAMPolicy

    def dependencies(self):
        # type: () -> List[Model]
        return [self.policy]


@attrs
class LambdaFunction(ManagedModel):
    resource_type = 'lambda_function'
    function_name = attrib()          # type: str
    deployment_package = attrib()     # type: DeploymentPackage
    environment_variables = attrib()  # type: StrMap
    runtime = attrib()                # type: str
    handler = attrib()                # type: str
    tags = attrib()                   # type: StrMap
    timeout = attrib()                # type: int
    memory_size = attrib()            # type: int
    role = attrib()                   # type: IAMRole
    security_group_ids = attrib()     # type: List[str]
    subnet_ids = attrib()             # type: List[str]
    reserved_concurrency = attrib()   # type: int
    layers = attrib()                 # type: List[str]

    def dependencies(self):
        # type: () -> List[Model]
        return [self.role, self.deployment_package]


@attrs
class ScheduledEvent(ManagedModel):
    resource_type = 'scheduled_event'
    rule_name = attrib()            # type: str
    schedule_expression = attrib()  # type: str
    lambda_function = attrib()      # type: LambdaFunction

    def dependencies(self):
        # type: () -> List[Model]
        return [self.lambda_function]


@attrs
class RestAPI(ManagedModel):
    resource_type = 'rest_api'
    swagger_doc = attrib()                       # type: DV[Dict[str, Any]]
    api_gateway_stage = attrib()                 # type: str
    lambda_function = attrib()                   # type: LambdaFunction
    authorizers = attrib(default=Factory(list))  # type: List[LambdaFunction]

    def dependencies(self):
        # type: () -> List[Model]
        return cast(List[Model], [self.lambda_function] + self.authorizers)


@attrs
class S3BucketNotification(ManagedModel):
    resource_type = 's3_event'
    bucket = attrib()           # type: str
    events = attrib()           # type: List[str]
    prefix = attrib()           # type: Optional[str]
    suffix = attrib()           # type: Optional[str]
    lambda_function = attrib()  # type: LambdaFunction

    def dependencies(self):
        # type: () -> List[Model]
        return [self.lambda_function]


@attrs
class SNSLambdaSubscription(ManagedModel):
    resource_type = 'sns_event'
    topic = attrib()            # type: str
    lambda_function = attrib()  # type: LambdaFunction

    def dependencies(self):
        # type: () -> List[Model]
        return [self.lambda_function]


@attrs
class SQSEventSource(ManagedModel):
    resource_type = 'sqs_event'
    queue = attrib()            # type: str
    batch_size = attrib()       # type: int
    lambda_function = attrib()  # type: LambdaFunction

    def dependencies(self):
        # type: () -> List[Model]
        return [self.lambda_function]
