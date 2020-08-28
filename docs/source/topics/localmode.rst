Local Mode
==========

The ``chalice local`` command can be used to start a local server for testing
your REST APIs. This runs a server on port 8000 that auto-reloads on code
changes, giving you quick feedback before deploying to AWS. The default local
mode is less accurate to the actual Lambda runtime, but is faster to start up
than the containerized local mode. Built-in authorizers are supported while
all other authorizer types will admit all requests.
Your REST API routes are available at ``localhost:8000/``.

For example, given the following sample app:

.. code-block:: python

    from chalice import Chalice

    app = Chalice(app_name="hello_world")

    @app.route('/hello')
    def test():
        return {'hello': 'world'}

**Usage:**

::

    $ chalice local

And now we can make HTTP requests to the endpoint:

::

    $ http localhost:8000/hello
    HTTP/1.1 200 OK
    Content-Length: 17
    Content-Type: application/json
    Date: Thu, 18 Aug 2020 02:02:20 GMT
    Server: BaseHTTP/0.6 Python/3.7.7

    {
        "hello": "world"
    }

*For the examples in this doc,* ``httpie`` *is used for making HTTP requests,*
*but any HTTP client can be used.*

Local Mode with Docker Containers
=================================

Your Chalice app can also be tested locally without deploying to AWS using the
containerized local mode. This feature starts a local endpoint that emulates
the behavior of both API Gateway and Lambda, enabling you to programmatically
invoke Lambda functions defined in your Chalice app using the AWS CLI or SDKs,
as well as test your REST APIs. A Docker container that replicates the live
Lambda environment is created for each Lambda function that would be generated
by ``chalice deploy`` in order to mirror the actual Lambda environment as
accurately as possible. Note that there exists a cold-start penalty for the
first time a Lambda function is locally invoked, but the container is
indefinitely kept warm afterwards.

Your app will be automatically packaged along with any specified layers
(including the automatic layer) before being mounted on the Docker containers.
Once you are finished testing, stopping the local AWS service will clean up
the created Docker containers and related resources automatically.

**Usage:**

::

    $ chalice local --use-container

This will start the local AWS service on ``localhost:8000`` by default. Lambda
functions can be invoked by sending requests directly to ``localhost:8000``
while the REST API routes are accessible at ``localhost:8000/api``.

**Prerequisites:**

You'll need Docker installed, but the necessary images will be automatically
downloaded on the first run if they are not already present.


Pure Lambda Functions
---------------------

Pure Lambda functions defined in your Chalice app can be invoked using the
``chalice invoke`` command, the AWS CLI, or any AWS SDK.

For example, for the sample app:

.. code-block:: python

    from chalice import Chalice

    app = Chalice(app_name="hello_world")

    @app.lambda_function()
    def hello(event, context):
        return {"hello": "world"}

    @app.lambda_function()
    def greet(event, context):
        return {"hello": event["name"]}

Using the Chalice CLI
~~~~~~~~~~~~~~~~~~~~~

The Chalice CLI provides a convenient wrapper around the ``aws lambda invoke``
command. The ``--local`` flag sends the request to ``localhost:8000``, or the
``--endpoint-url`` argument can be specified to send the request to any
arbitrary endpoint.

::

    $ chalice invoke --local -n hello
    {"hello": "world"}

::

    $ echo '{"name": "stephen"}' | chalice invoke --local -n greet

    {"hello": "stephen"}

Using the AWS CLI
~~~~~~~~~~~~~~~~~

The AWS CLI can also be used to directly call ``aws lambda invoke``.
Note that you will need to specify the full name of the Lambda function,
i.e. ``hello_world-dev-greet``. If you are using AWS CLI v2, you'll need to
add ``--cli-binary-format raw-in-base64-out`` to the below command.

::

    $ aws lambda invoke --endpoint http://localhost:8000 --function-name
        hello_world-dev-greet --payload '{"name": "stephen"}' output.json
    {
        "StatusCode": 200,
        "ExecutedVersion": "$LATEST"
    }
    $ cat output.json
    {"hello": "stephen"}

Using an AWS SDK
~~~~~~~~~~~~~~~~

Python example:

