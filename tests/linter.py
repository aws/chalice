from pylint.checkers import BaseChecker
from pylint.interfaces import IAstroidChecker
from astroid.exceptions import InferenceError


def register(linter):
    linter.register_checker(PatchChecker(linter))


class PatchChecker(BaseChecker):
    __implements__ = (IAstroidChecker,)
    name = 'patching-banned'
    msgs = {
        'C9999': ('Use of mock.patch is not allowed',
                  'patch-call',
                  'Use of mock.patch not allowed')
    }
    patch_pytype = 'mock.mock._patch'

    def visit_call(self, node):
        try:
            for inferred_type in node.infer():
                if inferred_type.pytype() == self.patch_pytype:
                    self.add_message('patch-call', node=node)
        except InferenceError:
            # It's ok if we can't work out what type the function
            # call is.
            pass
