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
* Middleware can short-circuit the request by returning its own response.
  It does not have to invoke ``get_response(event)`` if not needed.  The
  response type should match the response type of the underlying Lambda
  handler.

Below is the simplest middleware in Chalice that does nothing:

.. code-block:: python

   @app.middleware('all')
   def noop_middleware(event, get_response):
       # The `event` type will depend on what type of
       # Lambda handler is being invoked.
       return get_response(event)


Error Handling
--------------

With the exception of middleware for REST APIs, all middleware follow the same
error handling strategy.  Any exceptions from a Lambda handler are propagated
back to each middleware.  You can then catch these exceptions in your
middleware and process them as needed.  For example:

.. code-block:: python

   @app.middleware('all')
   def handle_errors(event, get_response):
       try:
           return get_response(event)
       except MyCustomError as e:
           # We don't want MyCustomError to propagate, instead
           # we'll convert this to an error response dictionary.
           return {"Error": e.__class__.__name__,
                   "Message": str(e)}

   @app.lambda_function()
   def noop_middleware(event, context):
       raise MyCustomError("Raising an error.")


If an exception is raised in a Lambda handler and no middleware catches the
exception, the exception will be returned back to the client that invoked
the Lambda function.

Rest APIs
~~~~~~~~~

Rest APIs have special error processing for backwards compatibility purposes.
If a chalice view function (decorated via ``@app.route``) raises an exception
Chalice will automatically catch this exception and convert to a ``Response``
object with an appropriately set status code (see :ref:`view-error-handling`).
As a result, middleware for Rest APIs won't see exceptions propagate, they will
instead see a `Response` object as a result of calling ``get_response(event)``.

In the case where you want to allow an exception to propagate out of a view
function, you can raise a ``chalice.ChaliceUnhandledError`` exception.
For example:

.. code-block:: python

   from chalice import ChaliceUnhandledError

   @app.middleware('all')
   def handle_errors(event, get_response):
       try:
           return get_response(event)
       except ChaliceUnhandledError as e:
           return Response(status_code=500, body=str(e),
                           headers={'Content-Type': 'text/plain'})

   @app.route('/')
   def index():
       # The handle_errors middleware will never see this exception.
       # This will automatically be converted to a ``Response`` object
       # with a status code of ``500``.
       raise MyCustomError("Raising an error.")

   @app.route('/error')
   def unhandled_error():
       # The handle_errors middleware will see this exception because it's
       # of type ChaliceUnhandledError.
       raise ChaliceUnhandledError("Raising an error.")


This is useful if you want to have middleware that applies to all event types
that has consistent error handling behavior.  If a
``chalice.ChaliceUnhandledError`` error is raised and no middleware catches
and processes this error, then the standard error processing behavior will
apply (a 500 response is returned back to the user, and if debug mode
is enabled, the traceback is sent as the response body).


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
* ``s3`` - :class:`S3Event`
* ``sns`` - :class:`SNSEvent`
* ``sqs`` - :class:`SQSEvent`
* ``cloudwatch`` - :class:`CloudWatchEvent`
* ``scheduled`` - :class:`CloudWatchEvent`
* ``websocket`` - :class:`WebsocketEvent`
* ``http`` - :class:`Request`
* ``pure_lambda`` - :class:`LambdaFunctionEvent`

.. note::
   The ``chalice.LambdaFunctionEvent`` is the only case where the
   event type for the middleware does not match the event type of the
   corresponding Lambda handler.  For backwards compatibility reasons,
   the existing signature of the ``@app.lambda_function()`` decorator
   is preserved (it accepts an ``event`` and ``context``) whereas for
   middleware, a consistent signature is needed, which is why the
   ``chalice.LambdaFunctionEvent`` is used.

You can also use the :meth:`Chalice.register_middleware` method, which
has the same behavior as :meth:`Chalice.middleware` except you provide
the middleware function as an argument instead of decorating a function.
This is useful when you want to import third party functions and use
them as middleware.

.. code-block:: python

    import thirdparty

    app.register_middleware(thirdparty.func, 'all')

