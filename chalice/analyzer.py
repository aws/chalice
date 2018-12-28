"""Source code analyzer for chalice app.

The main point of this module is to analyze your source code
and track which AWS API calls you make.

We can then use this information to create IAM policies
automatically for you.

How it Works
============

This is basically a simplified abstract interpreter.
The type inference is greatly simplified because
we're only interested in boto3 client types.
In a nutshell:

* Create an AST and symbol table from the source code.
* Interpret the AST and track boto3 types.  This is governed
  by a few simple rules.
* Propagate inferred boto3 types as much as possible.  Most of
  the basic stuff is handled, for example:

      * ``x = y`` if y is a boto3 type, so is x.
      * ``a :: (x -> y), where y is a boto3 type, then given ``b = a()``,
        b is of type y.
      * Map inferred types across function params and return types.

At the end of the analysis, a final walk is performed to collect any
node of type ``Boto3ClientMethodCallType``.  This represents an
API call being made.  This also lets you be selective about which
API calls you care about.  For example, if you want only want to see
which API calls happen in a particular function, only walk that
particular ``FunctionDef`` node.

"""
import ast
import symtable

from typing import Dict, Set, Any, Optional, List, Union, cast  # noqa


APICallT = Dict[str, Set[str]]
OptASTSet = Optional[Set[ast.AST]]
ComprehensionNode = Union[ast.DictComp, ast.GeneratorExp, ast.ListComp]


def get_client_calls(source_code):
    # type: (str) -> APICallT
    """Return all clients calls made in provided source code.

    :returns: A dict of service_name -> set([client calls]).
        Example: {"s3": set(["list_objects", "create_bucket"]),
                  "dynamodb": set(["describe_table"])}
    """
    parsed = parse_code(source_code)
    t = SymbolTableTypeInfer(parsed)
    binder = t.bind_types()
    collector = APICallCollector(binder)
    api_calls = collector.collect_api_calls(parsed.parsed_ast)
    return api_calls


def get_client_calls_for_app(source_code):
    # type: (str) -> APICallT
    """Return client calls for a chalice app.

    This is similar to ``get_client_calls`` except it will
    automatically traverse into chalice views with the assumption
    that they will be called.

    """
    parsed = parse_code(source_code)
    parsed.parsed_ast = AppViewTransformer().visit(parsed.parsed_ast)
    ast.fix_missing_locations(parsed.parsed_ast)
    t = SymbolTableTypeInfer(parsed)
    binder = t.bind_types()
    collector = APICallCollector(binder)
    api_calls = collector.collect_api_calls(parsed.parsed_ast)
    return api_calls


def parse_code(source_code, filename='app.py'):
    # type: (str, str) -> ParsedCode
    parsed = ast.parse(source_code, filename)
    table = symtable.symtable(source_code, filename, 'exec')
    return ParsedCode(parsed, ChainedSymbolTable(table, table))


class BaseType(object):
    def __repr__(self):
        # type: () -> str
        return "%s()" % self.__class__.__name__

    def __eq__(self, other):
        # type: (Any) -> bool
        return isinstance(other, self.__class__)


# The next 5 classes are used to track the
# components needed to create a boto3 client.
# While we really only care about boto3 clients we need
# to track all the types it takes to get there:
#
# import boto3          <--- bind "boto3" as the boto3 module type
# c = boto.client       <--- bind "c" as the boto3 create client type
# s3 = c('s3')          <--- bind 's3' as the boto3 client type, subtype 's3'.
# m = s3.list_objects   <--- bind as API call 's3', 'list_objets'
# r = m()               <--- bind as API call invoked (what we care about).
#
# That way we can handle (in addition to the case above) things like:
# import boto3; boto3.client('s3').list_objects()
# import boto3; s3 = boto3.client('s3'); s3.list_objects()
class Boto3ModuleType(BaseType):
    pass


class Boto3CreateClientType(BaseType):
    pass


