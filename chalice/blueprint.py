
class Blueprint:

    REGISTERED_APP = None

    def __init__(self, name):
        self.name = name
        self.routes = []

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
