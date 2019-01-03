from pylint.checkers import BaseChecker
from pylint.interfaces import IAstroidChecker
from astroid.exceptions import InferenceError


def register(linter):
    linter.register_checker(MocksUseSpecArg(linter))


class MocksUseSpecArg(BaseChecker):
    __implements__ = (IAstroidChecker,)
    name = 'mocks-use-spec'
    msgs = {
        'C9998': ('mock.Mock() must provide "spec=" argument',
                  'mock-missing-spec',
                  'mock.Mock() must provide "spec=" argument')
    }
    mock_pytype = 'mock.mock.Mock'
    required_kwarg = 'spec'

    def visit_call(self, node):
        try:
            for inferred_type in node.infer():
                if inferred_type.pytype() == self.mock_pytype:
                    self._verify_spec_arg_provided(node)
        except InferenceError:
            pass

    def _verify_spec_arg_provided(self, node):
        if not node.keywords:
            self.add_message('mock-missing-spec', node=node)
            return
        kwargs = [kwarg.arg for kwarg in node.keywords]
        if self.required_kwarg not in kwargs:
            self.add_message('mock-missing-spec', node=node)