class Boto3ClientType(BaseType):
    def __init__(self, service_name):
        # type: (str) -> None
        #: The name of the AWS service, e.g. 's3'.
        self.service_name = service_name

    def __eq__(self, other):
        # type: (Any) -> bool
        # NOTE: We can't use self.__class__ because of a mypy bug:
        # https://github.com/python/mypy/issues/3061
        # We can change this back once that bug is fixed.
        if not isinstance(other, Boto3ClientType):
            return False
        return self.service_name == other.service_name

    def __repr__(self):
        # type: () -> str
        return "%s(%s)" % (self.__class__.__name__, self.service_name)


class Boto3ClientMethodType(BaseType):
    def __init__(self, service_name, method_name):
        # type: (str, str) -> None
        self.service_name = service_name
        self.method_name = method_name

    def __eq__(self, other):
        # type: (Any) -> bool
        if self.__class__ != other.__class__:
            return False
        return (
            self.service_name == other.service_name and
            self.method_name == other.method_name)

    def __repr__(self):
        # type: () -> str
        return "%s(%s, %s)" % (
            self.__class__.__name__,
            self.service_name,
            self.method_name
        )


class Boto3ClientMethodCallType(Boto3ClientMethodType):
    pass


class TypedSymbol(symtable.Symbol):
    inferred_type = None  # type: Any
    ast_node = None  # type: ast.AST


class FunctionType(BaseType):
    def __init__(self, return_type):
        # type: (Any) -> None
        self.return_type = return_type

    def __eq__(self, other):
        # type: (Any) -> bool
        if self.__class__ != other.__class__:
            return False
        return self.return_type == other.return_type

    def __repr__(self):
        # type: () -> str
        return "%s(%s)" % (
            self.__class__.__name__,
            self.return_type,
        )


class StringLiteral(object):
    def __init__(self, value):
        # type: (str) -> None
        self.value = value


class ParsedCode(object):
    def __init__(self, parsed_ast, symbol_table):
        # type: (ast.AST, ChainedSymbolTable) -> None
        self.parsed_ast = parsed_ast
        self.symbol_table = symbol_table


class APICallCollector(ast.NodeVisitor):
    """Traverse a given AST and look for any inferred API call types.

    This visitor assumes you've ran type inference on the AST.
    It will search through the AST and collect any API calls.
    """
    def __init__(self, binder):
        # type: (TypeBinder) -> None
        self.api_calls = {}  # type: APICallT
        self._binder = binder

    def collect_api_calls(self, node):
        # type: (ast.AST) -> APICallT
        self.visit(node)
        return self.api_calls

    def visit(self, node):
        # type: (ast.AST) -> None
        inferred_type = self._binder.get_type_for_node(node)
        if isinstance(inferred_type, Boto3ClientMethodCallType):
            self.api_calls.setdefault(inferred_type.service_name, set()).add(
                inferred_type.method_name)
        ast.NodeVisitor.visit(self, node)


