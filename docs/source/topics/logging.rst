Logging
=======

You have several options for logging in your
application.  You can use any of the options
available to lambda functions as outlined
in the
`AWS Lambda Docs <http://docs.aws.amazon.com/lambda/latest/dg/python-logging.html>`_.
The simplest option is to just use print statements.
Anything you print will be accessible in cloudwatch logs
as well as in the output of the ``chalice logs`` command.

In addition to using the stdlib ``logging`` module directly,
the framework offers a preconfigured logger designed to work
nicely with Lambda.  This is offered purely as a convenience,
you can use ``print`` or the ``logging`` module directly if you prefer.

You can access this logger via the ``app.log``
attribute, which is a a logger specifically for your application.
This attribute is an instance of ``logging.getLogger(your_app_name_)``
that's been preconfigured with reasonable defaults:

* StreamHandler associated with ``sys.stdout``.
* Log level set to ``logging.ERROR`` by default.
  You can also manually set the logging level by setting
  ``app.log.setLevel(logging.DEBUG)``.
* A logging formatter that displays the app name, level name,
  and message.


Examples
--------

In the following application, we're using the application logger
to emit two log messages, one at ``DEBUG`` and one at the ``ERROR``
level:

.. code-block:: python

    from chalice import Chalice

    app = Chalice(app_name='demolog')


    @app.route('/')
    def index():
        app.log.debug("This is a debug statement")
        app.log.error("This is an error statement")
        return {'hello': 'world'}


If we make a request to this endpoint, and then look at
``chalice logs`` we'll see the following log message::

    2016-11-06 20:24:25.490000 9d2a92 demolog - ERROR - This is an error statement

As you can see, only the ``ERROR`` level log is emitted because
the default log level is ``ERROR``.  Also note the log message formatting.
This is the default format that's been automatically configured.
We can make a change to set our log level to debug:


.. code-block:: python

    from chalice import Chalice

    app = Chalice(app_name='demolog')
    # Enable DEBUG logs.
    app.log.setLevel(logging.DEBUG)


    @app.route('/')
    def index():
        app.log.debug("This is a debug statement")
        app.log.error("This is an error statement")
        return {'hello': 'world'}

Now if we make a request to the ``/`` URL and look at the
output of ``chalice logs``, we'll see the following log message::

    2016-11-07 12:29:15.714 431786 demolog - DEBUG - This is a debug statement
    2016-11-07 12:29:15.714 431786 demolog - ERROR - This is an error statement


As you can see here, both the debug and error log message are shown.
