from typing import Any, Callable, List  # noqa

from chalice.app import Request  # noqa


class Blueprint(object):

    REGISTERED_APP = None

    def __init__(self, name):  # type: (str) -> None
        self.name = name  # type: str
        self.routes = []  # type: List

    def url_for(self, view_name):  # type: (str) -> str
        if view_name.startswith('{}.'.format(self.name)):
            pass
        else:
            view_name = '{}.{}'.format(self.name, view_name.lstrip('.'))

        if self.REGISTERED_APP is None:
            raise RuntimeError('Blueprint must be registered first!')
        for path, methods in self.REGISTERED_APP.routes.items():
            for method in methods.keys():
                found_name = self.REGISTERED_APP.routes[path][method].view_name
                if found_name == view_name:
                    return path

        raise LookupError('No url found for {}'.format(view_name))

    @property
    def current_request(self):  # type: () -> Request
        if self.REGISTERED_APP is None:
            raise RuntimeError('Blueprint must be registered first!')
        return self.REGISTERED_APP.current_request

    def route(self, path, **kwargs):  # type: (str, **Any) -> Callable
        def _register_view(view_func):  # type: (Callable) -> Callable
            self.routes.append((path, view_func, kwargs))
            return view_func
        return _register_view