class ChainedSymbolTable(object):
    def __init__(self, local_table, global_table):
        # type: (symtable.SymbolTable, symtable.SymbolTable) -> None
        # If you're in the module scope, then pass in
        # the same symbol table for local and global.
        self._local_table = local_table
        self._global_table = global_table

    def new_sub_table(self, local_table):
        # type: (symtable.SymbolTable) -> ChainedSymbolTable
        # Create a new symbol table using this instances
        # local table as the new global table and the passed
        # in local table as the new local table.
        return self.__class__(local_table, self._local_table)

    def get_inferred_type(self, name):
        # type: (str) -> Any
        # Given a symbol name, check whether a type
        # has been inferred.
        # The stdlib symtable will already fall back to
        # global scope if necessary.
        symbol = self._local_table.lookup(name)
        if symbol.is_global():
            try:
                global_symbol = self._global_table.lookup(name)
            except KeyError:
                # It's not an error if a symbol.is_global()
                # but is not in our "_global_table", because
                # we're not considering the builtin scope.
                # In this case we just say that there is no
                # type we've inferred.
                return None
            return getattr(global_symbol, 'inferred_type', None)
        return getattr(symbol, 'inferred_type', None)

    def set_inferred_type(self, name, inferred_type):
        # type: (str, Any) -> None
        symbol = cast(TypedSymbol, self._local_table.lookup(name))
        symbol.inferred_type = inferred_type

    def lookup_sub_namespace(self, name):
        # type: (str) -> ChainedSymbolTable
        for child in self._local_table.get_children():
            if child.get_name() == name:
                return self.__class__(child, self._local_table)
        for child in self._global_table.get_children():
            if child.get_name() == name:
                return self.__class__(child, self._global_table)
        raise ValueError("Unknown symbol name: %s" % name)

    def get_sub_namespaces(self):
        # type: () -> List[symtable.SymbolTable]
        return self._local_table.get_children()

    def get_name(self):
        # type: () -> str
        return self._local_table.get_name()

    def get_symbols(self):
        # type: () -> List[symtable.Symbol]
        return self._local_table.get_symbols()

    def register_ast_node_for_symbol(self, name, node):
        # type: (str, ast.AST) -> None
        symbol = cast(TypedSymbol, self._local_table.lookup(name))
        symbol.ast_node = node

    def lookup_ast_node_for_symbol(self, name):
        # type: (str) -> ast.AST
        symbol = self._local_table.lookup(name)
        if symbol.is_global():
            symbol = self._global_table.lookup(name)
        try:
            return cast(TypedSymbol, symbol).ast_node
        except AttributeError:
            raise ValueError(
                "No AST node registered for symbol: %s" % name)

    def has_ast_node_for_symbol(self, name):
        # type: (str) -> bool
        try:
            self.lookup_ast_node_for_symbol(name)
            return True
        except (ValueError, KeyError):
            return False


class TypeBinder(object):

    def __init__(self):
        # type: () -> None
        self._node_to_type = {}  # type: Dict[ast.AST, Any]

    def get_type_for_node(self, node):
        # type: (Any) -> Any
        return self._node_to_type.get(node)

    def set_type_for_node(self, node, inferred_type):
        # type: (Any, Any) -> None
        self._node_to_type[node] = inferred_type


