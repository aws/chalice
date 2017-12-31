
class Blueprint:

    REGISTERED_APP = None

    def __init__(self, name):
        self.name = name
        self.routes = []

    def url_for(self, view_name):
        if view_name.startswith('{}.'.format(self.name)):
            pass
        else:
            view_name = '{}.{}'.format(self.name, view_name.lstrip('.'))

        if self.REGISTERED_APP is None:
            raise RuntimeError('Blueprint must be registered first!')
        for path, methods in self.REGISTERED_APP.routes.items():
            for method in methods.keys():
                if self.REGISTERED_APP.routes[path][method].view_name == view_name:
                    return path

        raise LookupError('No url found for {}'.format(view_name))

    @property
    def current_request(self):
        if self.REGISTERED_APP is None:
            raise RuntimeError('Blueprint must be registered first!')
        return self.REGISTERED_APP.current_request

    def route(self, path, **kwargs):
        def _register_view(view_func):
            self.routes.append((path, view_func, kwargs))
            return view_func
        return _register_view
