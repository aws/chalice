Testing
=======

Chalice provides a :ref:`test client <testing-api>` in ``chalice.test`` that
you can use to test your Chalice applications.  This client lets you invoke
Lambda function and event handlers directly, as well as test your REST APIs.

Lambda Functions
----------------

To test lambda functions, use the
:meth:`Client.lambda_.invoke <TestLambdaClient.invoke>` method.  The
test client is intended to be used as a context manager.  For example,
given this sample app:


.. code-block:: python

   from chalice import Chalice

   app = Chalice(app_name="testclient")

   @app.lambda_function()
   def foo(event, context):
       return {'hello': 'world'}

   @app.lambda_function()
   def bar(event, context):
       return {'event': event}


Here's how you can test these functions with the test client.  In our
example, we'll be using `pytest <https://docs.pytest.org/en/stable/>`__,
but the Chalice test client will work with any testing framework.
We'll create a new ``tests/`` directory and create a ``tests/__init__.py``
and a ``tests/test_app.py`` file.

::

    $ mkdir tests
    $ touch tests/{__init__.py,test_app.py}

The ``tests/test_app.py`` file should have the following contents:

.. code-block:: python

   from chalice.test import Client
   from app import app

   def test_foo_function():
       with Client(app) as client:
           result = client.lambda_.invoke('foo')
           assert result.payload == {'hello': 'world'}

   def test_bar_function():
       with Client(app) as client:
           result = client.lambda_.invoke(
               'bar', {'my': 'event'})
           assert result.payload == {'event': {'my': 'event'}}

Now we can run our tests with ``pytest``::

    $ pip install pytest
    $ py.test tests/test_app.py
    ========================= test session starts ==========================
    platform darwin -- Python 3.7.3, pytest-5.3.1, py-1.5.3, pluggy-0.12.0
    rootdir: /tmp/testclient
    plugins: hypothesis-4.43.1, cov-2.8.1
    collected 2 items

    test_app.py ..                                                            [100%]

    ========================= 2 passed in 0.32s ============================

For testing Lambda functions that are connected to specific events,
you can use the :attr:`Client.events` attribute to generate
sample events.  For example:

.. code-block:: python

   from chalice import Chalice

   @app.on_sns_message(topic='mytopic')
   def foo(event):
       return {'message': event.message}

   # Test code

   from chalice.test import Client

   def test_sns_handler():
       with Client(app) as client:
           response = client.lambda_.invoke(
               "foo",
               client.events.generate_sns_event(message="hello world")
           )
           assert response.payload == {'message': 'hello world'}


Environment Variables
~~~~~~~~~~~~~~~~~~~~~

The Chalice test client will also configure any environment variables you
have configured with your Lambda functions in your ``.chalice/config.json``
file.  For example, suppose you had these config file:

.. code-block:: json

   {
       "version": "2.0",
       "app_name": "testenv",
       "stages": {
           "prod": {
               "api_gateway_stage": "api",
               "environment_variables": {
                   "MY_ENV_VAR": "TOP LEVEL"
               },
               "lambda_functions": {
                   "bar": {
                       "environment_variables": {
                           "MY_ENV_VAR": "OVERRIDE"
                       }
                   }
               }
           }
       }
   }

These sets a ``MY_ENV_VAR`` environment variable for the ``prod`` stage.
The ``bar`` function overrides this environment variable with its own
custom value.  To test this, we need to specify the ``prod`` stage when
we create our test client:

.. code-block:: python

   from chalice import Chalice

   app = Chalice(app_name="testclient")

   @app.lambda_function()
   def foo(event, context):
       return {'value': os.environ.get('MY_ENV_VAR')}

   @app.lambda_function()
   def bar(event, context):
       return {'value': os.environ.get('MY_ENV_VAR')}

    # Test code
   from chalice.test import Client

   def test_foo_function():
       with Client(app, stage_name='prod') as client:
           result = client.lambda_.invoke('foo')
           assert result.payload == {'value': 'TOP LEVEL'}

   def test_bar_function():
       with Client(app) as client:
           result = client.lambda_.invoke('bar')
           assert result.payload == {'value': 'OVERRIDE'}


REST APIs
---------

You can test your REST API with the Chalice test client using the
:attr:`Client.http` attribute.  For example, given this REST API:


