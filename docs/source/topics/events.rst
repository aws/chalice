====================
Lambda Event Sources
====================


Scheduled Events
================

Chalice has support for `scheduled events`_.  This feature allows you to
periodically invoke a lambda function based on some regular schedule.  You can
specify a fixed rate or a cron expression.

To create a scheduled event in chalice, you use the ``@app.schedule()``
decorator.  Let's look at an example.


.. code-block:: python

    app = chalice.Chalice(app_name='foo')

    @app.schedule('rate(1 hour)')
    def every_hour(event):
        print(event.to_dict())

    @app.route('/')
    def index():
        return {'hello': 'world'}


In this example, we've updated the starter hello world app with
a scheduled event.  When you run ``chalice deploy`` Chalice will create
two Lambda functions.  The first lambda function is for the API handler
used by API gateway.  The second lambda function will be for the scheduled
CloudWatch event (the ``every_hour`` function).   The ``every_hour`` function
will be automatically invoked every hour by Lambda.

The :meth:`Chalice.schedule` method accepts either a string or an
instance of :class:`Rate` or :class:`Cron`.  For example:

.. code-block:: python

    app = chalice.Chalice(app_name='foo')

    @app.schedule(Rate(1, unit=Rate.HOURS))
    def every_hour(event):
        print(event.to_dict())


The function you decorate must accept a single argument,
which will be of type :class:`CloudWatchEvent`.

Limitations:

* You must provide at least 1 ``@app.route`` decorator.  It is not
  possible to deploy only scheduled events without an API Gateway API.
