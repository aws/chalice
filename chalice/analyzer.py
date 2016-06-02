"""Source code analyzer for chalice app."""
import ast

from typing import Dict, Set  # noqa


def get_client_calls(source_code):
    # type: (str) -> Dict[str, Set[str]]
    """Return all clients calls made in the application.

    :returns: A dict of service_name -> set([client calls]).
        Example: {"s3": set(["list_objects", "create_bucket"]),
                  "dynamodb": set(["describe_table"])}
    """
    parsed = ast.parse(source_code, 'app.py')
    v = AWSOperationTracker()
    v.visit(parsed)
    return v.clients


class AWSOperationTracker(ast.NodeVisitor):
    def __init__(self):
        # Mapping of AWS clients created to method
        # calls used. client_name -> [methods_called]
        self.clients = {}  # type: Dict[str, Set[str]]
        # These are the names bound in the module
        # scope for clients that are created.
        self._client_identifiers = {}
        # function_name -> AST
        self._function_defs = {}
        self.deferred_analysis = []

    def visit_Module(self, node):
        self.clients = {}
        self._client_identifiers = {}
        return self.generic_visit(node)

    def visit_Assign(self, node):
        if isinstance(node.value, ast.Call):
            call_node = node.value
            if isinstance(call_node.func, ast.Attribute):
                attr_node = call_node.func
                lhs = attr_node.value
                if isinstance(lhs, ast.Name) and lhs.id == 'boto3':
                    rhs = attr_node.attr
                    if rhs == 'client':
                        client_name = call_node.args[0].s
                        variable_name = node.targets[0].id
                        self._client_identifiers[variable_name] = client_name
                        self.clients.setdefault(client_name, set())
        elif self._assigns_existing_client_vars(node):
            # We also need to check if we're reassigning an existing
            # client identifier to something else.
            assigned_names = [n.id for n in node.targets
                              if isinstance(n, ast.Name)]
            for name in assigned_names:
                if name in self._client_identifiers:
                    del self._client_identifiers[name]
        if isinstance(node.value, ast.Name):
            # We need to check if any client identifiers are
            # being assigned to other variable names.
            if node.value.id in self._client_identifiers:
                if len(node.targets) == 1:
                    alias_name = node.targets[0].id
                    self._client_identifiers[alias_name] = \
                        self._client_identifiers[node.value.id]
        return self.generic_visit(node)

    def _assigns_existing_client_vars(self, node):
        return any(name in self._client_identifiers for name in
                   [n.id for n in node.targets if isinstance(n, ast.Name)])

    def visit_Call(self, node):
        # A Call node has:
        # 'args': [<_ast.Str object at 0x1064a8310>],
        # 'col_offset': 6,
        # 'func': <_ast.Attribute object at 0x1064a8290>,
        # 'keywords': [],
        # 'kwargs': None,
        # 'lineno': 4,
        # 'starargs': None
        if isinstance(node.func, ast.Attribute):
            attr_node = node.func
            # Attribute notes have:
            # 'attr': 'foo'   <--- this is the rhs
            # 'col_offset': 6,
            # 'ctx': <_ast.Load object at 0x10364fad0>,
            # 'lineno': 4,
            # 'value': <_ast.Name object at 0x1036632d0> <--- this is the lhs
            if isinstance(attr_node.value, ast.Name):
                lhs = attr_node.value.id
                if lhs in self._client_identifiers:
                    # This is a client call for an AWS service.
                    client_method_name = attr_node.attr
                    service_name = self._client_identifiers[lhs]
                    self.clients[service_name].add(client_method_name)
        elif isinstance(node.func, ast.Name):
            # Check if any client identifiers are being passed as
            # function arguments.
            arg_vars = [(i, n.id) for i, n in enumerate(node.args)
                        if isinstance(n, ast.Name)]
            if any(v[1] in self._client_identifiers for v in arg_vars):
                # Then a boto3 client is being passed into a function.
                # We need to look into the function code and see
                # how it's being used.
                function_name = node.func.id
                if function_name in self._function_defs:
                    client_args = [(i, self._client_identifiers[v])
                                   for i, v in arg_vars
                                   if v in self._client_identifiers]
                    self._analyze_function(
                        self._function_defs[function_name],
                        client_args)
        return self.generic_visit(node)

    def _analyze_function(self, node, args_to_track):
        v = self.__class__()
        arguments = node.args.args
        client_ids = {}
        clients = {}
        for index, service_name in args_to_track:
            arg_identifier_to_track = arguments[index].id
            client_ids[arg_identifier_to_track] = service_name
            clients.setdefault(service_name, set())
        v._client_identifiers = client_ids
        v.clients = clients
        v.visit(node)
        # Now merge the client calls from the function
        # analysis into the client calls for the main analysis.
        for service, api_calls in v.clients.items():
            self.clients[service].update(api_calls)

    def visit_FunctionDef(self, node):
        # A FunctionDef has these attrs:
        # 'args': <_ast.arguments object at 0x1103848d0>,
        # 'body': [<_ast.Assign object at 0x110384910>,
        #          <_ast.Expr object at 0x110384b50>],
        # 'col_offset': 0,
        # 'decorator_list': [],
        # 'lineno': 2,
        # 'name': 'foo'}
        self._function_defs[node.name] = node
        return self.generic_visit(node)


if __name__ == '__main__':
    from pprint import pprint
    import sys
    pprint(get_client_calls(open(sys.argv[1]).read()))