.. code-block:: python

   from chalice import Chalice

   app = Chalice(app_name="testclient")

   @app.route('/')
   def index()
       return {'hello': 'world'}


You can test this route with:

.. code-block:: python

   from chalice.test import Client
   from app import app

    def test_index():
        with Client(app) as client:
            response = client.http.get('/')
            assert response.json_body == {'hello': 'world'}

If you want to access the response body's raw bytes, you can use the
``body`` attribute:

.. code-block:: python

   from chalice.test import Client
   from app import app

    def test_index():
        with Client(app) as client:
            response = client.http.get('/')
            assert response.body == b'{"hello":"world"}'


You can also test builtin authorizers with the test client:

.. code-block:: python

   from chalice import Chalice

   app = Chalice(app_name="testclient")

   @app.authorizer()
   def myauth(event)
       if event.token == 'allow':
           return AuthResponse(['*'], principal_id='id')
       return AuthResponse([], principal_id='noone')

   @app.route('/needs-auth', authorizer=myauth)
   def needs_auth()
       return {'success': True}

   #  Test code:
   from chalice.test import Client

    def test_needs_auth():
        with Client(app) as client:
            response = client.http.get(
                '/needs-auth', headers={'Authorization': 'allow'})
            assert response.json_body == {'success': True}
            assert client.http.get(
                '/needs-auth',
                headers={'Authorization': 'deny'}).status_code == 403


Testing Boto3 Client Calls
--------------------------

If your event handlers are making AWS API calls using boto3 or botocore,
you can use the `botocore stubber
<https://botocore.amazonaws.com/v1/documentation/api/latest/reference/stubber.html>`__
to test your API calls.  For example, suppose we have an app that makes an
API call to Amazon Rekognition whenever an object is uploaded to S3:

.. code-block:: python

   import boto3

   from chalice import Chalice

   app = Chalice(app_name='testclient')
   _REKOGNITION_CLIENT = None


   def get_rekognition_client():
       global _REKOGNITION_CLIENT
       if _REKOGNITION_CLIENT is None:
           _REKOGNITION_CLIENT = boto3.client('rekognition')
       return _REKOGNITION_CLIENT


   @app.on_s3_event(bucket='mybucket',
                    events=['s3:ObjectCreated:*'])
   def handle_object_created(event):
       client = get_rekognition_client()
       response = client.detect_labels(
           Image={
               'S3Object': {
                   'Bucket': event.bucket,
                   'Name': event.key,
               },
           },
           MinConfidence=50.0
       )
       labels = [label['Name'] for label in response['Labels']]
       # In the real app we'd now do something with these labels
       # (e.g. store than in a database so we can query them later).
       return labels

To test this, we'll combine the botocore stubber and the Chalice test client:

.. code-block:: python

   from chalice.test import Client
   import app

   from botocore.stub import Stubber

   def test_calls_rekognition():
       client = app.get_rekognition_client()
       stub = Stubber(client)
       stub.add_response(
           'detect_labels',
           expected_params={
               'Image': {
                   'S3Object': {
                       'Bucket': 'mybucket',
                       'Name': 'mykey',
                   }
               },
               'MinConfidence': 50.0,
           },
           service_response={
               'Labels': [
                   {'Name': 'Dog', 'Confidence': 75.0},
                   {'Name': 'Mountain', 'Confidence': 80.0},
                   {'Name': 'Snow', 'Confidence': 85.0},
               ]
           },
       )
       with stub:
           with Client(app.app) as client:
               event = client.events.generate_s3_event(
                   bucket='mybucket', key='mykey')
               response = client.lambda_.invoke('handle_object_created', event)
               assert response.payload == ['Dog', 'Mountain', 'Snow']
           stub.assert_no_pending_responses()


In the testcase above, we first tell the stubber what API call we're expecting,
along with the parameters we'll send and the response we expect back from the
Rekognition service.  Next we use the ``with stub:`` line to activate our stubs.
This also ensures that when our test exits that we'll deactive the stubs for
this client.  Now we the ``client.lambda_.invoke`` method is called, our
stubbed client will return the preconfigured response data instead of making
an actual API call to the Rekognition service.


Next Steps
----------

For reference documentation on the methods and attributes of the Chalice test
client, see the :ref:`test client <testing-api>` section in the API
documentation.