You can also use the :class:`ConvertToMiddleware` class to convert an
existing Lambda wrapper to middleware.  For example, if you had the
following logging decorator:

.. code-block:: python

    def log_invocation(func):
        def wrapper(event, context):
            logger.debug("Before lambda function.")
            response = func(event, context)
            logger.debug("After lambda function.")
        return wrapper

    @app.lambda_function()
    @log_invocation
    def myfunction(event, context):
        logger.debug("In myfunction().")


Rather than decorate every Lambda function with the ``@log_invocation``
decorator, you can instead use ``ConvertToMiddleware`` to automatically
apply this wrapper to every Lambda function in your app.

.. code-block:: python

    from chalice import ConvertToMiddleware

    app.register_middleware(ConvertToMiddleware(log_invoation))

This is also useful to integrate with existing libraries that provide
Lambda wrappers.  See :ref:`powertools-example` for a more complete
example.

Examples
========

Below are some examples of common middleware patterns.

Short Circuiting a Request
--------------------------

In this example, we want to return a 400 bad response if a specific
header is missing from a request.  Because this is HTTP specific, we only
want to register this handler for our ``http`` event type.

.. code-block:: python

   from chalice import Response

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

   @app.middleware('pure_lambda')
   def inject_time(event, get_response):
       start = time.time()
       response = get_response(event)
       total = time.time() - start
       response.setdefault('metadata', {})['duration'] = total
       return response


.. _powertools-example:

Integrating with AWS Lambda Powertools
--------------------------------------

`AWS Lambda Powertools
<https://docs.powertools.aws.dev/lambda/python/latest/>`__ is a suite of
utilities for AWS Lambda functions that makes tracing with AWS X-Ray,
structured logging and creating custom metrics asynchronously easier.

You can use Chalice middleware to easily integrate Lambda Powertools with
your Chalice apps.  In this example, we'll use the
`Logger
<https://docs.powertools.aws.dev/lambda/python/latest/core/logger/>`__
and `Tracer <https://docs.powertools.aws.dev/lambda/python/latest/core/tracer/>`__
and convert them to Chalice middleware so they will be automatically applied
to all Lambda functions in our application.


.. code-block:: python

    from chalice import Chalice
    from chalice.app import ConvertToMiddleware

    # First, instead of using Chalice's built in logger, we'll instead use
    # the structured logger from powertools.  In addition to automatically
    # injecting lambda context, let's say we also want to inject which
    # route is being invoked.
    from aws_lambda_powertools import Logger
    from aws_lambda_powertools import Tracer

    app = Chalice(app_name='chalice-powertools')


    logger = Logger(service=app.app_name)
    tracer = Tracer(service=app.app_name)
    # This will automatically convert any decorator on a lambda function
    # into middleware that will be connected to every lambda function
    # in our app.  This lets us avoid decoratoring every lambda function
    # with this behavior, but it also works in cases where we don't control
    # the code (e.g. registering blueprints).
    app.register_middleware(ConvertToMiddleware(logger.inject_lambda_context))
    app.register_middleware(
        ConvertToMiddleware(
            tracer.capture_lambda_handler(capture_response=False))
    )

    # Here we're writing Chalice specific middleware where for any HTTP
    # APIs, we want to add the request path to our structured log message.
    # This shows how we can combine both Chalice-style middleware with
    # other existing tools.
    @app.middleware('http')
    def inject_route_info(event, get_response):
        logger.structure_logs(append=True, request_path=event.path)
        return get_response(event)


    @app.route('/')
    def index():
        logger.info("In index() function, this will have a 'path' key.")
        return {'hello': 'world'}

    @app.route('/foo/bar')
    def foobar():
        logger.info("In foobar() function")
        return {'foo': 'bar'}


    @app.lambda_function()
    def myfunction(event, context):
        logger.info("In myfunction().")
        tracer.put_annotation(key="Status", value="SUCCESS")
        return {}


For a more detailed walkthrough of configuring Chalice with Lambda Powertools,
see
`Following serverless best practices with AWS Chalice and Lambda Powertools <https://aws.amazon.com/blogs/developer/following-serverless-best-practices-with-aws-chalice-and-lambda-powertools/>`__.
