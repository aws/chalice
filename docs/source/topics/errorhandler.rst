=====================
Custom Error Handling
=====================

While chalice middleware allow for catching of user defined errors, exceptions
raised by a third party library can't be seen by the middleware and chalice
will set the response without giving the middleware a chance to see the
exception. These error handlers will only by used in the case of 'http' event,
as the middleware for other types of events can catch other exceptions
(see :ref:`middleware-error-handling-rest`).

In the case where you want to return your own ``Response`` for those exceptions
you can register an error handler to intercept the exception.

Below is an example of Chalice error hanler:

.. code-block:: python

    from chalice import Chalice, Response
    from thirdparty import func, ThirdPartyError

    app = Chalice(app_name='demo-errorhandler')

    @app.error(ThirdPartyError)
    def my_error_handler(error: Exception):
        app.log.error("ThirdPartyError was raised")
        return Response(
            body=e.__class__.__name__,
            status_code=500
        )

    @app.route('/')
    def index():
        return func()

In this example, our error handler is registered to catch ``ThirdPartyError``
raised in a http event. In this case, if `func` were to raise a
``ThirdPartyError``, ``my_error_handler`` will be called and our custom
``Response`` will be returned.

Writing Error Handlers
======================

Error handlers must adhere to these requirements:

* Must be a callable object that accepts one parameter. It will be of
  ``Exception`` type.
* Must return a response. If the response is not of ``chalice.Response`` type,
  Chalice will either try to call the next error handler registered for the
  same error or in the event where no handlers return a valid response, Chalice
  will return a ``chalice.ChaliceViewError``.


Error Propagation
-----------------

Cahlice will propagatet the error through all registered handlers until a valid
response is returned. If no handlers return a valid response, chalice will
handle the error as if no handlers were registered.

.. code-block:: python

    @app.error(ThirdPartyError)
    def my_error_handler_1(error: Exception):
        if error.message == '1':
            return Response(
                body='Error 1 was raised',
                status_code=200
            )

    @app.error(ThirdPartyError)
    def my_error_handler_2(error: Exception):
        if error.message == '2':
            return Response(
                body='Error 2 was raised',
                status_code=400
            )

    @app.route('/1')
    def index():
        # The response from `my_error_handler_1` will be returned
        raise ThirdPartyError('1')

    @app.route('/2')
    def index():
        # The response from `my_error_handler_2` will be returned
        raise ThirdPartyError('2')

    @app.route('/3')
    def index():
        # A ChaliceViewError will be returned
        raise ThirdPartyError('3')
