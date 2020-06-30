REST API Tutorial
=================

In this tutorial, we're going to create a REST API and explore what features
Chalice provides that helps us write this REST APIs.

Installation and Configuration
------------------------------

If you haven't already setup and configured Chalice, see the
:doc:`../quickstart` for a step by step guide.  In a nutshell, you can get a
basic Chalice app created with::

    $ python3 --version
    Python 3.7.3
    $ python3 -m venv venv37
    $ . venv37/bin/activate
    $ python3 -m pip install chalice
    $ chalice new-project helloworld
    $ cd helloworld


URL Parameters
--------------

The default template when you run the ``new-project`` generates a sample
REST API for you:

.. code-block:: python

    from chalice import Chalice

    app = Chalice(app_name='helloworld')


    @app.route('/')
    def index():
        return {'hello': 'world'}

We're going to make a few changes to our ``app.py`` file that
demonstrate the capabilities provided by Chalice.

Our application so far has a single view that allows you to make
an HTTP GET request to ``/``.  Now let's suppose we want to capture
parts of the URI:

.. code-block:: python

    from chalice import Chalice

    app = Chalice(app_name='helloworld')

    CITIES_TO_STATE = {
        'seattle': 'WA',
        'portland': 'OR',
    }


    @app.route('/')
    def index():
        return {'hello': 'world'}

    @app.route('/cities/{city}')
    def state_of_city(city):
        return {'state': CITIES_TO_STATE[city]}


In the example above, we've now added a ``state_of_city`` view that allows
a user to specify a city name.  The view function takes the city
name and returns name of the state the city is in.  Notice that the
``@app.route`` decorator has a URL pattern of ``/cities/{city}``.  This
means that the value of ``{city}`` is captured and passed to the view
function.  You can also see that the ``state_of_city`` takes a single
argument.  This argument is the name of the city provided by the user.
For example::

    GET /cities/seattle   --> state_of_city('seattle')
    GET /cities/portland  --> state_of_city('portland')

Now that we've updated our ``app.py`` file with this new view function,
let's redeploy our application.  You can run ``chalice deploy`` from
the ``helloworld`` directory and it will deploy your application::

    $ chalice deploy

Let's try it out.  Note the examples below use the ``http`` command from the
``httpie`` package.  You can install this using ``pip install httpie``::

    $ http https://endpoint/api/cities/seattle
    HTTP/1.1 200 OK

    {
        "state": "WA"
    }

    $ http https://endpoint/api/cities/portland
    HTTP/1.1 200 OK

    {
        "state": "OR"
    }


Notice what happens if we try to request a city that's not in our
``CITIES_TO_STATE`` map::

    $ http https://endpoint/api/cities/vancouver
    HTTP/1.1 500 Internal Server Error
    Content-Type: application/json
    X-Cache: Error from cloudfront

    {
        "Code": "ChaliceViewError",
        "Message": "ChaliceViewError: An internal server error occurred."
    }


In the next section, we'll see how to fix this and provide better
error messages.


Error Messages
--------------

In the example above, you'll notice that when our app raised
an uncaught exception, a 500 internal server error was returned.

In this section, we're going to show how you can debug and improve
these error messages.

The first thing we're going to look at is how we can debug this
issue.  By default, debugging is turned off, but you can
enable debugging to get more information:

.. code-block:: python

    from chalice import Chalice

    app = Chalice(app_name='helloworld')
    app.debug = True


The ``app.debug = True`` enables debugging for your app.
Save this file and redeploy your changes::

    $ chalice deploy
    ...
    https://endpoint/api/

Now, when you request the same URL that returned an internal
server error, you'll get back the original stack trace::

    $ http https://endpoint/api/cities/vancouver
    Traceback (most recent call last):
      File "/var/task/chalice/app.py", line 304, in _get_view_function_response
        response = view_function(*function_args)
      File "/var/task/app.py", line 18, in state_of_city
        return {'state': CITIES_TO_STATE[city]}
    KeyError: u'vancouver'


We can see that the error is caused from an uncaught ``KeyError`` resulting
from trying to access the ``vancouver`` key.

Now that we know the error, we can fix our code.  What we'd like to do is
catch this exception and instead return a more helpful error message
to the user.  Here's the updated code:

.. code-block:: python

    from chalice import BadRequestError

    @app.route('/cities/{city}')
    def state_of_city(city):
        try:
            return {'state': CITIES_TO_STATE[city]}
        except KeyError:
            raise BadRequestError("Unknown city '%s', valid choices are: %s" % (
                city, ', '.join(CITIES_TO_STATE.keys())))


