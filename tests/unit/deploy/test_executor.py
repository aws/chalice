import mock
import pytest

from chalice.awsclient import TypedAWSClient
from chalice.deploy import models
from chalice.deploy.executor import Executor, UnresolvedValueError, \
    VariableResolver
from chalice.deploy.models import APICall, RecordResourceVariable, \
    RecordResourceValue, StoreValue, JPSearch, BuiltinFunction, Instruction, \
    CopyVariable, CopyVariableFromDict
from chalice.deploy.planner import Variable, StringFormat
from chalice.utils import UI


class TestExecutor(object):
    def setup_method(self):
        self.mock_client = mock.Mock(spec=TypedAWSClient)
        self.ui = mock.Mock(spec=UI)
        self.executor = Executor(self.mock_client, self.ui)

    def execute(self, instructions, messages=None):
        if messages is None:
            messages = {}
        self.executor.execute(models.Plan(instructions, messages))

    def test_can_invoke_api_call_with_no_output(self):
        params = {'name': 'foo', 'trust_policy': {'trust': 'policy'},
                  'policy': {'iam': 'policy'}}
        call = APICall('create_role', params)

        self.execute([call])

        self.mock_client.create_role.assert_called_with(**params)

    def test_can_store_api_result(self):
        params = {'name': 'foo', 'trust_policy': {'trust': 'policy'},
                  'policy': {'iam': 'policy'}}
        apicall = APICall('create_role', params, output_var='my_variable_name')
        self.mock_client.create_role.return_value = 'myrole:arn'

        self.execute([apicall])

        assert self.executor.variables['my_variable_name'] == 'myrole:arn'

    def test_can_reference_stored_results_in_api_calls(self):
        params = {
            'name': Variable('role_name'),
            'trust_policy': {'trust': 'policy'},
            'policy': {'iam': 'policy'}
        }
        call = APICall('create_role', params)
        self.mock_client.create_role.return_value = 'myrole:arn'

        self.executor.variables['role_name'] = 'myrole-name'
        self.execute([call])

        self.mock_client.create_role.assert_called_with(
            name='myrole-name',
            trust_policy={'trust': 'policy'},
            policy={'iam': 'policy'},
        )

    def test_can_return_created_resources(self):
        params = {}
        call = APICall('create_function', params,
                       output_var='myfunction_arn')
        self.mock_client.create_function.return_value = 'function:arn'
        record_instruction = RecordResourceVariable(
            resource_type='lambda_function',
            resource_name='myfunction',
            name='myfunction_arn',
            variable_name='myfunction_arn',
        )
        self.execute([call, record_instruction])
        assert self.executor.resource_values == [{
            'name': 'myfunction',
            'myfunction_arn': 'function:arn',
            'resource_type': 'lambda_function',
        }]

    def test_can_reference_varname(self):
        self.mock_client.create_function.return_value = 'function:arn'
        self.execute([
            APICall('create_function', {}, output_var='myvarname'),
            RecordResourceVariable(
                resource_type='lambda_function',
                resource_name='myfunction',
                name='myfunction_arn',
                variable_name='myvarname',
            ),
        ])
        assert self.executor.resource_values == [{
            'name': 'myfunction',
            'resource_type': 'lambda_function',
            'myfunction_arn': 'function:arn',
        }]

    def test_can_record_value_directly(self):
        self.execute([
            RecordResourceValue(
                resource_type='lambda_function',
                resource_name='myfunction',
                name='myfunction_arn',
                value='arn:foo',
            )
        ])
        assert self.executor.resource_values == [{
            'name': 'myfunction',
            'resource_type': 'lambda_function',
            'myfunction_arn': 'arn:foo',
        }]

    def test_can_aggregate_multiple_resource_values(self):
        self.execute([
            RecordResourceValue(
                resource_type='lambda_function',
                resource_name='myfunction',
                name='key1',
                value='value1',
            ),
            RecordResourceValue(
                resource_type='lambda_function',
                resource_name='myfunction',
                name='key2',
                value='value2',
            )
        ])
        assert self.executor.resource_values == [{
            'name': 'myfunction',
            'resource_type': 'lambda_function',
            'key1': 'value1',
            'key2': 'value2',
        }]

    def test_new_keys_override_old_keys(self):
        self.execute([
            RecordResourceValue(
                resource_type='lambda_function',
                resource_name='myfunction',
                name='key1',
                value='OLD',
            ),
            RecordResourceValue(
                resource_type='lambda_function',
                resource_name='myfunction',
                name='key1',
                value='NEW',
            )
        ])
        assert self.executor.resource_values == [{
            'name': 'myfunction',
            'resource_type': 'lambda_function',
            'key1': 'NEW',
        }]

    def test_validates_no_unresolved_deploy_vars(self):
        params = {'zip_contents': models.Placeholder.BUILD_STAGE}
        call = APICall('create_function', params)
        self.mock_client.create_function.return_value = 'function:arn'
        # We should raise an exception because a param has
        # a models.Placeholder.BUILD_STAGE value which should have
        # been handled in an earlier stage.
        with pytest.raises(UnresolvedValueError):
            self.execute([call])

    def test_can_jp_search(self):
        self.execute([
            StoreValue(name='searchval', value={'foo': {'bar': 'baz'}}),
            JPSearch('foo.bar', input_var='searchval', output_var='result'),
        ])
        assert self.executor.variables['result'] == 'baz'

    def test_can_copy_variable(self):
        self.execute([
            StoreValue(name='foo', value='bar'),
            CopyVariable(from_var='foo', to_var='baz'),
        ])
        assert self.executor.variables['baz'] == 'bar'

    def test_can_copy_variable_from_dict(self):
        self.execute([
            StoreValue(name='foo', value={'bar': 'baz'}),
            CopyVariableFromDict(from_var='foo', key='bar', to_var='buz'),
        ])
        assert self.executor.variables['buz'] == 'baz'

    def test_can_call_builtin_function(self):
        self.execute([
            StoreValue(
                name='my_arn',
                value='arn:aws:lambda:us-west-2:123:function:name'),
            BuiltinFunction(
                function_name='parse_arn',
                args=[Variable('my_arn')],
                output_var='result',
            )
        ])
        assert self.executor.variables['result'] == {
            'account_id': '123',
            'region': 'us-west-2',
            'service': 'lambda'
        }

    def test_errors_out_on_unknown_function(self):
        with pytest.raises(ValueError):
            self.execute([
                BuiltinFunction(
                    function_name='unknown_foo',
                    args=[],
                    output_var=None,
                )
            ])

    def test_can_print_ui_messages(self):
        params = {'name': 'foo', 'trust_policy': {'trust': 'policy'},
                  'policy': {'iam': 'policy'}}
        call = APICall('create_role', params)
        messages = {id(call): 'Creating role'}
        self.execute([call], messages)
        self.mock_client.create_role.assert_called_with(**params)
        self.ui.write.assert_called_with('Creating role')

    def test_error_out_on_unknown_instruction(self):

        class CustomInstruction(Instruction):
            pass

        with pytest.raises(RuntimeError):
            self.execute([CustomInstruction()])


