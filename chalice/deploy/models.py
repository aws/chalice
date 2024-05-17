# pylint: disable=line-too-long
from __future__ import annotations
from dataclasses import dataclass, field
import enum
from typing import List, Dict, Optional as Opt, Any, TypeVar, Union, Set  # noqa
from typing import cast


class Placeholder(enum.Enum):
    BUILD_STAGE = 'build_stage'


class Instruction(object):
    pass


class RoleTraits(enum.Enum):
    VPC_NEEDED = 'vpc_needed'


class APIType(enum.Enum):
    WEBSOCKET = 'WEBSOCKET'
    HTTP = 'HTTP'


class TLSVersion(enum.Enum):
    TLS_1_0 = 'TLS_1_0'
    TLS_1_1 = 'TLS_1_1'
    TLS_1_2 = 'TLS_1_2'

    @classmethod
    def create(cls, str_version: str) -> Opt[TLSVersion]:
        for version in cls:
            if version.value == str_version:
                return version
        return None


T = TypeVar('T')
DV = Union[Placeholder, T]
StrMap = Dict[str, str]


@dataclass
class Plan:
    instructions: List[Instruction] = field(default_factory=list)
    messages: Dict[int, str] = field(default_factory=dict)


@dataclass(frozen=True)
class APICall(Instruction):
    method_name: str
    params: Dict[str, Any]
    output_var: Opt[str] = None


@dataclass(frozen=True)
class StoreValue(Instruction):
    name: str
    value: Any


@dataclass(frozen=True)
class StoreMultipleValue(Instruction):
    name: str
    value: List[Any] = field(default_factory=list)


@dataclass(frozen=True)
class CopyVariable(Instruction):
    from_var: str
    to_var: str


@dataclass(frozen=True)
class CopyVariableFromDict(Instruction):
    from_var: str
    key: str
    to_var: str


@dataclass(frozen=True)
class RecordResource(Instruction):
    resource_type: str
    resource_name: str
    name: str


@dataclass(frozen=True)
class RecordResourceVariable(RecordResource):
    variable_name: str


@dataclass(frozen=True)
class RecordResourceValue(RecordResource):
    value: Any


@dataclass(frozen=True)
class JPSearch(Instruction):
    expression: Any
    input_var: Any
    output_var: Any


@dataclass(frozen=True)
class BuiltinFunction(Instruction):
    function_name: str
    args: List[Any]
    output_var: str


@dataclass
class Model(object):
    def dependencies(self) -> List[Model]:
        return []


@dataclass
class ManagedModel(Model):
    resource_name: str
    # Subclasses must fill in this attribute.
    resource_type = ''


@dataclass
class Application(Model):
    stage: str
    resources: List[Model]

    def dependencies(self) -> List[Model]:
        return self.resources


@dataclass
class DeploymentPackage(Model):
    filename: DV[str]


@dataclass
class IAMPolicy(Model):
    document: DV[Dict[str, Any]]


@dataclass
class FileBasedIAMPolicy(IAMPolicy):
    filename: str


@dataclass
class AutoGenIAMPolicy(IAMPolicy):
    traits: Set[RoleTraits] = field(default_factory=set)


@dataclass
class IAMRole(Model):
    pass


@dataclass
class PreCreatedIAMRole(IAMRole):
    role_arn: str


@dataclass
class ManagedIAMRole(IAMRole, ManagedModel):
    resource_type = 'iam_role'
    role_name: str
    trust_policy: Dict[str, Any]
    policy: IAMPolicy

    def dependencies(self) -> List[Model]:
        return [self.policy]


@dataclass
class LambdaLayer(ManagedModel):
    resource_type = 'lambda_layer'
    layer_name: str
    runtime: str
    deployment_package: DeploymentPackage
    is_empty: bool = False

    def dependencies(self) -> List[Model]:
        return [self.deployment_package]


@dataclass
class LambdaFunction(ManagedModel):
    resource_type = 'lambda_function'
    function_name: str
    deployment_package: DeploymentPackage
    environment_variables: StrMap
    xray: bool
    runtime: str
    handler: str
    tags: StrMap
    timeout: int
    memory_size: int
    role: IAMRole
    security_group_ids: List[str]
    subnet_ids: List[str]
    reserved_concurrency: int
    # These are customer created layers.
    layers: List[str]
    managed_layer: Opt[LambdaLayer] = None
    log_group: Opt[LogGroup] = None

    def dependencies(self) -> List[Model]:
        resources: List[Model] = []
        if self.managed_layer is not None:
            resources.append(self.managed_layer)
        if self.log_group is not None:
            resources.append(self.log_group)
        resources.extend([self.role, self.deployment_package])
        return resources


