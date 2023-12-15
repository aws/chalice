import re
import pprint
from dataclasses import asdict, is_dataclass

import jmespath
from typing import Dict, List, Any  # noqa

from chalice.deploy import models # noqa
from chalice.awsclient import TypedAWSClient  # noqa
from chalice.utils import UI  # noqa


class BaseExecutor(object):
    def __init__(self, client, ui):
        # type: (TypedAWSClient, UI) -> None
        self._client = client
        self._ui = ui
        self.resource_values = []  # type: List[Dict[str, Any]]

    def execute(self, plan):
        # type: (models.Plan) -> None
        pass


class Executor(BaseExecutor):
    def __init__(self, client, ui):
        # type: (TypedAWSClient, UI) -> None
        super(Executor, self).__init__(client, ui)
        # A mapping of variables that's populated as API calls
        # are made.  These can be used in subsequent API calls.
        self.variables = {}  # type: Dict[str, Any]
        self._resource_value_index = {}  # type: Dict[str, Any]
        self._variable_resolver = VariableResolver()

    def execute(self, plan):
        # type: (models.Plan) -> None
        messages = plan.messages
        for instruction in plan.instructions:
            message = messages.get(id(instruction))
            if message is not None:
                self._ui.write(message)
            getattr(self, '_do_%s' % instruction.__class__.__name__.lower(),
                    self._default_handler)(instruction)

    def _default_handler(self, instruction):
        # type: (models.Instruction) -> None
        raise RuntimeError("Deployment executor encountered an "
                           "unknown instruction: %s"
                           % instruction.__class__.__name__)

    def _do_apicall(self, instruction):
        # type: (models.APICall) -> None
        final_kwargs = self._resolve_variables(instruction)
        method = getattr(self._client, instruction.method_name)
        result = method(**final_kwargs)
        if instruction.output_var is not None:
            self.variables[instruction.output_var] = result

    def _do_copyvariable(self, instruction):
        # type: (models.CopyVariable) -> None
        to_var = instruction.to_var
        from_var = instruction.from_var
        self.variables[to_var] = self.variables[from_var]

    def _do_storevalue(self, instruction):
        # type: (models.StoreValue) -> None
        result = self._variable_resolver.resolve_variables(
            instruction.value, self.variables)
        self.variables[instruction.name] = result

    def _do_storemultiplevalue(self, instruction):
        # type: (models.StoreValue) -> None
        result = self._variable_resolver.resolve_variables(
            instruction.value, self.variables)
        data = self.variables.get(instruction.name)
        if data and isinstance(data, list):
            self.variables[instruction.name].extend(result)
        else:
            self.variables[instruction.name] = result

    def _do_recordresourcevariable(self, instruction):
        # type: (models.RecordResourceVariable) -> None
        payload = {
            'name': instruction.resource_name,
            'resource_type': instruction.resource_type,
            instruction.name: self.variables[instruction.variable_name],
        }
        self._add_to_deployed_values(payload)

    def _do_recordresourcevalue(self, instruction):
        # type: (models.RecordResourceValue) -> None
        payload = {
            'name': instruction.resource_name,
            'resource_type': instruction.resource_type,
            instruction.name: instruction.value,
        }
        self._add_to_deployed_values(payload)

    def _add_to_deployed_values(self, payload):
        # type: (Dict[str, str]) -> None
        key = payload['name']
        if key not in self._resource_value_index:
            self._resource_value_index[key] = payload
            self.resource_values.append(payload)
        else:
            # If the key already exists, we merge the new payload
            # with the existing payload.
            self._resource_value_index[key].update(payload)

    def _do_jpsearch(self, instruction):
        # type: (models.JPSearch) -> None
        v = self.variables[instruction.input_var]
        result = jmespath.search(instruction.expression, v)
        self.variables[instruction.output_var] = result

    def _do_builtinfunction(self, instruction):
        # type: (models.BuiltinFunction) -> None
        # Split this out to a separate class of built in functions
        # once we add more functions.
        if instruction.function_name == 'parse_arn':
            resolved_args = self._variable_resolver.resolve_variables(
                instruction.args, self.variables)
            value = resolved_args[0]
            parts = value.split(':')
            result = {
                'partition': parts[1],
                'service': parts[2],
                'region': parts[3],
                'account_id': parts[4],
                'dns_suffix': self._client.endpoint_dns_suffix(parts[2],
                                                               parts[3])
            }
            self.variables[instruction.output_var] = result
        elif instruction.function_name == 'interrogate_profile':
            region = self._client.region_name
            result = {
                'partition': self._client.partition_name,
                'region': region,
                'dns_suffix': self._client.endpoint_dns_suffix('apigateway',
                                                               region)
            }
            self.variables[instruction.output_var] = result
        elif instruction.function_name == 'service_principal':
            resolved_args = self._variable_resolver.resolve_variables(
                instruction.args, self.variables)
            service_name = resolved_args[0]
            region_name = self._client.region_name
            dns_suffix = self._client.endpoint_dns_suffix(service_name,
                                                          region_name)
            result = {
                'principal': self._client.service_principal(service_name,
                                                            region_name,
                                                            dns_suffix)
            }
            self.variables[instruction.output_var] = result
        else:
            raise ValueError("Unknown builtin function: %s"
                             % instruction.function_name)

    def _resolve_variables(self, api_call):
        # type: (models.APICall) -> Dict[str, Any]
        try:
            return self._variable_resolver.resolve_variables(
                api_call.params, self.variables)
        except UnresolvedValueError as e:
            e.method_name = api_call.method_name
            raise


