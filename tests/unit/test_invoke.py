import json
import base64

import pytest

from chalice.awsclient import TypedAWSClient
from chalice.config import DeployedResources
from chalice.invoke import LambdaInvoker
from chalice.invoke import NoSuchFunctionError


@pytest.fixture
def no_deployed_values():
    return DeployedResources({'resources': [], 'schema_version': '2.0'})


def test_invoke_does_raise_error_on_bad_resource_name(no_deployed_values,
                                                      stubbed_session):
    stubbed_session.activate_stubs()
    client = TypedAWSClient(stubbed_session)
    invoker = LambdaInvoker(no_deployed_values, client)
    with pytest.raises(NoSuchFunctionError) as e:
        invoker.invoke('name')
    assert e.value.name == 'name'


def test_invoke_can_call_api_handler(stubbed_session):
    arn = 'arn:aws:lambda:region:id:function:name-dev'
    stubbed_session.stub('lambda').invoke(
        FunctionName=arn,
        InvocationType='RequestResponse'
    ).returns({})
    stubbed_session.activate_stubs()
    client = TypedAWSClient(stubbed_session)
    deployed_values = DeployedResources({
        "resources": [
            {
                "name": "name",
                "resource_type": "lambda_function",
                "lambda_arn": arn
            },
        ],
    })
    invoker = LambdaInvoker(deployed_values, client)
    invoker.invoke('name')
    stubbed_session.verify_stubs()


def test_invoke_does_raise_error_on_bad_resource_type(stubbed_session):
    stubbed_session.activate_stubs()
    client = TypedAWSClient(stubbed_session)
    deployed_values = DeployedResources({
        "resources": [
            {
                "name": "rest_api",
                "resource_type": "rest_api",
                "rest_api_id": "foobar",
                "rest_api_url": "https://foobar/api",
            },
        ],
    })
    invoker = LambdaInvoker(deployed_values, client)
    with pytest.raises(NoSuchFunctionError) as e:
        invoker.invoke('name')
    assert e.value.name == 'name'


def test_invoke_does_forward_payload(stubbed_session):
    arn = 'arn:aws:lambda:region:id:function:name-dev'
    stub_client = stubbed_session.stub('lambda').invoke(
        FunctionName=arn,
        InvocationType='RequestResponse',
        Payload=b'foobar',
    ).returns({})
    stubbed_session.activate_stubs()
    client = TypedAWSClient(stubbed_session)
    deployed_values = DeployedResources({
        "resources": [
            {
                "name": "name",
                "resource_type": "lambda_function",
                "lambda_arn": arn
            },
        ],
    })
    invoker = LambdaInvoker(deployed_values, client)
    invoker.invoke('name', payload=b'foobar')
    stubbed_session.verify_stubs()


def test_invoke_does_forward_context(stubbed_session):
    arn = 'arn:aws:lambda:region:id:function:name-dev'
    orig_context = '{"key": "value"}'
    custom = json.dumps({'custom': json.loads(orig_context)})
    context = base64.b64encode(custom.encode('utf-8')).decode('utf-8')

    stubbed_session.stub('lambda').invoke(
        FunctionName=arn,
        InvocationType='RequestResponse',
        ClientContext=context,
    ).returns({})
    stubbed_session.activate_stubs()
    client = TypedAWSClient(stubbed_session)
    deployed_values = DeployedResources({
        "resources": [
            {
                "name": "name",
                "resource_type": "lambda_function",
                "lambda_arn": arn
            },
        ],
    })
    invoker = LambdaInvoker(deployed_values, client)
    invoker.invoke('name', context=orig_context)
    stubbed_session.verify_stubs()