.. code-block:: python

    lambda_client = boto3.client(
        'lambda', endpoint_url="http://127.0.0.1:8000",
        config=Config(signature_version=UNSIGNED,
                      read_timeout=0,
                      retries={'max_attempts': 3}))
    lambda_client.invoke(FunctionName="hello_world-dev-hello")

Other Lambda Functions
----------------------

Since the containerized local mode creates a container for each deployable
Lambda function, it can also be used to test other Lambda functions supported
by Chalice, such as event source handlers.

For example, for the sample app:

.. code-block:: python

    from chalice import Chalice

    app = Chalice(app_name="hello_world")

    @app.on_s3_event(bucket='lambda_bucket')
    def s3handler(event):
        return {"message": "Object uploaded for bucket: %s, key: %s"
            % (event.bucket, event.key)}


We can generate a fake ``s3event.json``:

.. code-block:: json

    {
        "Records": [
            {
                "eventVersion": "2.1",
                "eventSource": "aws:s3",
                "awsRegion": "us-east-1",
                "eventTime": "2020-08-18T02:02:20.000Z",
                "eventName": "ObjectCreated:Put",
                "userIdentity": {
                    "principalId": "AWS:USER_IDENTITY"
                },
                "s3": {
                    "s3SchemaVersion": "1.0",
                    "configurationId": "config_id",
                    "bucket": {
                        "name": "lambda_bucket",
                        "ownerIdentity": {
                            "principalId": "PRINCIPAL_ID"
                        },
                        "arn": "arn:aws:s3:::some_arn"
                    },
                    "object": {
                        "key": "object_key",
                        "size": 123456789
                    }
                }
            }
        ]
    }

And then we can test the S3 event handler:

::

    $ aws lambda invoke --function-name hello_world-dev-s3handler --payload
        file://s3event.json --endpoint-url http://localhost:8000 output.json
    {
        "StatusCode": 200,
        "ExecutedVersion": "$LATEST"
    }
    $ cat output.json
    {"message": "Object uploaded for bucket: lambda_bucket, key: object_key"}


REST APIs
---------

Your REST APIs can be tested at ``localhost:8000/{API_GATEWAY_STAGE}``,
similar to an API Gateway endpoint. The default API Gateway stage is ``api``,
so we will be sending requests to ``localhost:8000/api``.

For example, given the following sample app:

.. code-block:: python

    from chalice import Chalice, AuthResponse

    app = Chalice(app_name="hello_world")

    @app.route('/hello')
    def index():
        return {'hello': 'world'}

    @app.authorizer()
    def demo_auth(auth_request):
        token = auth_request.token
        if token == 'allow':
            return AuthResponse(routes=['/auth'], principal_id='user')
        else:
            return AuthResponse(routes=[], principal_id='user')

    @app.route('/auth', authorizer=demo_auth)
    def auth():
        return {'authorized': True}

We can make HTTP requests to the endpoint:

::

    $ http localhost:8000/api/hello
    HTTP/1.1 200 OK
    Content-Length: 17
    Content-Type: application/json
    Date: Thu, 18 Aug 2020 02:02:20 GMT
    Server: BaseHTTP/0.6 Python/3.7.7

    {
        "hello": "world"
    }

Authorizers
~~~~~~~~~~~

Similar to the containerless local mode, only built-in authorizers are fully
supported locally. The authorizer function will be called within a Docker
container as well.

Unauthorized:

::

    $ http localhost:8000/api/auth
    HTTP/1.1 401 Unauthorized
    Content-Length: 26
    Content-Type: application/json
    Date: Thu, 18 Aug 2020 02:02:20 GMT
    Server: BaseHTTP/0.6 Python/3.7.7
    x-amzn-ErrorType: UnauthorizedException
    x-amzn-RequestId: ad388a55-02ac-423f-a478-632859086fe2

    {
        "message": "Unauthorized"
    }

Authorized:

::

    $ http localhost:8000/api/auth 'Authorization: allow'
    HTTP/1.1 200 OK
    Content-Length: 19
    Content-Type: application/json
    Date: Thu, 18 Aug 2020 02:02:20 GMT
    Server: BaseHTTP/0.6 Python/3.7.7

    {
        "authorized": true
    }