Save and deploy these changes::

    $ chalice deploy
    $ http https://endpoint/api/cities/vancouver
    HTTP/1.1 400 Bad Request

    {
        "Code": "BadRequestError",
        "Message": "Unknown city 'vancouver', valid choices are: portland, seattle"
    }

We can see now that we have received a ``Code`` and ``Message`` key, with the
message being the value we passed to ``BadRequestError``.  Whenever you raise a
``BadRequestError`` from your view function, the framework will return an HTTP
status code of 400 along with a JSON body with a ``Code`` and ``Message``.
There are a few additional exceptions you can raise from your python code::

* BadRequestError - return a status code of 400
* UnauthorizedError - return a status code of 401
* ForbiddenError - return a status code of 403
* NotFoundError - return a status code of 404
* ConflictError - return a status code of 409
* UnprocessableEntityError - return a status code of 422
* TooManyRequestsError - return a status code of 429
* ChaliceViewError - return a status code of 500

You can import these directly from the ``chalice`` package:

.. code-block:: python

    from chalice import UnauthorizedError


Additional Routing
------------------

So far, our examples have only allowed GET requests.
It's actually possible to support additional HTTP methods.
Here's an example of a view function that supports PUT:

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
PUT is sent to ``/myview``.

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
view function. It is also important to note that the view functions
**must** have unique names. For example, both view functions cannot be
named ``myview()``.

In the next section we'll go over how you can introspect the given request
in order to differentiate between various HTTP methods.


Request Metadata
----------------

In the examples above, you saw how to create a view function that supports
an HTTP PUT request as well as a view function that supports both POST and
PUT via the same view function.  However, there's more information we
might need about a given request:

* In a PUT/POST, you frequently send a request body.  We need some
  way of accessing the contents of the request body.
* For view functions that support multiple HTTP methods, we'd like
  to detect which HTTP method was used so we can have different
  code paths for PUTs vs. POSTs.

All of this and more is handled by the current request object that the
``chalice`` library makes available to each view function when it's called.

Let's see an example of this.  Suppose we want to create a view function
that allowed you to PUT data to an object and retrieve that data
via a corresponding GET.  We could accomplish that with the
following view function:

.. code-block:: python

    from chalice import NotFoundError

    OBJECTS = {
    }

    @app.route('/objects/{key}', methods=['GET', 'PUT'])
    def myobject(key):
        request = app.current_request
        if request.method == 'PUT':
            OBJECTS[key] = request.json_body
        elif request.method == 'GET':
            try:
                return {key: OBJECTS[key]}
            except KeyError:
                raise NotFoundError(key)


Save this in your ``app.py`` file and rerun ``chalice deploy``.
Now, you can make a PUT request to ``/objects/your-key`` with a request
body, and retrieve the value of that body by making a subsequent
``GET`` request to the same resource.  Here's an example of its usage::

    # First, trying to retrieve the key will return a 404.
    $ http GET https://endpoint/api/objects/mykey
    HTTP/1.1 404 Not Found

    {
        "Code": "NotFoundError",
        "Message": "mykey"
    }

    # Next, we'll create that key by sending a PUT request.
    $ echo '{"foo": "bar"}' | http PUT https://endpoint/api/objects/mykey
    HTTP/1.1 200 OK

    null

    # And now we no longer get a 404, we instead get the value we previously
    # put.
    $ http GET https://endpoint/api/objects/mykey
    HTTP/1.1 200 OK

    {
        "mykey": {
            "foo": "bar"
        }
    }

You might see a problem with storing the objects in a module level
``OBJECTS`` variable.  We address this in the next section.

The ``app.current_request`` object is an instance of the :class:`Request`
class, which also has the following properties.

* ``current_request.query_params`` - A dict of the query params.
* ``current_request.headers`` - A dict of the request headers.
* ``current_request.uri_params`` - A dict of the captured URI params.
* ``current_request.method`` -  The HTTP method (as a string).
* ``current_request.json_body`` - The parsed JSON body.
* ``current_request.raw_body`` - The raw HTTP body as bytes.
* ``current_request.context`` - A dict of additional context information
* ``current_request.stage_vars`` - Configuration for the API Gateway stage

The ``current_request`` object also has a ``to_dict`` method, which returns all
the information about the current request as a dictionary.  Let's use this
method to write a view function that returns everything it knows about the
request:

.. code-block:: python

    @app.route('/introspect')
    def introspect():
        return app.current_request.to_dict()


