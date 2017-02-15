Views
=====

A view function in chalice is the function attached to an
``@app.route()`` decorator.  In the example below, ``index``
is the view function:

.. code-block:: python

    from chalice import Chalice

    app = Chalice(app_name='helloworld')


    @app.route('/')
    def index():
        return {'view': 'index'}


View Function Parameters
------------------------

A view function's parameters correspond to the number of captured
URL parameters specified in the ``@app.route`` call.  In the example above,
the route ``/`` specifies no captured parameters so the ``index`` view
function accepts no parameters.  However, in the view function below,
a single URL parameter, ``{city}`` is specified, so the view function
must accept a single parameter:


.. code-block:: python

    from chalice import Chalice

    app = Chalice(app_name='helloworld')


    @app.route('/cities/{city}')
    def index(city):
        return {'city': city}


This indicates that the value of ``{city}`` is variable, and whatever
value is provided in the URL is passed to the ``index`` view function.
For example::

    GET /cities/seattle   --> index('seattle')
    GET /cities/portland  --> index('portland')


If you want to access any other metdata of the incoming HTTP request,
you can use the ``app.current_request`` property, which is an instance of
the the :class:`Request` class.


View Function Return Values
---------------------------

The response returned back to the client depends on the behavior
of the view function.  There are several options available:

* Returning an instance of :class:`Response`.  This gives you
  complete control over what gets returned back to the customer.
* Any other return value will be serialized as JSON and sent back
  as the response body with content type ``application/json``.
* Any subclass of ``ChaliceViewError`` will result in an HTTP
  response being returned with the status code associated with that
  response, and a JSON response body containing a ``Code`` and a ``Message``.
  This is discussed in more detail below.
* Any other exception raised will result in a 500 HTTP response.
  The body of that response depends on whether debug mode is enabled.


Error Handling
--------------

Chalice provides a built in set of exception classes that map to common
HTTP errors including:

* ``BadRequestError``- returns a status code of 400
* ``UnauthorizedError``- returns a status code of 401
* ``ForbiddenError``- returns a status code of 403
* ``NotFoundError``- returns a status code of 404
* ``ConflictError``- returns a status code of 409
* ``TooManyRequestsError``- returns a status code of 429
* ``ChaliceViewError``- returns a status code of 500

You can raise these anywhere in your view functions and chalice will convert
these to the appropriate HTTP response.  The default chalice error responses
will send the error back as ``application/json`` with the response body
containing a ``Code`` corresponding to the exception class name and a
``Message`` key corresponding to the string provided when the exception
was instantiated.  For example:

.. code-block:: python

    from chalice import Chalice
    from chalice import BadRequestError

    app = Chalice(app_name="badrequset")

    @app.route('/badrequest')
    def badrequest():
        raise BadRequestError("This is a bad request")


This view function will generate the following HTTP response::

    $ http https://endpoint/dev/badrequest
    HTTP/1.1 400 Bad Request

    {
        "Code": "BadRequestError",
        "Message": "This is a bad request"
    }


In addition to the built in chalice exceptions, you can use the
:class:`Response` class to customize the HTTP errors if you prefer to
either not have JSON error responses or customize the JSON response body
for errors.  For example:

.. code-block:: python

    from chalice import Chalice, Response

    app = Chalice(app_name="badrequest")

    @app.route('/badrequest')
    def badrequest():
        return Response(message='Plain text error message',
                        headers={'Content-Type': 'text/plain'},
                        status_code=400)


Usage Recommendations
---------------------

If you want to return a JSON response body, just return the corresponding
python types directly.  You don't need to use the :class:`Response` class.
Chalice will automatically convert this to a JSON HTTP response as a
convenience for you.

Use the :class:`Response` class when you want to return non-JSON content, or
when you want to inject custom HTTP headers to your response.

For errors, raise the built in ``ChaliceViewError`` subclasses (e.g
``BadRequestError``, ``NotFoundError``, ``ConflictError`` etc)  when you
want to return a HTTP error response with a preconfigured JSON body containing
a ``Code`` and ``Message``.

Use the :class:`Response` class when you want to customize the error responses
to either return a different JSON error response body, or to return an HTTP
response that's not ``application/json``.
