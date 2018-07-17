import json

import pytest

from chalice.awsclient import TypedAWSClient
from chalice.config import DeployedResources
from chalice.invoke import LambdaInvoker
from chalice.invoke import LambdaResponseFormatter
from chalice.invoke import NoSuchFunctionError


class FakeUI(object):
    def __init__(self):
        self.writes = []
        self.errors = []

    def write(self, value):
        self.writes.append(value)

    def error(self, value):
        self.errors.append(value)


class FakeStreamingBody(object):
    def __init__(self, value):
        self._value = value

    def read(self):
        return self._value


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
    stubbed_session.stub('lambda').invoke(
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


def test_formatter_can_format_success():
    fake_ui = FakeUI()
    formatter = LambdaResponseFormatter(fake_ui)
    formatter.format_response({
        'StatusCode': 200,
        'ExecutedVersion': '$LATEST',
        'Payload': FakeStreamingBody(b'foobarbaz')
    })
    assert 'foobarbaz' in fake_ui.writes


def test_formatter_can_format_stack_trace():
    error = {
        "errorMessage": "Something bad happened",
        "errorType": "Error",
        "stackTrace": [
            ["/path/file.py", 123, "main", "foo(bar)"],
            ["/path/other_file.py", 456, "function", "bar = baz"]
        ]
    }
    serialized_error = json.dumps(error).encode('utf-8')
    fake_ui = FakeUI()
    formatter = LambdaResponseFormatter(fake_ui)
    formatter.format_response({
        'StatusCode': 200,
        'FunctionError': 'Unhandled',
        'ExecutedVersion': '$LATEST',
        'Payload': FakeStreamingBody(serialized_error)
    })

    assert '  File "/path/file.py", line 123, in main\n' in fake_ui.errors
    assert '    foo(bar)\n' in fake_ui.errors
    assert '  File "/path/other_file.py", line 456, in function\n' in \
        fake_ui.errors
    assert '    bar = baz\n' in fake_ui.errors
    assert 'Traceback (most recent call last):\n' in fake_ui.errors
    assert 'Error: Something bad happened\n' in fake_ui.errors