class VariableResolver(object):
    def resolve_variables(self, value, variables):
        # type: (Any, Dict[str, str]) -> Any

        value_type = type(value).__name__.lower()
        handler_name = '_resolve_%s' % value_type
        handler = getattr(self, handler_name, None)
        if handler:
            return handler(value, variables)
        else:
            return value

    def _resolve_variable(self, value, variables):
        # type: (Any, Dict[str, str]) -> Any
        return variables[value.name]

    def _resolve_stringformat(self, value, variables):
        # type: (Any, Dict[str, str]) -> Any
        v = {k: variables[k] for k in value.variables}
        return value.template.format(**v)

    def _resolve_keydatavariable(self, value, variables):
        # type: (Any, Dict[str, str]) -> Any
        return variables[value.name][value.key]

    def _resolve_placeholder(self, value, variables):
        # type: (Any, Dict[str, str]) -> Any
        # The key and method_name values are added
        # as the exception propagates up the stack.
        raise UnresolvedValueError('', value, '')

    def _resolve_dict(self, value, variables):
        # type: (Any, Dict[str, str]) -> Any
        final = {}
        for k, v in value.items():
            try:
                final[k] = self.resolve_variables(v, variables)
            except UnresolvedValueError as e:
                e.key = k
                raise
        return final

    def _resolve_list(self, value, variables):
        # type: (Any, Dict[str, str]) -> Any
        final_list = []
        for v in value:
            final_list.append(self.resolve_variables(v, variables))
        return final_list


# This class is used for the ``chalice dev plan`` command.
# The dev commands don't have any backwards compatibility guarantees
# so we can alter this output as needed.
class DisplayOnlyExecutor(BaseExecutor):
    # Max length of bytes object before we truncate with '<bytes>'
    _MAX_BYTE_LENGTH = 30
    _LINE_VERTICAL = '\u2502'

    def execute(self, plan):
        # type: (models.Plan) -> None
        spillover_values = {}  # type: Dict[str, Any]
        self._ui.write("Plan\n")
        self._ui.write("====\n\n")
        for instruction in plan.instructions:
            getattr(self, '_do_%s' % instruction.__class__.__name__.lower(),
                    self._default_handler)(instruction, spillover_values)
        self._write_spillover(spillover_values)

    def _write_spillover(self, spillover_values):
        # type: (Dict[str, Any]) -> None
        if not spillover_values:
            return
        self._ui.write("Variable Pool\n")
        self._ui.write("=============\n\n")
        for key, value in spillover_values.items():
            self._ui.write('%s:\n' % key)
            self._ui.write(pprint.pformat(value) + '\n\n')

    def _default_handler(self, instruction, spillover_values):
        # type: (models.Instruction, Dict[str, Any]) -> None
        instruction_name = self._upper_snake_case(
            instruction.__class__.__name__)
        # Need this to make typing happy . We're certain that we're always
        # dealing with a dataclass, but the base type `Instruction` has
        # no dataclass pieces.  There's probably a better way to represent
        # this type hierarchy.
        assert is_dataclass(instruction) and not isinstance(instruction, type)
        for key, value in asdict(instruction).items():
            if isinstance(value, dict):
                value = self._format_dict(value, spillover_values)
            line = ('%-30s %s%20s %-10s' % (
                instruction_name, self._LINE_VERTICAL, '%s:' % key, value)
            )
            self._ui.write(line + '\n')
            instruction_name = ''
        self._ui.write('\n')

    def _format_dict(self, dict_value, spillover_values):
        # type: (Dict[str, Any], Dict[str, Any]) -> str
        lines = ['']
        for key, value in dict_value.items():
            if not value:
                continue
            if isinstance(value, bytes) and len(value) > self._MAX_BYTE_LENGTH:
                value = '<bytes>'
            if isinstance(value, (dict, list)):
                # We need a unique name to use so we just use a simple
                # incrementing counter with the name prefixed.
                spillover_name = '${%s_%s}' % (
                    key.upper(), len(spillover_values))
                spillover_values[spillover_name] = value
                value = spillover_name
            line = '%-31s%s%-15s%s%20s %-10s' % (
                ' ', self._LINE_VERTICAL, ' ', self._LINE_VERTICAL,
                '%s:' % key, value
            )
            lines.append(line)
        return '\n'.join(lines)

    def _upper_snake_case(self, v):
        # type: (str) -> str
        first_cap_regex = re.compile('(.)([A-Z][a-z]+)')
        end_cap_regex = re.compile('([a-z0-9])([A-Z])')
        first = first_cap_regex.sub(r'\1_\2', v)
        transformed = end_cap_regex.sub(r'\1_\2', first).upper()
        return transformed


class UnresolvedValueError(Exception):
    MSG = (
        "The API parameter '%s' has an unresolved value "
        "of %s in the method call: %s"
    )

    def __init__(self, key, value, method_name):
        # type: (str, models.Placeholder, str) -> None
        super(UnresolvedValueError, self).__init__()
        self.key = key
        self.value = value
        self.method_name = method_name

    def __str__(self):
        # type: () -> str
        return self.MSG % (self.key, self.value, self.method_name)
