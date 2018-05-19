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


In this example, we have a single lambda function that we want automatically
invoked every hour.  When you run ``chalice deploy`` Chalice will create a
lambda function as well as the necessary CloudWatch events/rules such that the
``every_hour`` function is invoked every hour.

The :meth:`Chalice.schedule` method accepts either a string or an
instance of :class:`Rate` or :class:`Cron`.  For example:

.. code-block:: python

    app = chalice.Chalice(app_name='foo')

    @app.schedule(Rate(1, unit=Rate.HOURS))
    def every_hour(event):
        print(event.to_dict())


The function you decorate must accept a single argument,
which will be of type :class:`CloudWatchEvent`.

You can use the ``schedule()`` decorator multiple times
in your chalice app.  Each ``schedule()`` decorator will
result in a new lambda function and associated CloudWatch
event rule.  For example:


.. code-block:: python

    app = chalice.Chalice(app_name='foo')

    @app.schedule(Rate(1, unit=Rate.HOURS))
    def every_hour(event):
        print(event.to_dict())


    @app.schedule(Rate(2, unit=Rate.HOURS))
    def every_two_hours(event):
        print(event.to_dict())


In the app above, chalice will create two lambda functions,
and configure ``every_hour`` to be invoked once an hour,
and ``every_two_hours`` to be invoked once every two hours.
