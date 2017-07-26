Routing
=======

The :meth:`Chalice.route` method is used to contruct which routes
you want to create for your API.  The concept is the same
mechanism used by `Flask <http://flask.pocoo.org/>`__ and
`bottle <http://bottlepy.org/docs/dev/index.html>`__.
You decorate a function with ``@app.route(...)``, and whenever
a user requests that URL, the function you've decorated is called.
For example, suppose you deployed this app:

.. code-block:: python

    from chalice import Chalice

    app = Chalice(app_name='helloworld')


    @app.route('/')
    def index():
        return {'view': 'index'}

    @app.route('/a')
    def a():
        return {'view': 'a'}

    @app.route('/b')
    def b():
        return {'view': 'b'}


If you go to ``https://endpoint/``, the ``index()`` function would be called.
If you went to ``https://endpoint/a`` and ``https://endpoint/b``, then the
``a()`` and ``b()`` function would be called, respectively.

.. note::

  Do not end your route paths with a trailing slash.  If you do this, the
  ``chalice deploy`` command will raise a validation error.


You can also create a route that captures part of the URL.  This captured value
will then be passed in as arguments to your view function:


.. code-block:: python

    from chalice import Chalice

    app = Chalice(app_name='helloworld')


    @app.route('/users/{name}')
    def users(name):
        return {'name': name}


If you then go to ``https://endpoint/users/james``, then the view function
will be called as: ``users('james')``.  The parameters are passed as
keyword parameters based on the name as they appear in the URL. The argument
names for the view function must match the name of the captured
argument:


.. code-block:: python

    from chalice import Chalice

    app = Chalice(app_name='helloworld')


    @app.route('/a/{first}/b/{second}')
    def users(first, second):
        return {'first': first, 'second': second}


Other Request Metadata
----------------------

The route path can only contain ``[a-zA-Z0-9._-]`` chars and curly braces for
parts of the URL you want to capture.  You do not need to model other parts of
the request you want to capture, including headers and query strings.  Within
a view function, you can introspect the current request using the
:attr:`app.current_request <Chalice.current_request>` attribute.  This also
means you cannot control the routing based on query strings or headers.
Here's an example for accessing query string data in a view function:

.. code-block:: python

    from chalice import Chalice

    app = Chalice(app_name='helloworld')


    @app.route('/users/{name}')
    def users(name):
        result = {'name': name}
        if app.current_request.query_params.get('include-greeting') == 'true':
            result['greeting'] = 'Hello, %s' % name
        return result

In the function above, if the user provides a ``?include-greeting=true`` in the
HTTP request, then an additional ``greeting`` key will be returned::

    $ http https://endpoint/dev/users/bob

    {
        "name": "bob"
    }

    $ http https://endpoint/dev/users/bob?include-greeting=true

    {
        "greeting": "Hello, bob",
        "name": "bob"
    }
