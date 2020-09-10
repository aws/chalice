==========
Middleware
==========

Chalice provides numerous features and capabilities right out of the box, but
there are often times where you'll want to customize the behavior of Chalice
for your specific needs.  You can accomplish this by using middleware, which
lets you alter the request and response lifecycle.  Chalice middleware
is a function that you register as part of your application that will
automatically be invoked by Chalice whenever your Lambda functions are called.

Below is an example of Chalice middleware:

.. code-block:: python

    from chalice import Chalice

    app = Chalice(app_name='demo-middleware')

    @app.middleware('all')
    def my_middleware(event, get_response):
        app.log.info("Before calling my main Lambda function.")
        response = get_response(event)
        app.log.info("After calling my main Lambda function.")
        return response

    @app.route('/')
    def index():
        return {'hello': 'world'}

    @app.on_sns_message('mytopic')
    def sns_handler(event):
        pass

In this example, our middleware is emitting a log message before and after
our Lambda function has been invoked.  Because we specified an event type of
``all``, the ``my_middleware`` function will be called when either our REST
API's ``index()`` or our ``sns_handler()`` Lambda function is invoked.


Writing Middleware
==================

Middleware must adhere to these requirements:

* Must be a callable object that accepts two parameters, an ``event``, and
  a ``get_response`` function.  The ``event`` type will depend on what type
  of handlers the middleware has been registered for (see "Registering
  Middleware" below).
* Must return a response.  This will be the response that gets returned back
  to the caller.
* In order to invoke the next middleware in the chain and eventually call the
  actual Lambda handler, it must invoke ``get_response(event)``.
* Middleware can short-circuit the request be returning its own response.
  It does not have to invoke ``get_response(event)`` if not needed.

Below is the simplest middleware in Chalice that does nothing:

.. code-block:: python

   @app.middleware('all')
   def noop_middleware(event, get_response):
       return get_response(event)


Registering Middleware
----------------------

In order to register middleware, you use the ``@app.middleware()`` decorator.
This function accepts a single arg that specifies what type of Lambda function
it wants to be registered for.  This allows you to apply middleware to only
specific type of event handlers, e.g. only for REST APIs, or Websockets, or
S3 event handlers.  To register middleware for all Lambda functions, you can
specify ``all``.  Below are the supported event types along with the
corresponding type of event that will be provided to the middleware:

* ``all`` - ``Any``
* ``s3`` - ``chalice.S3Event``
* ``sns`` - ``chalice.SNSEvent``
* ``sqs`` - ``chalice.SQSEvent``
* ``cloudwatch`` - ``chalice.CloudWatchEvent``
* ``scheduled`` - ``chalice.CloudWatchEvent``
* ``websocket`` - ``chalice.WebsocketEvent``
* ``http`` - ``chalice.Request``
* ``pure_lambda`` - ``chalice.LambdaFunctionEvent``


Examples
========

Below are some examples of common middleware patterns.

Short Circuiting a Request
--------------------------

In this example, we want to return a 400 bad response if a specific
header is missing from a request.  Because this is HTTP specific, we only
want to register this handler for our ``http`` event type.

.. code-block:: python

   from chalice Response

   @app.middleware('http')
   def require_header(event, get_response):
       # From the list above, because this is an ``http`` event
       # type, we know that event will be of type ``chalice.Request``.
       if 'X-Custom-Header' not in event.headers:
           return Response(
               status_code=400,
               body={"Error": "Missing required 'X-Custom-Header'"})
       # If the header exists then we'll defer to our normal request flow.
       return get_response(event)

Modifying a Response
--------------------

In this example, we want to measure the processing time and inject it as
a key in our Lambda response.

.. code-block:: python

   import time
   from chalice Response

   @app.middleware('pure_lambda')
   def inject_time(event, get_response):
       start = time.time()
       response = get_response(event)
       total = time.time() - start
       response.setdefault('metadata', {})['duration'] = total
       return response
