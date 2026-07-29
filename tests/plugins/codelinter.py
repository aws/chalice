# These are linting checks used in the chalice codebase itself.
# These are used to enforce specific coding standards and constraints.
from pylint.checkers import BaseChecker
from astroid.exceptions import InferenceError
import astroid


def register(linter):
    linter.register_checker(ConditionalImports(linter))


class ConditionalImports(BaseChecker):
    # This is used to ensure that any imports that rely on conditional
    # dependencies must be wrapped in a try/except ImportError.
    name = 'must-catch-import-error'
    msgs = {
        'C9997': ('Importing this module must catch ImportError.',
                  'must-catch-import-error',
                  'Importing this module must catch ImportError.'),
    }

    def visit_import(self, node):
        names = [name[0] for name in node.names]
        if 'chalice.cli.filewatch.eventbased' in names:
            if not self._is_in_try_except_import_error(node):
                self.add_message('must-catch-import-error', node=node)
                return

    def visit_importfrom(self, node):
        if node.modname == 'chalice.cli.filewatch.eventbased':
            names = [name[0] for name in node.names]
            if 'WatchdogWorkerProcess' in names:
                # Ensure this is wrapped in a try/except.
                # Technically we should ensure anywhere in the call stack
                # we're wrapped in a try/except, but in practice we'll just
                # enforce you did that in the same scope as your import.
                if not self._is_in_try_except_import_error(node):
                    self.add_message('must-catch-import-error', node=node)
                    return

    def _is_in_try_except_import_error(self, node):
        if not isinstance(node.parent, astroid.Try):
            return False
        caught_exceptions = [
            handler.type.name for handler in node.parent.handlers]
        if 'ImportError' not in caught_exceptions:
            # They wrapped a try/except but aren't catching
            # ImportError.
            return False
        return True