class SymbolTableTypeInfer(ast.NodeVisitor):
    _SDK_PACKAGE = 'boto3'
    _CREATE_CLIENT = 'client'

    def __init__(self, parsed_code, binder=None, visited=None):
        # type: (ParsedCode, Optional[TypeBinder], OptASTSet) -> None
        self._symbol_table = parsed_code.symbol_table
        self._current_ast_namespace = parsed_code.parsed_ast
        self._node_inference = {}  # type: Dict[ast.AST, Any]
        if binder is None:
            binder = TypeBinder()
        if visited is None:
            visited = set()
        self._binder = binder
        self._visited = visited

    def bind_types(self):
        # type: () -> TypeBinder
        self.visit(self._current_ast_namespace)
        return self._binder

    def known_types(self, scope_name=None):
        # type: (Optional[str]) -> Dict[str, Any]
        table = None
        if scope_name is None:
            table = self._symbol_table
        else:
            table = self._symbol_table.lookup_sub_namespace(scope_name)
        return {
            s.get_name(): cast(TypedSymbol, s).inferred_type
            for s in table.get_symbols()
            if hasattr(s, 'inferred_type') and
            cast(TypedSymbol, s).inferred_type is not None and
            s.is_local()
        }

    def _set_inferred_type_for_name(self, name, inferred_type):
        # type: (str, Any) -> None
        self._symbol_table.set_inferred_type(name, inferred_type)

    def _set_inferred_type_for_node(self, node, inferred_type):
        # type: (Any, Any) -> None
        self._binder.set_type_for_node(node, inferred_type)

    def _get_inferred_type_for_node(self, node):
        # type: (Any) -> Any
        return self._binder.get_type_for_node(node)

    def _new_inference_scope(self, parsed_code, binder, visited):
        # type: (ParsedCode, TypeBinder, Set[ast.AST]) -> SymbolTableTypeInfer
        instance = self.__class__(parsed_code, binder, visited)
        return instance

    def visit_Import(self, node):
        # type: (ast.Import) -> None
        for child in node.names:
            if isinstance(child, ast.alias):
                import_name = child.name
                if import_name == self._SDK_PACKAGE:
                    self._set_inferred_type_for_name(
                        import_name, Boto3ModuleType())
        self.generic_visit(node)

    def visit_Name(self, node):
        # type: (ast.Name) -> None
        self._set_inferred_type_for_node(
            node,
            self._symbol_table.get_inferred_type(node.id)
        )
        self.generic_visit(node)

    def visit_Assign(self, node):
        # type: (ast.Assign) -> None
        # The LHS gets the inferred type of the RHS.
        # We do this post-traversal to let the type inference
        # run on the children first.
        self.generic_visit(node)
        rhs_inferred_type = self._get_inferred_type_for_node(node.value)
        if rhs_inferred_type is None:
            # Special casing assignment to a string literal.
            if isinstance(node.value, ast.Str):
                rhs_inferred_type = StringLiteral(node.value.s)
                self._set_inferred_type_for_node(node.value, rhs_inferred_type)
        for t in node.targets:
            if isinstance(t, ast.Name):
                self._symbol_table.set_inferred_type(t.id, rhs_inferred_type)
                self._set_inferred_type_for_node(node, rhs_inferred_type)

    def visit_Attribute(self, node):
        # type: (ast.Attribute) -> None
        self.generic_visit(node)
        lhs_inferred_type = self._get_inferred_type_for_node(node.value)
        if lhs_inferred_type is None:
            return
        elif lhs_inferred_type == Boto3ModuleType():
            # Check for attributes such as boto3.client.
            if node.attr == self._CREATE_CLIENT:
                # This is a "boto3.client" attribute.
                self._set_inferred_type_for_node(node, Boto3CreateClientType())
        elif isinstance(lhs_inferred_type, Boto3ClientType):
            self._set_inferred_type_for_node(
                node,
                Boto3ClientMethodType(
                    lhs_inferred_type.service_name,
                    node.attr
                )
            )

    def visit_Call(self, node):
        # type: (ast.Call) -> None
        self.generic_visit(node)
        # func -> Node that's being called
        # args -> Arguments being passed.
        inferred_func_type = self._get_inferred_type_for_node(node.func)
        if inferred_func_type == Boto3CreateClientType():
            # e_0 : B3CCT -> B3CT[S]
            # e_1 : S str which is a service name
            # e_0(e_1) : B3CT[e_1]
            if len(node.args) >= 1:
                service_arg = node.args[0]
                if isinstance(service_arg, ast.Str):
                    self._set_inferred_type_for_node(
                        node, Boto3ClientType(service_arg.s))
                elif isinstance(self._get_inferred_type_for_node(service_arg),
                                StringLiteral):
                    sub_type = self._get_inferred_type_for_node(service_arg)
                    inferred_type = Boto3ClientType(sub_type.value)
                    self._set_inferred_type_for_node(node, inferred_type)
        elif isinstance(inferred_func_type, Boto3ClientMethodType):
            self._set_inferred_type_for_node(
                node,
                Boto3ClientMethodCallType(
                    inferred_func_type.service_name,
                    inferred_func_type.method_name
                )
            )
        elif isinstance(inferred_func_type, FunctionType):
            self._set_inferred_type_for_node(
                node, inferred_func_type.return_type)
        elif isinstance(node.func, ast.Name) and \
                self._symbol_table.has_ast_node_for_symbol(node.func.id):
            if node not in self._visited:
                self._visited.add(node)
                self._infer_function_call(node)

    def visit_Lambda(self, node):
        # type: (ast.Lambda) -> None
        # Lambda is going to be a bit tricky because
        # there's a new child namespace (via .get_children()),
        # but it's not something that will show up in the
        # current symbol table via .lookup().
        # For now, we're going to ignore lambda expressions.
        pass

    def _infer_function_call(self, node):
        # type: (Any) -> None
        # Here we're calling a function we haven't analyzed
        # yet.  We're first going to analyze the function.
        # This will set the inferred_type on the FunctionDef
        # node.
        # If we get a FunctionType as the inferred type of the
        # function, then we know that the inferred type for
        # calling the function is the .return_type type.
        function_name = node.func.id
        sub_table = self._symbol_table.lookup_sub_namespace(function_name)
        ast_node = self._symbol_table.lookup_ast_node_for_symbol(
            function_name)

        self._map_function_params(sub_table, node, ast_node)

        child_infer = self._new_inference_scope(
            ParsedCode(ast_node, sub_table), self._binder, self._visited)
        child_infer.bind_types()
        inferred_func_type = self._get_inferred_type_for_node(ast_node)
        self._symbol_table.set_inferred_type(function_name, inferred_func_type)
        # And finally the result of this Call() node will be
        # the return type from the function we just analyzed.
        if isinstance(inferred_func_type, FunctionType):
            self._set_inferred_type_for_node(
                node, inferred_func_type.return_type)

    def _map_function_params(self, sub_table, node, def_node):
        # type: (ChainedSymbolTable, Any, Any) -> None
        # TODO: Handle the full calling syntax, kwargs, stargs, etc.
        #       Right now we just handle positional args.
        defined_args = def_node.args
        for arg, defined in zip(node.args, defined_args.args):
            inferred_type = self._get_inferred_type_for_node(arg)
            if inferred_type is not None:
                name = self._get_name(defined)
                sub_table.set_inferred_type(name, inferred_type)

    def _get_name(self, node):
        # type: (Any) -> str
        try:
            return getattr(node, 'id')
        except AttributeError:
            return getattr(node, 'arg')

    def visit_FunctionDef(self, node):
        # type: (ast.FunctionDef) -> None
        if node.name == self._symbol_table.get_name():
            # Not using generic_visit() because we don't want to
            # visit the decorator_list attr.
            for child in node.body:
                self.visit(child)
        else:
            self._symbol_table.register_ast_node_for_symbol(node.name, node)

    def visit_AsyncFunctionDef(self, node):
        # type: (ast.FunctionDef) -> None
        # this type is actually wrong but we can't use the actual type as it's
        # not available in python 2
        self.visit_FunctionDef(node)

    def visit_ClassDef(self, node):
        # type: (ast.ClassDef) -> None
        # Not implemented yet.  We want to ensure we don't
        # traverse into the class body for now.
        return

    def visit_DictComp(self, node):
        # type: (ast.DictComp) -> None
        self._handle_comprehension(node, 'dictcomp')

    def visit_Return(self, node):
        # type: (Any) -> None
        self.generic_visit(node)
        inferred_type = self._get_inferred_type_for_node(node.value)
        if inferred_type is not None:
            self._set_inferred_type_for_node(node, inferred_type)
            # We're making a pretty big assumption there's one return
            # type per function.  Will likely need to come back to this.
            inferred_func_type = FunctionType(inferred_type)
            self._set_inferred_type_for_node(self._current_ast_namespace,
                                             inferred_func_type)

    def visit_ListComp(self, node):
        # type: (ast.ListComp) -> None
        # 'listcomp' is the string literal used by python
        # to creating the SymbolTable for the corresponding
        # list comp function.
        self._handle_comprehension(node, 'listcomp')

    def visit_GeneratorExp(self, node):
        # type: (ast.GeneratorExp) -> None
        # Generator expressions are an interesting case.
        # They create a new sub scope, but they're not
        # explicitly named.  Python just creates a table
        # with the name "genexpr".
        self._handle_comprehension(node, 'genexpr')

    def _visit_first_comprehension_generator(self, node):
        # type: (ComprehensionNode) -> None
        if node.generators:
            # first generator's iterator is visited in the current scope
            first_generator = node.generators[0]
            self.visit(first_generator.iter)

    def _collect_comprehension_children(self, node):
        # type: (ComprehensionNode) -> List[ast.expr]
        if isinstance(node, ast.DictComp):
            # dict comprehensions have two values to be checked
            child_nodes = [node.key, node.value]
        else:
            child_nodes = [node.elt]

        if node.generators:
            first_generator = node.generators[0]
            child_nodes.append(first_generator.target)
            for if_expr in first_generator.ifs:
                child_nodes.append(if_expr)

        for generator in node.generators[1:]:
            # rest need to be visited in the child scope
            child_nodes.append(generator.iter)
            child_nodes.append(generator.target)
            for if_expr in generator.ifs:
                child_nodes.append(if_expr)
        return child_nodes

    def _visit_comprehension_children(self, node, comprehension_type):
        # type: (ComprehensionNode, str) -> None
        child_nodes = self._collect_comprehension_children(node)
        child_scope = self._get_matching_sub_namespace(comprehension_type,
                                                       node.lineno)
        if child_scope is None:
            # In Python 2 there's no child scope for list comp
            # Or we failed to locate the child scope, this happens in Python 2
            # when there are multiple comprehensions of the same type in the
            # same scope. The line number trick doesn't work as Python 2 always
            # passes line number 0, make a best effort
            for child_node in child_nodes:
                try:
                    self.visit(child_node)
                except KeyError:
                    pass
            return
        for child_node in child_nodes:
            # visit sub expressions in the child scope
            child_table = self._symbol_table.new_sub_table(child_scope)
            child_infer = self._new_inference_scope(
                ParsedCode(child_node, child_table),
                self._binder, self._visited)
            child_infer.bind_types()

    def _handle_comprehension(self, node, comprehension_type):
        # type: (ComprehensionNode, str) -> None
        self._visit_first_comprehension_generator(node)
        self._visit_comprehension_children(node, comprehension_type)

    def _get_matching_sub_namespace(self, name, lineno):
        # type: (str, int) -> Optional[symtable.SymbolTable]
        namespaces = [t for t in self._symbol_table.get_sub_namespaces()
                      if t.get_name() == name]
        if len(namespaces) == 1:
            # if there's only one match for the name, return it
            return namespaces[0]
        for namespace in namespaces:
            # otherwise disambiguate by using the line number
            if namespace.get_lineno() == lineno:
                return namespace
        return None

    def visit(self, node):
        # type: (Any) -> None
        return ast.NodeVisitor.visit(self, node)


