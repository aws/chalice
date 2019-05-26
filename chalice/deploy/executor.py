import jmespath

from typing import Dict, List, Any  # noqa

from chalice.deploy import models
from chalice.deploy.planner import Variable, StringFormat
from chalice.awsclient import TypedAWSClient  # noqa
from chalice.utils import UI  # noqa


class Executor(object):
    def __init__(self, client, ui):
        # type: (TypedAWSClient, UI) -> None
        self._client = client
        self._ui = ui
        # A mapping of variables that's populated as API calls
        # are made.  These can be used in subsequent API calls.
        self.variables = {}  # type: Dict[str, Any]
        self.resource_values = []  # type: List[Dict[str, Any]]
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

    def _do_copyvariablefromdict(self, instruction):
        # type: (models.CopyVariableFromDict) -> None
        to_var = instruction.to_var
        key = instruction.key
        from_var = instruction.from_var
        self.variables[to_var] = self.variables[from_var][key]

    def _do_storevalue(self, instruction):
        # type: (models.StoreValue) -> None
        result = self._variable_resolver.resolve_variables(
            instruction.value, self.variables)
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
                'service': parts[2],
                'region': parts[3],
                'account_id': parts[4],
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
        if isinstance(value, Variable):
            return variables[value.name]
        elif isinstance(value, StringFormat):
            v = {k: variables[k] for k in value.variables}
            return value.template.format(**v)
        elif isinstance(value, models.Placeholder):
            # The key and method_name values are added
            # as the exception propagates up the stack.
            raise UnresolvedValueError('', value, '')
        elif isinstance(value, dict):
            final = {}
            for k, v in value.items():
                try:
                    final[k] = self.resolve_variables(v, variables)
                except UnresolvedValueError as e:
                    e.key = k
                    raise
            return final
        elif isinstance(value, list):
            final_list = []
            for v in value:
                final_list.append(self.resolve_variables(v, variables))
            return final_list
        else:
            return value


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
