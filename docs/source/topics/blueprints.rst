Blueprints
==========


.. warning::

  Blueprints are considered an experimental API.  You'll need to opt-in
  to this feature using the ``BLUEPRINTS`` feature flag:

  .. code-block:: python

    app = Chalice('myapp')
    app.experimental_feature_flags.update([
        'BLUEPRINTS'
    ])

  See :doc:`experimental` for more information.


Chalice blueprints are used to organize your application into logical
components.  Using a blueprint, you define your resources and decorators in
modules outside of your ``app.py``.  You then register a blueprint in your main
``app.py`` file.  Blueprints support any decorator available on an application
object.


.. note::

  The Chalice blueprints are conceptually similar to `Blueprints
  <https://flask.palletsprojects.com/blueprints/>`__ in Flask.  Flask
  blueprints allow you to define a set of URL routes separately from the main
  ``Flask`` object.  This concept is extended to all resources in Chalice.  A
  Chalice blueprint can have Lambda functions, event handlers, built-in
  authorizers, etc. in addition to a collection of routes.


Example
-------

In this example, we'll create a blueprint with part of our routes defined in a
separate file.  First, let's create an application::

    $ chalice new-project blueprint-demo
    $ cd blueprint-demo
    $ mkdir chalicelib
    $ touch chalicelib/__init__.py
    $ touch chalicelib/blueprints.py

Next, we'll open the ``chalicelib/blueprints.py`` file:

.. code-block:: python

    from chalice import Blueprint


    extra_routes = Blueprint(__name__)


    @extra_routes.route('/foo')
    def foo():
        return {'foo': 'bar'}


The ``__name__`` is used to denote the import path of the blueprint.  This name
must match the import name of the module so the function can be properly
imported when running in Lambda.  We'll now import this module in our
``app.py`` and register this blueprint.  We'll also add a route in our
``app.py`` directly:

.. code-block:: python

    from chalice import Chalice
    from chalicelib.blueprints import extra_routes

    app = Chalice(app_name='blueprint-demo')
    app.experimental_feature_flags.update([
        'BLUEPRINTS'
    ])
    app.register_blueprint(extra_routes)


    @app.route('/')
    def index():
        return {'hello': 'world'}

At this point, we've defined two routes.  One route, ``/``, is directly defined
in our ``app.py`` file.  The other route, ``/foo`` is defined in
``chalicelib/blueprints.py``.  It was added to our Chalice app when we
registered it via ``app.register_blueprint(extra_routes)``.

We can deploy our application to verify this works as expected::

    $ chalice deploy
    Creating deployment package.
    Creating IAM role: blueprint-demo-dev
    Creating lambda function: blueprint-demo-dev
    Creating Rest API
    Resources deployed:
      - Lambda ARN: arn:aws:lambda:us-west-2:1234:function:blueprint-demo-dev
      - Rest API URL: https://rest-api.execute-api.us-west-2.amazonaws.com/api/


We should now be able to request the ``/`` and ``/foo`` routes::

    $ http https://rest-api.execute-api.us-west-2.amazonaws.com/api/
    HTTP/1.1 200 OK
    Connection: keep-alive
    Content-Length: 17
    Content-Type: application/json
    Date: Sat, 22 Dec 2018 01:05:48 GMT
    Via: 1.1 5ab5dc09da67e3ea794ec8a82992cc89.cloudfront.net (CloudFront)
    X-Amz-Cf-Id: Cdsow9--fnTH5EdjkjWBMWINCCMD4nGmi4S_3iMYMK0rpc8Mpiymgw==
    X-Amzn-Trace-Id: Root=1-5c1d8dec-f1ef3ee83c7c654ca7fb3a70;Sampled=0
    X-Cache: Miss from cloudfront
    x-amz-apigw-id: SSMc6H_yvHcFcEw=
    x-amzn-RequestId: b7bd0c87-0585-11e9-90cf-59b71c1a1de1

    {
        "hello": "world"
    }

    $ http https://rest-api.execute-api.us-west-2.amazonaws.com/api/foo
    HTTP/1.1 200 OK
    Connection: keep-alive
    Content-Length: 13
    Content-Type: application/json
    Date: Sat, 22 Dec 2018 01:05:51 GMT
    Via: 1.1 95b0ac620fa3a80ee590ecf1cda1c698.cloudfront.net (CloudFront)
    X-Amz-Cf-Id: HX4l1BNdWvYDRXan17PFZya1vaomoJel4rP7d8_stdw2qT50v7Iybg==
    X-Amzn-Trace-Id: Root=1-5c1d8def-214e7f681ff82c00fd81f37a;Sampled=0
    X-Cache: Miss from cloudfront
    x-amz-apigw-id: SSMdXF40vHcF-mg=
    x-amzn-RequestId: b96f77bf-0585-11e9-b229-01305cd40040

    {
        "foo": "bar"
    }


Blueprint Registration
----------------------

The ``app.register_blueprint`` function accepts two optional arguments,
``name_prefix`` and ``url_prefix``.  This allows you to register the resources
in your blueprint at a certain url and name prefix.  If you specify
``url_prefix``, any routes defined in your blueprint will have the
``url_prefix`` prepended to it.  If you specify the ``name_prefix``, any Lambda
functions created will have the ``name_prefix`` prepended to the resource name.

.. note::

  The ``name_prefix`` parameter does not apply to the Lambda function
  associated with API Gateway, which is anything decorated with
  ``@app.route()``.


Advanced Example
----------------

Let's create a more advanced example.  If this application, let's say we want
to organize our application into separate modules for our API and our event
sources.  We can create an app with these files::

    $ ls -la chalicelib/
    __init__.py
    api.py
    events.py


The contents of ``api.py`` are:

.. code-block:: python

    from chalice import Blueprint


    myapi = Blueprint(__name__)


    @myapi.route('/')
    def index():
        return {'hello': 'world'}


    @myapi.route('/foo')
    def index():
        return {'foo': 'bar'}


The contents of ``events.py`` are:

.. code-block:: python

    from chalice import Blueprint


    myevents = Blueprint(__name__)


    @myevents.schedule('rate(5 minutes)')
    def cron(event):
        pass


    @myevents.on_sns_message('MyTopic')
    def handle_sns_message(event):
        pass

In our ``app.py`` we'll register these blueprints:

.. code-block:: python

    from chalice import Chalice
    from chalicelib.events import myevents
    from chalicelib.api import myapi

    app = Chalice(app_name='blueprint-demo')
    app.experimental_feature_flags.update([
        'BLUEPRINTS'
    ])
    app.register_blueprint(myevents)
    app.register_blueprint(myapi)


Now our ``app.py`` only registers the necessary blueprints, and all our
resources are defined in blueprints.