Save this to your ``app.py`` file and redeploy with ``chalice deploy``.
Here's an example of hitting the ``/introspect`` URL.  Note how we're
sending a query string as well as a custom ``X-TestHeader`` header::


    $ http 'https://endpoint/api/introspect?query1=value1&query2=value2' 'X-TestHeader: Foo'
    HTTP/1.1 200 OK

    {
        "context": {
            "apiId": "apiId",
            "httpMethod": "GET",
            "identity": {
                "accessKey": null,
                "accountId": null,
                "apiKey": null,
                "caller": null,
                "cognitoAuthenticationProvider": null,
                "cognitoAuthenticationType": null,
                "cognitoIdentityId": null,
                "cognitoIdentityPoolId": null,
                "sourceIp": "1.1.1.1",
                "userAgent": "HTTPie/0.9.3",
                "userArn": null
            },
            "requestId": "request-id",
            "resourceId": "resourceId",
            "resourcePath": "/introspect",
            "stage": "dev"
        },
        "headers": {
            "accept": "*/*",
            ...
            "x-testheader": "Foo"
        },
        "method": "GET",
        "query_params": {
            "query1": "value1",
            "query2": "value2"
        },
        "raw_body": null,
        "stage_vars": null,
        "uri_params": null
    }


Request Content Types
---------------------

The default behavior of a view function supports
a request body of ``application/json``.  When a request is
made with a ``Content-Type`` of ``application/json``, the
``app.current_request.json_body`` attribute is automatically
set for you.  This value is the parsed JSON body.

You can also configure a view function to support other
content types.  You can do this by specifying the
``content_types`` parameter value to your ``app.route``
function.  This parameter is a list of acceptable content
types.  Here's an example of this feature:

.. code-block:: python

    import sys

    from chalice import Chalice
    from urllib.parse import urlparse, parse_qs

    app = Chalice(app_name='helloworld')


    @app.route('/', methods=['POST'],
               content_types=['application/x-www-form-urlencoded'])
    def index():
        parsed = parse_qs(app.current_request.raw_body.decode())
        return {
            'states': parsed.get('states', [])
        }

