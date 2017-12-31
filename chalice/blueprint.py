
class Blueprint:

    def __init__(self, name):
        self.name = name
        self.routes = []

    def route(self, path, **kwargs):
        def _register_view(view_func):
            self.routes.append((path, view_func, kwargs))
            return view_func
        return _register_view
