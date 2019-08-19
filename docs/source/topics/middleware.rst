Middlewares
===========

Chalice middlewares allow to modify the request/response cycle.

To create a new middleware you need to inherit from the base Middleware class
provided by Chalice and override ``__call__`` method.


.. note::

  You must call the parent ``__call__`` method to continue the request
  processing. Also, every middleware ``__call__`` method must return the
  response of the parent method call.


Examples
--------

The following code describes basic middleware usage:

.. code-block:: python

    from chalice import Chalice, Middleware

    app = Chalice(app_name='middleware-demo')

    class ExampleMiddleware(Middleware):
        def __call__(self, *args, **kwargs):
            # do something with app.current_request here
            response = super().__call__(*args, **kwargs)
            # modify response here
            return response


    app.middlewares = [ExampleMiddleware]

Сalling the ``__call__`` method ___ invocation of all next middlewares in
the list and, as a result, the call of the view function.

Below you can see the example of the middleware which act as adapter
for endpoints and allow to change endpoint content-type without
the modification of the view code.

.. code-block:: python

    from chalice import Chalice, Middleware

    app = Chalice(app_name='middleware-demo')

    class YAMLMiddleware(Middleware):
        def __call__(self, *args, **kwargs):
            request = app.current_request
            is_yaml = request.headers.get('Content-Type') == "text/yaml"

            if is_yaml:
                body = request.raw_body.decode("utf8")
                request._json_body = yaml.safe_load(body)
                request.headers._dict["content-type"] = "application/json"

            response = super().__call__(*args, **kwargs)

            if is_yaml:
                response.headers["Content-Type"] = "text/yaml"
                yaml_body = yaml.dump(response.body, default_flow_style=False)
                response.body = yaml_body

            return response

    app.middlewares.append(YAMLMiddleware)

    @app.route("/index", methods=["POST"], content_types=["application/json", "text/yaml"])
    def index():
        return app.current_request.json_body