class AppViewTransformer(ast.NodeTransformer):
    _CHALICE_DECORATORS = [
        'route', 'authorizer', 'lambda_function',
        'schedule', 'on_s3_event', 'on_sns_message',
        'on_sqs_message', 'websocket',
    ]

    def visit_FunctionDef(self, node):
        # type: (ast.FunctionDef) -> Any
        if self._is_chalice_view(node):
            return self._auto_invoke_view(node)
        return node

    def _is_chalice_view(self, node):
        # type: (ast.FunctionDef) -> bool
        # We can certainly improve on this, but this check is more
        # of a heuristic for the time being.  The ideal way to do this
        # is to infer the Chalice type and ensure the function is
        # decorated with the Chalice type's route() method.
        decorator_list = node.decorator_list
        if not decorator_list:
            return False
        for decorator in decorator_list:
            if isinstance(decorator, ast.Call) and \
                    isinstance(decorator.func, ast.Attribute):
                if decorator.func.attr in self._CHALICE_DECORATORS:
                    return True
        return False

    def _auto_invoke_view(self, node):
        # type: (ast.FunctionDef) -> List[ast.AST]
        auto_invoke = ast.Expr(
            value=ast.Call(
                func=ast.Name(id=node.name, ctx=ast.Load()),
                args=[], keywords=[], starargs=None, kwargs=None
            )
        )
        return [node, auto_invoke]
