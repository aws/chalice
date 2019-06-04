import json

import pytest

from chalice.awsclient import TypedAWSClient
from chalice.invoke import LambdaInvoker
from chalice.invoke import LambdaInvokeHandler
from chalice.invoke import LambdaResponseFormatter
from chalice.invoke import UnhandledLambdaError


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


class TestLambdaInvokeHandler(object):
    def test_invoke_can_format_and_write_success_case(self, stubbed_session):
        arn = 'arn:aws:lambda:region:id:function:name-dev'
        stubbed_session.stub('lambda').invoke(
            FunctionName=arn,
            InvocationType='RequestResponse'
        ).returns({
            'StatusCode': 200,
            'ExecutedVersion': '$LATEST',
            'Payload': FakeStreamingBody(b'foobarbaz')
        })
        ui = FakeUI()
        stubbed_session.activate_stubs()
        client = TypedAWSClient(stubbed_session)
        invoker = LambdaInvoker(arn, client)
        formatter = LambdaResponseFormatter()
        invoke_handler = LambdaInvokeHandler(invoker, formatter, ui)
        invoke_handler.invoke()

        stubbed_session.verify_stubs()
        assert ['foobarbaz\n'] == ui.writes

    def test_invoke_can_format_and_write_error_case(self, stubbed_session):
        arn = 'arn:aws:lambda:region:id:function:name-dev'
        error = {
            "errorMessage": "Something bad happened",
            "errorType": "Error",
            "stackTrace": [
                ["/path/file.py", 123, "main", "foo(bar)"],
                ["/path/other_file.py", 456, "function", "bar = baz"]
            ]
        }
        serialized_error = json.dumps(error).encode('utf-8')
        stubbed_session.stub('lambda').invoke(
            FunctionName=arn,
            InvocationType='RequestResponse'
        ).returns({
            'StatusCode': 200,
            'FunctionError': 'Unhandled',
            'ExecutedVersion': '$LATEST',
            'Payload': FakeStreamingBody(serialized_error)
        })
        ui = FakeUI()
        stubbed_session.activate_stubs()
        client = TypedAWSClient(stubbed_session)
        invoker = LambdaInvoker(arn, client)
        formatter = LambdaResponseFormatter()
        invoke_handler = LambdaInvokeHandler(invoker, formatter, ui)
        with pytest.raises(UnhandledLambdaError):
            invoke_handler.invoke()

        stubbed_session.verify_stubs()
        assert [(
            'Traceback (most recent call last):\n'
            '  File "/path/file.py", line 123, in main\n'
            '    foo(bar)\n'
            '  File "/path/other_file.py", line 456, in function\n'
            '    bar = baz\n'
            'Error: Something bad happened\n'
        )] == ui.errors

    def test_invoke_can_format_and_write_small_error_case(self,
                                                          stubbed_session):
        # Some error response payloads do not have the errorType or
        # stackTrace key.
        arn = 'arn:aws:lambda:region:id:function:name-dev'
        error = {
            "errorMessage": "Something bad happened",
        }
        serialized_error = json.dumps(error).encode('utf-8')
        stubbed_session.stub('lambda').invoke(
            FunctionName=arn,
            InvocationType='RequestResponse'
        ).returns({
            'StatusCode': 200,
            'FunctionError': 'Unhandled',
            'ExecutedVersion': '$LATEST',
            'Payload': FakeStreamingBody(serialized_error)
        })
        ui = FakeUI()
        stubbed_session.activate_stubs()
        client = TypedAWSClient(stubbed_session)
        invoker = LambdaInvoker(arn, client)
        formatter = LambdaResponseFormatter()
        invoke_handler = LambdaInvokeHandler(invoker, formatter, ui)
        with pytest.raises(UnhandledLambdaError):
            invoke_handler.invoke()

        stubbed_session.verify_stubs()
        assert [(
            'Something bad happened\n'
        )] == ui.errors


class TestLambdaInvoker(object):
    def test_invoke_can_call_api_handler(self, stubbed_session):
        arn = 'arn:aws:lambda:region:id:function:name-dev'
        stubbed_session.stub('lambda').invoke(
            FunctionName=arn,
            InvocationType='RequestResponse'
        ).returns({})
        stubbed_session.activate_stubs()
        client = TypedAWSClient(stubbed_session)
        invoker = LambdaInvoker(arn, client)
        invoker.invoke()
        stubbed_session.verify_stubs()

    def test_invoke_does_forward_payload(self, stubbed_session):
        arn = 'arn:aws:lambda:region:id:function:name-dev'
        stubbed_session.stub('lambda').invoke(
            FunctionName=arn,
            InvocationType='RequestResponse',
            Payload=b'foobar',
        ).returns({})
        stubbed_session.activate_stubs()
        client = TypedAWSClient(stubbed_session)
        invoker = LambdaInvoker(arn, client)
        invoker.invoke(b'foobar')
        stubbed_session.verify_stubs()


class TestLambdaResponseFormatter(object):
    def test_formatter_can_format_success(self):
        formatter = LambdaResponseFormatter()
        formatted = formatter.format_response({
            'StatusCode': 200,
            'ExecutedVersion': '$LATEST',
            'Payload': FakeStreamingBody(b'foobarbaz')
        })
        assert 'foobarbaz\n' == formatted

    def test_formatter_can_format_list_stack_trace(self):
        error = {
            "errorMessage": "Something bad happened",
            "errorType": "Error",
            "stackTrace": [
                ["/path/file.py", 123, "main", "foo(bar)"],
                ["/path/more.py", 456, "func", "bar = baz"]
            ]
        }
        serialized_error = json.dumps(error).encode('utf-8')
        formatter = LambdaResponseFormatter()
        formatted = formatter.format_response({
            'StatusCode': 200,
            'FunctionError': 'Unhandled',
            'ExecutedVersion': '$LATEST',
            'Payload': FakeStreamingBody(serialized_error)
        })

        assert (
            'Traceback (most recent call last):\n'
            '  File "/path/file.py", line 123, in main\n'
            '    foo(bar)\n'
            '  File "/path/more.py", line 456, in func\n'
            '    bar = baz\n'
            'Error: Something bad happened\n'
        ) == formatted

    def test_formatter_can_format_string_stack_trace(self):
        error = {
            "errorMessage": "Something bad happened",
            "errorType": "Error",
            "stackTrace": [
                '  File "/path/file.py", line 123, in main\n    foo(bar)\n',
                '  File "/path/more.py", line 456, in func\n    bar = baz\n',
            ]
        }
        serialized_error = json.dumps(error).encode('utf-8')
        formatter = LambdaResponseFormatter()
        formatted = formatter.format_response({
            'StatusCode': 200,
            'FunctionError': 'Unhandled',
            'ExecutedVersion': '$LATEST',
            'Payload': FakeStreamingBody(serialized_error)
        })

        assert (
            'Traceback (most recent call last):\n'
            '  File "/path/file.py", line 123, in main\n'
            '    foo(bar)\n'
            '  File "/path/more.py", line 456, in func\n'
            '    bar = baz\n'
            'Error: Something bad happened\n'
        ) == formatted

    def test_formatter_can_format_simple_error(self):
        error = {
            "errorMessage": "Something bad happened",
        }
        serialized_error = json.dumps(error).encode('utf-8')
        formatter = LambdaResponseFormatter()
        formatted = formatter.format_response({
            'StatusCode': 200,
            'FunctionError': 'Unhandled',
            'ExecutedVersion': '$LATEST',
            'Payload': FakeStreamingBody(serialized_error)
        })

        assert 'Something bad happened\n' == formatted
