import re
import mock
import pytest

from chalice.awsclient import TypedAWSClient
from chalice.deploy import models
from chalice.deploy.executor import Executor, UnresolvedValueError, \
    VariableResolver, DisplayOnlyExecutor
from chalice.deploy.models import APICall, RecordResourceVariable, \
    RecordResourceValue, StoreValue, JPSearch, BuiltinFunction, Instruction, \
    CopyVariable
from chalice.deploy.planner import Variable, StringFormat, KeyDataVariable
from chalice.utils import UI


class TestExecutor(object):
    def setup_method(self):
        self.mock_client = mock.Mock(spec=TypedAWSClient)
        self.mock_client.endpoint_dns_suffix.return_value = 'amazonaws.com'
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

    def test_can_store_multiple_value(self):
        instruction = models.StoreMultipleValue(
            name='list_data',
            value=['first_elem']
        )

        self.execute([instruction])
        assert self.executor.variables['list_data'] == ['first_elem']

        instruction = models.StoreMultipleValue(
            name='list_data',
            value=['second_elem']
        )

        self.execute([instruction])
        assert self.executor.variables['list_data'] == [
            'first_elem', 'second_elem'
        ]

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
            'partition': 'aws',
            'account_id': '123',
            'region': 'us-west-2',
            'service': 'lambda',
            'dns_suffix': 'amazonaws.com'
        }

    def test_built_in_function_interrogate_profile(self):
        self.mock_client.region_name = 'us-west-2'
        self.mock_client.partition_name = 'aws'
        self.execute([
            BuiltinFunction(
                function_name='interrogate_profile',
                args=[],
                output_var='result',
            )
        ])
        assert self.executor.variables['result'] == {
            'partition': 'aws',
            'region': 'us-west-2',
            'dns_suffix': 'amazonaws.com'
        }

    def test_built_in_function_service_principal(self):
        self.mock_client.region_name = 'us-west-2'
        self.mock_client.partition_name = 'aws'
        self.mock_client.service_principal.return_value = \
            'apigateway.amazonaws.com'
        self.execute([
            BuiltinFunction(
                function_name='service_principal',
                args=['apigateway'],
                output_var='result',
            )
        ])

        self.mock_client.service_principal \
            .assert_called_once_with('apigateway',
                                     'us-west-2',
                                     'amazonaws.com')
        assert self.executor.variables['result'] == {
            'principal': 'apigateway.amazonaws.com'
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


class TestDisplayOnlyExecutor(object):

    # Note: This executor doesn't have any guarantees on its output,
    # it's primarily to help debug/understand chalice.  The tests here
    # check the basic structure of the output, but try to not be overly strict.

    def setup_method(self):
        self.mock_client = mock.Mock(spec=TypedAWSClient)
        self.ui = mock.Mock(spec=UI)
        self.executor = DisplayOnlyExecutor(self.mock_client, self.ui)

    def execute(self, instructions, messages=None):
        if messages is None:
            messages = {}
        self.executor.execute(models.Plan(instructions, messages))

    def get_plan_output(self, instructions):
        self.executor.execute(models.Plan(instructions, {}))
        return ''.join(args[0][0] for args in self.ui.write.call_args_list)

    def test_can_display_plan(self):
        params = {'name': 'foo', 'trust_policy': {'trust': 'policy'},
                  'policy': {'iam': 'policy'}}
        call = APICall('create_role', params)

        plan_output = self.get_plan_output([call])
        # Should have a plan title.
        assert plan_output.startswith('Plan\n====')
        # Should print the api call in upper camel case.
        assert 'API_CALL' in plan_output
        # Should print the name of the method in the plan.
        assert 'method_name: create_role' in plan_output
        # Should print out the api call arguments in output.
        assert 'name: foo' in plan_output
        # The values for these are in the tests for the variable pool.
        assert 'trust_policy: ' in plan_output
        assert 'policy: ' in plan_output

    def test_variable_pool_printed_if_needed(self):
        params = {'name': 'foo', 'policy': {'iam': 'policy'}}
        call = APICall('create_role', params)

        plan_output = self.get_plan_output([call])
        # Dictionaries for param values are printed at the end so they
        # don't clutter the plan output.  We should see a placeholder here.
        assert 'policy: ${POLICY_0}' in plan_output
        assert 'Variable Pool' in plan_output
        assert "${POLICY_0}:\n{'iam': 'policy'}" in plan_output

    def test_variable_pool_omitted_if_empty(self):
        params = {'name': 'foo'}
        call = APICall('create_role', params)

        plan_output = self.get_plan_output([call])
        assert 'Variable Pool' not in plan_output

    def test_byte_value_replaced_if_over_length(self):
        params = {'name': 'foo', 'zip_contents': b'\x01' * 50}
        call = APICall('create_role', params)

        plan_output = self.get_plan_output([call])
        assert 'zip_contents: <bytes>' in plan_output

    def test_can_print_multiple_instructions(self):
        instructions = [
            JPSearch(expression='foo.bar', input_var='in1', output_var='out1'),
            JPSearch(expression='foo.baz', input_var='in2', output_var='out2'),
        ]
        plan_output = self.get_plan_output(instructions)
        # Use a regex to ensure they're printed in order.
        assert re.search(
            'JP_SEARCH.*expression: foo.bar.*'
            'JP_SEARCH.*expression: foo.baz', plan_output,
            re.MULTILINE | re.DOTALL
        ) is not None

    def test_empty_values_omitted(self):
        params = {'name': 'foo', 'empty_list': [],
                  'empty_dict': {}, 'empty_str': ''}
        call = APICall('create_role', params)

        plan_output = self.get_plan_output([call])
        assert 'empty_list' not in plan_output
        assert 'empty_dict' not in plan_output
        assert 'empty_str' not in plan_output


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

    def test_can_handle_dict_value_by_key(self):
        variables = {
            'domain_name': {
                'base_path_mapping': {
                    'path': '/'
                }
            }
        }
        assert self.resolve_vars(
            KeyDataVariable('domain_name', 'base_path_mapping'), variables
        ) == {'path': '/'}