There's a few things worth noting in this view function.
First, we've specified that we only accept the
``application/x-www-form-urlencoded`` content type.  If we
try to send a request with ``application/json``, we'll now
get a ``415 Unsupported Media Type`` response::

    $ http POST https://endpoint/api/ states=WA states=CA --debug
    ...
    >>> requests.request(**{'allow_redirects': False,
     'headers': {'Accept': 'application/json',
                 'Content-Type': 'application/json',
    ...


    HTTP/1.1 415 Unsupported Media Type

    {
        "message": "Unsupported Media Type"
    }

If we use the ``--form`` argument, we can see the
expected behavior of this view function because ``httpie`` sets the
``Content-Type`` header to ``application/x-www-form-urlencoded``::

    $ http --form POST https://endpoint/api/formtest states=WA states=CA --debug
    ...
    >>> requests.request(**{'allow_redirects': False,
     'headers': {'Content-Type': 'application/x-www-form-urlencoded; charset=utf-8',
    ...

    HTTP/1.1 200 OK
    {
        "states": [
            "WA",
            "CA"
        ]
    }

The second thing worth noting is that ``app.current_request.json_body``
**is only available for the application/json content type.**
In our example above, we used ``app.current_request.raw_body`` to access
the raw body bytes:

.. code-block:: python

    parsed = parse_qs(app.current_request.raw_body)

``app.current_request.json_body`` is set to ``None`` whenever the
``Content-Type`` is not ``application/json``.  This means that
you will need to use ``app.current_request.raw_body`` and parse
the request body as needed.


Customizing the HTTP Response
-----------------------------

The return value from a chalice view function is serialized as JSON as the
response body returned back to the caller.  This makes it easy to create
rest APIs that return JSON response bodies.

Chalice allows you to control this behavior by returning an instance of
a chalice specific ``Response`` class.  This behavior allows you to:

* Specify the status code to return
* Specify custom headers to add to the response
* Specify response bodies that are not ``application/json``

Here's an example of this:

.. code-block:: python

    from chalice import Chalice, Response

    app = Chalice(app_name='custom-response')


    @app.route('/')
    def index():
        return Response(body='hello world!',
                        status_code=200,
                        headers={'Content-Type': 'text/plain'})

This will result in a plain text response body::

    $ http https://endpoint/api/
    HTTP/1.1 200 OK
    Content-Length: 12
    Content-Type: text/plain

    hello world!


GZIP compression for JSON
-------------------------

The return value from a chalice view function is serialized as JSON as the
response body returned back to the caller.  This makes it easy to create
rest APIs that return JSON response bodies.

Chalice allows you to control this behavior by returning an instance of
a chalice specific ``Response`` class.  This behavior allows you to:

* Add ``application/json`` to binary_types
* Specify the status code to return
* Specify custom header ``Content-Type: application/json``
* Specify custom header ``Content-Encoding: gzip``

Here's an example of this:

.. code-block:: python

    import json
    import gzip
    from chalice import Chalice, Response

    app = Chalice(app_name='compress-response')
    app.api.binary_types.append('application/json')

    @app.route('/')
    def index():
        blob = json.dumps({'hello': 'world'}).encode('utf-8')
        payload = gzip.compress(blob)
        custom_headers = {
            'Content-Type': 'application/json',
            'Content-Encoding': 'gzip'
        }
        return Response(body=payload,
                        status_code=200,
                        headers=custom_headers)



CORS Support
------------

You can specify whether a view supports CORS by adding the
``cors=True`` parameter to your ``@app.route()`` call.  By
default this value is ``False``. Global CORS can be set by
setting ``app.api.cors = True``.

.. code-block:: python

    @app.route('/supports-cors', methods=['PUT'], cors=True)
    def supports_cors():
        return {}


Setting ``cors=True`` has similar behavior to enabling CORS
using the AWS Console.  This includes:

* Injecting the ``Access-Control-Allow-Origin: *`` header to your
  responses, including all error responses you can return.
* Automatically adding an ``OPTIONS`` method to support preflighting
  requests.

The preflight request will return a response that includes:

* ``Access-Control-Allow-Origin: *``
* The ``Access-Control-Allow-Methods`` header will return a list of all HTTP
  methods you've called out in your view function.  In the example above,
  this will be ``PUT,OPTIONS``.
* ``Access-Control-Allow-Headers: Content-Type,X-Amz-Date,Authorization,
  X-Api-Key,X-Amz-Security-Token``.

If more fine grained control of the CORS headers is desired, set the ``cors``
parameter to an instance of ``CORSConfig`` instead of ``True``. The
``CORSConfig`` object can be imported from from the ``chalice`` package it's
constructor takes the following keyword arguments that map to CORS headers:

================= ==== ================================
Argument          Type Header
================= ==== ================================
allow_origin      str  Access-Control-Allow-Origin
allow_headers     list Access-Control-Allow-Headers
expose_headers    list Access-Control-Expose-Headers
max_age           int  Access-Control-Max-Age
allow_credentials bool Access-Control-Allow-Credentials
================= ==== ================================

Code sample defining more CORS headers:

.. code-block:: python

    from chalice import CORSConfig
    cors_config = CORSConfig(
        allow_origin='https://foo.example.com',
        allow_headers=['X-Special-Header'],
        max_age=600,
        expose_headers=['X-Special-Header'],
        allow_credentials=True
    )
    @app.route('/custom-cors', methods=['GET'], cors=cors_config)
    def supports_custom_cors():
        return {'cors': True}


There's a couple of things to keep in mind when enabling cors for a view:

* An ``OPTIONS`` method for preflighting is always injected.  Ensure that
  you don't have ``OPTIONS`` in the ``methods=[...]`` list of your
  view function.
* Even though the ``Access-Control-Allow-Origin`` header can be set to a
  string that is a space separated list of origins, this behavior does not
  work on all clients that implement CORS. You should only supply a single
  origin to the ``CORSConfig`` object. If you need to supply multiple origins
  you will need to define a custom handler for it that accepts ``OPTIONS``
  requests and matches the ``Origin`` header against a whitelist of origins.
  If the match is successful then return just their ``Origin`` back to them
  in the ``Access-Control-Allow-Origin`` header.

  Example:

.. code-block:: python

    from chalice import Chalice, Response

    app = Chalice(app_name='multipleorigincors')

    _ALLOWED_ORIGINS = set([
        'http://allowed1.example.com',
        'http://allowed2.example.com',
    ])

    @app.route('/cors_multiple_origins', methods=['GET', 'OPTIONS'])
    def supports_cors_multiple_origins():
        method = app.current_request.method
        if method == 'OPTIONS':
            headers = {
                'Access-Control-Allow-Method': 'GET,OPTIONS',
                'Access-Control-Allow-Origin': ','.join(_ALLOWED_ORIGINS),
                'Access-Control-Allow-Headers': 'X-Some-Header',
            }
            origin = app.current_request.headers.get('origin', '')
            if origin in _ALLOWED_ORIGINS:
                headers.update({'Access-Control-Allow-Origin': origin})
            return Response(
                body=None,
                headers=headers,
            )
        elif method == 'GET':
            return 'Foo'