@dataclass
class FunctionEventSubscriber(ManagedModel):
    lambda_function: LambdaFunction

    def dependencies(self) -> List[Model]:
        return [self.lambda_function]


@dataclass
class CloudWatchEventBase(FunctionEventSubscriber):
    rule_name: str


@dataclass
class CloudWatchEvent(CloudWatchEventBase):
    resource_type = 'cloudwatch_event'
    event_pattern: str


@dataclass
class ScheduledEvent(CloudWatchEventBase):
    resource_type = 'scheduled_event'
    schedule_expression: str
    rule_description: Opt[str] = None


@dataclass
class LogGroup(ManagedModel):
    resource_type = 'log_group'
    log_group_name: str
    retention_in_days: int


@dataclass
class APIMapping(ManagedModel):
    resource_type = 'api_mapping'
    mount_path: str
    api_gateway_stage: str


@dataclass
class DomainName(ManagedModel):
    resource_type = 'domain_name'
    domain_name: str
    protocol: APIType
    api_mapping: APIMapping
    certificate_arn: str
    tags: Opt[Dict[str, Any]] = None
    tls_version: Opt[TLSVersion] = None

    def dependencies(self) -> List[Model]:
        return [self.api_mapping]


@dataclass
class RestAPI(ManagedModel):
    resource_type = 'rest_api'
    swagger_doc: DV[Dict[str, Any]]
    minimum_compression: str
    api_gateway_stage: str
    endpoint_type: str
    lambda_function: LambdaFunction
    xray: bool = False
    policy: Opt[IAMPolicy] = None
    authorizers: List[LambdaFunction] = field(default_factory=list)
    domain_name: Opt[DomainName] = None
    vpce_ids: Opt[List[str]] = None

    def dependencies(self) -> List[Model]:
        resources: List[Model] = []
        resources.extend([self.lambda_function] + self.authorizers)
        if self.domain_name is not None:
            resources.append(self.domain_name)
        return cast(List[Model], resources)


@dataclass
class WebsocketAPI(ManagedModel):
    resource_type = 'websocket_api'
    name: str
    api_gateway_stage: str
    routes: List[str]
    connect_function: Opt[LambdaFunction]
    message_function: Opt[LambdaFunction]
    disconnect_function: Opt[LambdaFunction]
    domain_name: Opt[DomainName] = None

    def dependencies(self) -> List[Model]:
        resources: List[Model] = []
        if self.domain_name is not None:
            resources.append(self.domain_name)
        if self.connect_function is not None:
            resources.append(self.connect_function)
        if self.message_function is not None:
            resources.append(self.message_function)
        if self.disconnect_function is not None:
            resources.append(self.disconnect_function)
        return resources


@dataclass
class S3BucketNotification(FunctionEventSubscriber):
    resource_type = 's3_event'
    bucket: str
    events: List[str]
    prefix: Opt[str]
    suffix: Opt[str]


@dataclass
class SNSLambdaSubscription(FunctionEventSubscriber):
    resource_type = 'sns_event'
    topic: str


@dataclass
class QueueARN(object):
    arn: str

    @property
    def queue_name(self) -> str:
        # Pylint 2.x validates this correctly, but for py27, we have to
        # use Pylint 1.x which doesn't support dataclass.
        return self.arn.rpartition(':')[2]  # pylint: disable=no-member


@dataclass
class SQSEventSource(FunctionEventSubscriber):
    resource_type = 'sqs_event'
    queue: Union[str, QueueARN]
    batch_size: int
    maximum_batching_window_in_seconds: int
    maximum_concurrency: Opt[int] = None


@dataclass
class KinesisEventSource(FunctionEventSubscriber):
    resource_type = 'kinesis_event'
    stream: str
    batch_size: int
    starting_position: str
    maximum_batching_window_in_seconds: int


@dataclass
class DynamoDBEventSource(FunctionEventSubscriber):
    resource_type = 'dynamodb_event'
    stream_arn: str
    batch_size: int
    starting_position: str
    maximum_batching_window_in_seconds: int
