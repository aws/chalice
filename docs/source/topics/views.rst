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


If you want to access any other metadata of the incoming HTTP request,
you can use the ``app.current_request`` property, which is an instance of
the the :class:`Request` class.


View Function Return Values
---------------------------

The response returned back to the client depends on the behavior
of the view function.  There are several options available:

* Returning an instance of :class:`Response`.  This gives you
  complete control over what gets returned back to the customer.
* A ``bytes`` type response body must have a ``Content-Type`` header value
  that is present in the ``app.api.binary_types`` list in order to be handled
  properly.
* Any other return value will be serialized as JSON and sent back
  as the response body with content type ``application/json``.
* Any subclass of ``ChaliceViewError`` will result in an HTTP
  response being returned with the status code associated with that
  response, and a JSON response body containing a ``Code`` and a ``Message``.
  This is discussed in more detail below.
* Any other exception raised will result in a 500 HTTP response.
  The body of that response depends on whether debug mode is enabled.


.. _view-error-handling:

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

    app = Chalice(app_name="badrequest")

    @app.route('/badrequest')
    def badrequest():
        raise BadRequestError("This is a bad request")


This view function will generate the following HTTP response::

    $ http https://endpoint/api/badrequest
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
        return Response(body='Plain text error message',
                        headers={'Content-Type': 'text/plain'},
                        status_code=400)



Specifying HTTP Methods
-----------------------

So far, our examples have only allowed GET requests. It's actually possible
to support additional HTTP methods. Here's an example of a view function that
supports PUT:

.. code-block:: python

    @app.route('/resource/{value}', methods=['PUT'])
    def put_test(value):
        return {"value": value}

We can test this method using the ``http`` command::

    $ http PUT https://endpoint/api/resource/foo
    HTTP/1.1 200 OK

    {
        "value": "foo"
    }

Note that the ``methods`` kwarg accepts a list of methods.  Your view function
will be called when any of the HTTP methods you specify are used for the
specified resource.  For example:

.. code-block:: python

    @app.route('/myview', methods=['POST', 'PUT'])
    def myview():
        pass

The above view function will be called when either an HTTP POST or
PUT is sent to ``/myview`` as shown below::

    POST /myview   --> myview()
    PUT /myview  --> myview()

Alternatively if you do not want to share the same view function across
multiple HTTP methods for the same route url, you may define separate view
functions to the same route url but have the view functions differ by
HTTP method. For example:

.. code-block:: python

    @app.route('/myview', methods=['POST'])
    def myview_post():
        pass

    @app.route('/myview', methods=['PUT'])
    def myview_put():
        pass

This setup will route all HTTP POST's to ``/myview`` to the ``myview_post()``
view function and route all HTTP PUT's to ``/myview`` to the ``myview_put()``
view function as shown below::

    POST /myview   --> myview_post()
    PUT /myview  --> myview_put()

If you do chose to use separate view functions for the same route path, it is
important to know:

* View functions that share the same route cannot have the same names.
  For example, two view functions that both share the same route path cannot
  both be named ``view()``.

* View functions that share the same route cannot overlap in supported HTTP
  methods. For example if two view functions both share the same route path,
  they both cannot contain ``'PUT'`` in their route ``methods`` list.

* View functions that share the same route path and have CORS configured cannot
  have differing CORS configuration. For example, if two view functions that
  both share the same route path, the route configuration for one of the
  view functions cannot set ``cors=True`` while having the route
  configuration of the other view function be set to
  ``cors=app.CORSConfig(allow_origin='https://foo.example.com')``.


Binary Content
--------------

Chalice supports binary payloads through its ``app.api.binary_types`` list. Any
type in this list is considered a binary ``Content-Type``. Whenever a request
with a ``Content-Type`` header is encountered that matches an entry in the
``binary_types`` list, its body will be available as a ``bytes`` type on the
property ``app.current_request.raw_body``. Similarly, in order to send binary
data back in a response, simply set your ``Content-Type`` header to something
present in the ``binary_types`` list. Note that you can override the default
types by modifying the ``app.api.binary_types`` list at the module level.

Here is an example app which simply echoes back binary content:

.. code-block:: python

   from chalice import Chalice, Response

   app = Chalice(app_name="binary-response")

   @app.route('/bin-echo', methods=['POST'],
              content_types=['application/octet-stream'])
   def bin_echo():
       raw_request_body = app.current_request.raw_body
       return Response(body=raw_request_body,
                       status_code=200,
                       headers={'Content-Type': 'application/octet-stream'})

You can see this app echo back binary data sent to it::

  $ echo -n -e "\xFE\xED" | http POST $(chalice url)bin-echo \
    Accept:application/octet-stream Content-Type:application/octet-stream | xxd
  0000000: feed                                     ..

Note that both the ``Accept`` and ``Content-Type`` headers are required. If
you fail to set the ``Content-Type`` header on the request will result in a
``415 UnsupportedMediaType`` error. Care must be taken when configuring what
``content_types`` a route accepts, they must all be valid binary types, or they
must all be non-binary types. The ``Accept`` header must also be set if the
data returned is to be the raw binary, if is omitted the call return a ``400``
Bad Request response.

For example, here is the same call as above without the ``Accept`` header::

  $ echo -n -e "\xFE\xED" | http POST  $(chalice url)bin-echo \
    Content-Type:application/octet-stream
  HTTP/1.1 400 Bad Request
  Connection: keep-alive
  Content-Length: 270
  Content-Type: application/json
  Date: Sat, 27 May 2017 07:09:51 GMT

  {
    "Code": "BadRequest",
    "Message": "Request did not specify an Accept header with
      application/octet-stream, The response has a Content-Type of
      application/octet-stream. If a response has a binary Content-Type then
      the request must specify an Accept header that matches."
  }



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