class TestResolveVariables(object):

    def resolve_vars(self, params, variables):
        return VariableResolver().resolve_variables(
            params, variables
        )

    def test_resolve_top_level_vars(self):
        assert self.resolve_vars(
            {'foo': Variable('myvar')},
            {'myvar': 'value'}
        ) == {'foo': 'value'}

    def test_can_resolve_multiple_vars(self):
        assert self.resolve_vars(
            {'foo': Variable('myvar'),
             'bar': Variable('myvar')},
            {'myvar': 'value'}
        ) == {'foo': 'value', 'bar': 'value'}

    def test_unsolved_error_raises_error(self):
        with pytest.raises(UnresolvedValueError) as excinfo:
            self.resolve_vars({'foo': models.Placeholder.BUILD_STAGE}, {})
        raised_exception = excinfo.value
        assert raised_exception.key == 'foo'
        assert raised_exception.value == models.Placeholder.BUILD_STAGE

    def test_can_resolve_nested_variable_refs(self):
        assert self.resolve_vars(
            {'foo': {'bar': Variable('myvar')}},
            {'myvar': 'value'}
        ) == {'foo': {'bar': 'value'}}

    def test_can_resolve_vars_in_list(self):
        assert self.resolve_vars(
            {'foo': [0, 1, Variable('myvar')]},
            {'myvar': 2}
        ) == {'foo': [0, 1, 2]}

    def test_deeply_nested(self):
        nested = {
            'a': {
                'b': {
                    'c': {
                        'd': [{'e': {'f': Variable('foo')}}],
                    }
                }
            }
        }
        variables = {'foo': 'value'}
        assert self.resolve_vars(nested, variables) == {
            'a': {
                'b': {
                    'c': {
                        'd': [{'e': {'f': 'value'}}],
                    }
                }
            }
        }

    def test_can_handle_format_string(self):
        params = {'bar': StringFormat('value: {my_var}', ['my_var'])}
        variables = {'my_var': 'foo'}
        assert self.resolve_vars(params, variables) == {
            'bar': 'value: foo',
        }

    def test_can_handle_deeply_nested_format_string(self):
        nested = {
            'a': {
                'b': {
                    'c': {
                        'd': [{'e': {'f': StringFormat(
                            'foo: {myvar}', ['myvar'])}}],
                    }
                }
            }
        }
        variables = {'myvar': 'value'}
        assert self.resolve_vars(nested, variables) == {
            'a': {
                'b': {
                    'c': {
                        'd': [{'e': {'f': 'foo: value'}}],
                    }
                }
            }
        }
