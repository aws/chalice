========================================
Python Serverless Microframework for AWS
========================================

.. image:: https://badges.gitter.im/awslabs/chalice.svg
   :target: https://gitter.im/awslabs/chalice?utm_source=badge&utm_medium=badge
   :alt: Gitter

The python serverless microframework for AWS allows you to quickly create and
deploy applications that use Amazon API Gateway and AWS Lambda.
It provides:

* A command line tool for creating, deploying, and managing your app
* A familiar and easy to use API for declaring views in python code
* Automatic IAM policy generation


::

    $ pip install chalice
    $ chalice new-project helloworld && cd helloworld
    $ cat app.py

    from chalice import Chalice

    app = Chalice(app_name="helloworld")

    @app.route("/")
    def index():
        return {"hello": "world"}

    $ chalice deploy
    ...
    Your application is available at: https://endpoint/dev

    $ curl https://endpoint/dev
    {"hello": "world"}

Up and running in less than 30 seconds.

**This project is published as a preview project, and is not yet recommended for
production APIs.**  Give this project a try and share your feedback with us
here on Github.

The documentation is available
`on readthedocs <http://chalice.readthedocs.io/en/latest/>`__.

Quickstart
==========

.. quick-start-begin

In this tutorial, you'll use the ``chalice`` command line utility
to create and deploy a basic REST API.
First, you'll need to install ``chalice``.  Using a virtualenv
is recommended::

    $ pip install virtualenv
    $ virtualenv ~/.virtualenvs/chalice-demo
    $ source ~/.virtualenvs/chalice-demo/bin/activate

Note: **make sure you are using python2.7**.  The ``chalice`` CLI
as well as the ``chalice`` python package will support the versions
of python supported by AWS Lambda.  Currently, AWS Lambda only supports
python2.7, so this is what this project supports.  You can ensure
you're creating a virtualenv with python2.7 by running::

    # Double check you have python2.7
    $ which python2.7
    /usr/local/bin/python2.7
    $ virtualenv --python $(which python2.7) ~/.virtualenvs/chalice-demo
    $ source ~/.virtualenvs/chalice-demo/bin/activate

Next, in your virtualenv, install ``chalice``::

    $ pip install chalice

You can verify you have chalice installed by running::

    $ chalice --help
    Usage: chalice [OPTIONS] COMMAND [ARGS]...
    ...

Credentials
-----------

Before you can deploy an application, be sure you have
credentials configured.  If you have previously configured your
machine to run boto3 (the AWS SDK for Python) or the AWS CLI then
you can skip this section.

If this is your first time configuring credentials for AWS you
can follow these steps to quickly get started::

    $ mkdir ~/.aws
    $ cat >> ~/.aws/config
    [default]
    aws_access_key_id=YOUR_ACCESS_KEY_HERE
    aws_secret_access_key=YOUR_SECRET_ACCESS_KEY
    region=YOUR_REGION (such as us-west-2, us-west-1, etc)

If you want more information on all the supported methods for
configuring credentials, see the
`boto3 docs
<http://boto3.readthedocs.io/en/latest/guide/configuration.html>`__.


Creating Your Project
---------------------

The next thing we'll do is use the ``chalice`` command to create a new
project::

    $ chalice new-project helloworld

This will create a ``helloworld`` directory.  Cd into this
directory.  You'll see several files have been created for you::

    $ cd helloworld
    $ ls -la
    drwxr-xr-x   .chalice
    -rw-r--r--   app.py
    -rw-r--r--   requirements.txt

You can ignore the ``.chalice`` directory for now, the two main files
we'll focus on is ``app.py`` and ``requirements.txt``.

Let's take a look at the ``app.py`` file:

.. code-block:: python

    from chalice import Chalice

    app = Chalice(app_name='helloworld')


    @app.route('/')
    def index():
        return {'hello': 'world'}


The ``new-project`` command created a sample app that defines a
single view, ``/``, that when called will return the JSON body
``{"hello": "world"}``.


Deploying
---------

Let's deploy this app.  Make sure you're in the ``helloworld``
directory and run ``chalice deploy``::

    $ chalice deploy
    ...
    Initiating first time deployment...
    https://qxea58oupc.execute-api.us-west-2.amazonaws.com/dev/

You now have an API up and running using API Gateway and Lambda::

    $ curl https://qxea58oupc.execute-api.us-west-2.amazonaws.com/dev/
    {"hello": "world"}

Try making a change to the returned dictionary from the ``index()``
function.  You can then redeploy your changes by running ``chalice deploy``.


For the rest of these tutorials, we'll be using ``httpie`` instead of ``curl``
(https://github.com/jkbrzt/httpie) to test our API.  You can install ``httpie``
using ``pip install httpie``, or if you're on Mac, you can run ``brew install
httpie``.  The Github link has more information on installation instructions.
Here's an example of using ``httpie`` to request the root resource of the API
we just created.  Note that the command name is ``http``::


    $ http https://qxea58oupc.execute-api.us-west-2.amazonaws.com/dev/
    HTTP/1.1 200 OK
    Connection: keep-alive
    Content-Length: 18
    Content-Type: application/json
    Date: Mon, 30 May 2016 17:55:50 GMT
    X-Cache: Miss from cloudfront

    {
        "hello": "world"
    }


Additionally, the API Gateway endpoints will be shortened to
``https://endpoint/dev/`` for brevity.  Be sure to substitute
``https://endpoint/dev/`` for the actual endpoint that the ``chalice``
CLI displays when you deploy your API (it will look something like
``https://abcdefg.execute-api.us-west-2.amazonaws.com/dev/``.

Next Steps
----------

You've now created your first app using ``chalice``.

The next few sections will build on this quickstart section and introduce
you to additional features including: URL parameter capturing,
error handling, advanced routing, current request metadata, and automatic
policy generation.


Tutorial: URL Parameters
========================

Now we're going to make a few changes to our ``app.py`` file that
demonstrate additional capabilities provided by the python serverless
microframework for AWS.

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

Let's try it out.  Note the examples below use the ``http`` command
from the ``httpie`` package.  You can install this using ``pip install httpie``::

    $ http https://endpoint/dev/cities/seattle
    HTTP/1.1 200 OK

    {
        "state": "WA"
    }

    $ http https://endpoint/dev/cities/portland
    HTTP/1.1 200 OK

    {
        "state": "OR"
    }


Notice what happens if we try to request a city that's not in our
``CITIES_TO_STATE`` map::

    $ http https://endpoint/dev/cities/vancouver
    HTTP/1.1 500 Internal Server Error
    Content-Type: application/json
    X-Cache: Error from cloudfront

    {
        "Code": "ChaliceViewError",
        "Message": "ChaliceViewError: An internal server error occurred."
    }


In the next section, we'll see how to fix this and provide better
error messages.


Tutorial: Error Messages
========================

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
    https://endpoint/dev/

Now, when you request the same URL that returned an internal
server error, you'll get back the original stack trace::

    $ http https://endpoint/dev/cities/vancouver
    {
        "errorMessage": "u'vancouver'",
        "errorType": "KeyError",
        "stackTrace": [
            [
                "/var/task/chalice/__init__.py",
                134,
                "__call__",
                "raise e"
            ]
        ]
    }


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
    $ http https://endpoint/dev/cities/vancouver
    HTTP/1.1 400 Bad Request

    {
        "Code": "BadRequestError",
        "Message": "BadRequestError: Unknown city 'vancouver', valid choices are: portland, seattle"
    }

We can see now that we can a ``Code`` and ``Message`` key, with the message
being the value we passed to ``BadRequestError``.  Whenever you raise
a ``BadRequestError`` from your view function, the framework will return an
HTTP status code of 400 along with a JSON body with a ``Code`` and ``Message``.
There are a few additional exceptions you can raise from your python code::

* BadRequestError - return a status code of 400
* UnauthorizedError - return a status code of 401
* ForbiddenError - return a status code of 403
* NotFoundError - return a status code of 404
* ConflictError - return a status code of 409
* TooManyRequestsError - return a status code of 429
* ChaliceViewError - return a status code of 500

You can import these directly from the ``chalice`` package:

.. code-block:: python

    from chalice import UnauthorizedError


Tutorial: Additional Routing
============================

So far, our examples have only allowed GET requests.
It's actually possible to support additional HTTP methods.
Here's an example of a view function that supports PUT:

.. code-block:: python

    @app.route('/resource/{value}', methods=['PUT'])
    def put_test(value):
        return {"value": value}

We can test this method using the ``http`` command::

    $ http PUT https://endpoint/dev/resource/foo
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
PUT is sent to ``/myview``.  In the next section we'll go over
how you can introspect the given request in order to differentiate between
various HTTP methods.

Tutorial: Request Metadata
==========================

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
    $ http GET https://endpoint/dev/objects/mykey
    HTTP/1.1 404 Not Found

    {
        "Code": "NotFoundError",
        "Message": "NotFoundError: mykey"
    }

    # Next, we'll create that key by sending a PUT request.
    $ echo '{"foo": "bar"}' | http PUT https://endpoint/dev/objects/mykey
    HTTP/1.1 200 OK

    null

    # And now we no longer get a 404, we instead get the value we previously
    # put.
    $ http GET https://endpoint/dev/objects/mykey
    HTTP/1.1 200 OK

    {
        "mykey": {
            "foo": "bar"
        }
    }

You might see a problem with storing the objects in a module level
``OBJECTS`` variable.  We address this in the next section.

The ``app.current_request`` object also has the following properties.

* ``current_request.query_params`` - A dict of the query params for the request.
* ``current_request.headers`` - A dict of the request headers.
* ``current_request.uri_params`` - A dict of the captured URI params.
* ``current_request.method`` -  The HTTP method (as a string).
* ``current_request.json_body`` - The parsed JSON body (``json.loads(raw_body)``)
* ``current_request.raw_body`` - The raw HTTP body as bytes.
* ``current_request.context`` - A dict of additional context information
* ``current_request.stage_vars`` - Configuration for the API Gateway stage

Don't worry about the ``context`` and ``stage_vars`` for now.  We haven't
discussed those concepts yet.  The ``current_request`` object also
has a ``to_dict`` method, which returns all the information about the
current request as a dictionary.  Let's use this method to write a view
function that returns everything it knows about the request:

.. code-block:: python

    @app.route('/introspect')
    def introspect():
        return app.current_request.to_dict()


Save this to your ``app.py`` file and redeploy with ``chalice deploy``.
Here's an example of hitting the ``/introspect`` URL.  Note how we're
sending a query string as well as a custom ``X-TestHeader`` header::


    $ http 'https://endpoint/dev/introspect?query1=value1&query2=value2' 'X-TestHeader: Foo'
    HTTP/1.1 200 OK

    {
        "context": {
            ...
            "resource-path": "/introspect",
            "stage": "dev",
            "user-agent": "HTTPie/0.9.3",
            "user-arn": ""
        },
        "headers": {
            "Accept": "*/*",
             ...
            "X-TestHeader": "Foo"
        },
        "json_body": {},
        "method": "GET",
        "query_params": {
            "query1": "value1",
            "query2": "value2"
        },
        "stage_vars": {},
        "uri_params": {}
    }

Tutorial: Request Content Types
===============================

The default behavior of a view function supports
a request body of ``application/json``.  When a request is
made with a ``Content-Type`` of ``application/json``, the
``app.current_request.json_body`` attribute is automatically
set for you.  This value is the parsed JSON body.

You can also configure a view function to support other
content types.  You can do this by specifying the
``content_types`` paramter value to your ``app.route``
function.  This parameter is a list of acceptable content
types.  Here's an example of this feature:

.. code-block:: python

    from chalice import Chalice

    app = Chalice(app_name='helloworld')


    @app.route('/', methods=['POST'],
               content_types=['application/x-www-form-urlencoded'])
    def index():
        parsed = urlparse.parse_qs(app.current_request.raw_body)
        return {
            'states': parsed.get('states', [])
        }

There's a few things worth noting in this view function.
First, we've specified that we only accept the
``application/x-www-form-urlencoded`` content type.  If we
try to send a request with ``application/json``, we'll now
get a ``415 Unsupported Media Type`` response::

    $ http POST https://endpoint/dev/ states=WA states=CA --debug
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

    $ http --form POST https://endpoint/dev/formtest states=WA states=CA --debug
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

    parsed = urlparse.parse_qs(app.current_request.raw_body)

``app.current_request.json_body`` is set to ``None`` whenever the
``Content-Type`` is not ``application/json``.  This means that
you will need to use ``app.current_request.raw_body`` and parse
the request body as needed.

Tutorial: CORS Support
======================

You can specify whether a view supports CORS by adding the
``cors=True`` parameter to your ``@app.route()`` call.  By
default this value is false:

.. code-block:: python

    @app.route('/supports-cors', methods=['PUT'], cors=True)
    def supports_cors():
        return {}


Settings ``cors=True`` has similar behavior to enabling CORS
using the AWS Console.  This includes:

* Injecting the ``Access-Control-Allow-Origin: *`` header to your
  responses, including all error responses you can return.
* Automatically adding an ``OPTIONS`` method so support preflighting
  requests.

The preflight request will return a response that includes:

* ``Access-Control-Allow-Origin: *``
* The ``Access-Control-Allow-Methods`` header will return a list of all HTTP
  methods you've called out in your view function.  In the example above,
  this will be ``PUT,OPTIONS``.
* ``Access-Control-Allow-Headers: Content-Type,X-Amz-Date,Authorization,
  X-Api-Key,X-Amz-Security-Token``.

There's a couple of things to keep in mind when enabling cors for a view:

* An ``OPTIONS`` method for preflighting is always injected.  Ensure that
  you don't have ``OPTIONS`` in the ``methods=[...]`` list of your
  view function.
* Every view function must explicitly enable CORS support.
* There's no support for customizing the CORS configuration.

The last two points will change in the future.  See
`this issue
<https://github.com/awslabs/chalice/issues/70#issuecomment-248787037>`_
for more information.


Tutorial: Policy Generation
===========================

In the previous section we created a basic rest API that
allowed you to store JSON objects by sending the JSON
in the body of an HTTP PUT request to ``/objects/{name}``.
You could then retrieve objects by sending a GET request to
``/objects/{name}``.

However, there's a problem with the code we wrote:

.. code-block:: python

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


We're storing the key value pairs in a module level ``OBJECTS``
variable.  We can't rely on local storage like this persisting
across requests.

A better solution would be to store this information in Amazon S3.
To do this, we're going to use boto3, the AWS SDK for Python.
First, install boto3::

    $ pip install boto3

Next, add ``boto3`` to your requirements.txt file::

    $ echo 'boto3==1.3.1' >> requirements.txt

The requirements.txt file should be in the same directory that contains
your ``app.py`` file.  Next, let's update our view code to use boto3:

.. code-block:: python

    import json
    import boto3
    from botocore.exceptions import ClientError

    from chalice import NotFoundError


    S3 = boto3.client('s3', region_name='us-west-2')
    BUCKET = 'your-bucket-name'


    @app.route('/objects/{key}', methods=['GET', 'PUT'])
    def s3objects(key):
        request = app.current_request
        if request.method == 'PUT':
            S3.put_object(Bucket=BUCKET, Key=key,
                          Body=json.dumps(request.json_body))
        elif request.method == 'GET':
            try:
                response = S3.get_object(Bucket=BUCKET, Key=key)
                return json.loads(response['Body'].read())
            except ClientError as e:
                raise NotFoundError(key)

Make sure to change ``BUCKET`` with the name of an S3 bucket
you own.  Redeploy your changes with ``chalice deploy``.
Now, whenever we make a ``PUT`` request to ``/objects/keyname``, the
data send will be stored in S3.  Any subsequent ``GET`` requests will
retrieve this data from S3.

Manually Providing Policies
---------------------------


IAM permissions can be auto generated, provided manually or can be
pre-created and explicitly configured. To use a
pre-configured IAM role ARN for chalice, add these two keys to your
chalice configuration. Setting manage_iam_role to false tells
Chalice to not attempt to generate policies and create IAM role.

::

    "manage_iam_role":false
    "iam_role_arn":"arn:aws:iam::<account-id>:role/<role-name>"

Whenever your application is deployed using ``chalice``, the
auto generated policy is written to disk at
``<projectdir>/.chalice/policy.json``.  When you run the
``chalice deploy`` command, you can also specify the
``--no-autogen-policy`` option.  Doing so will result in the
``chalice`` CLI loading the ``<projectdir>/.chalice/policy.json``
file and using that file as the policy for the IAM role.
You can manually edit this file and specify ``--no-autogen-policy``
if you'd like to have full control over what IAM policy to associate
with the IAM role.

You can also run the ``chalice gen-policy`` command from your project
directory to print the auto generated policy to stdout.  You can
then use this as a starting point for your policy.

::

    $ chalice gen-policy
    {
      "Version": "2012-10-17",
      "Statement": [
        {
          "Action": [
            "s3:ListAllMyBuckets"
          ],
          "Resource": [
            "*"
          ],
          "Effect": "Allow",
          "Sid": "9155de6ad1d74e4c8b1448255770e60c"
        }
      ]
    }

Experimental Status
-------------------

The automatic policy generation is still in the early stages, it should
be considered experimental.  You can always disable policy
generation with ``--no-autogen-policy`` for complete control.

Additionally, you will be prompted for confirmation whenever the
auto policy generator detects actions that it would like to add or remove::


    $ chalice deploy
    Updating IAM policy.

    The following action will be added to the execution policy:

    s3:ListBucket

    Would you like to continue?  [Y/n]:

.. quick-start-end

Tutorial: Using Custom Authentication
=====================================

AWS API Gateway routes can be authenticated in multiple ways:
- API Key
- Custom Auth Handler

API Key
-------

.. code-block:: python

    @app.route('/authenticated', methods=['GET'], api_key_required=True)
    def authenticated(key):
        return {"secure": True}

Only requests sent with a valid `X-Api-Key` header will be accepted.

Custom Auth Handler
-------------------

A custom Authorizer is required for this to work, details can be found here;
http://docs.aws.amazon.com/apigateway/latest/developerguide/use-custom-authorizer.html

.. code-block:: python

    @app.route('/authenticated', methods=['GET'], authorization_type='CUSTOM', authorizer_id='ab12cd')
    def authenticated(key):
        return {"secure": True}

Only requests sent with a valid `X-Api-Key` header will be accepted.

Backlog
=======

These are features that are in the backlog:

* Adding full support for API gateway stages - `issue 20
  <https://github.com/awslabs/chalice/issues/20>`__
* Adding support for more than ``app.py`` - `issue 21
  <https://github.com/awslabs/chalice/issues/21>`__

Please share any feedback on the above issues.  We'd also love
to hear from you.  Please create any Github issues for additional
features you'd like to see: https://github.com/awslabs/chalice/issues

FAQ
===


**Q: How does the Python Serverless Microframework for AWS compare to other
similar frameworks?**

The biggest difference between this framework and others is that the Python
Serverless Microframework for AWS is singularly focused on using a familiar,
decorator-based API to write python applications that run on Amazon API Gateway
and AWS Lambda.  You can think of it as
`Flask <http://flask.pocoo.org/>`__/`Bottle <http://bottlepy.org/docs/dev/index.html>`__
for serverless APIs.  Its goal is to make writing and deploying these types of
applications as simple as possible specifically for Python developers.

To achieve this goal, it has to make certain tradeoffs.  Python will always
remain the only supported language in this framework.  Not every feature of API
Gateway and Lambda is exposed in the framework.  It makes assumptions about how
applications will be deployed, and it has restrictions on how an application
can be structured.  It does not address the creation and lifecycle of other AWS
resources your application may need (Amazon S3 buckets, Amazon DynamoDB tables,
etc.).  The feature set is purposefully small.

Other full-stack frameworks offer a lot more features and configurability than
what this framework has and likely will ever have.  Those frameworks are
excellent choices for applications that need more than what is offered by this
microframework.  If all you need is to create a simple rest API in Python that
runs on Amazon API Gateway and AWS Lambda, consider giving the Python
Serverless Microframework for AWS a try.

Related Projects
----------------

* `serverless <https://github.com/serverless/serverless>`__ - Build applications
  comprised of microservices that run in response to events, auto-scale for
  you, and only charge you when they run.
* `Zappa <https://github.com/Miserlou/Zappa>`__ - Deploy python WSGI applications
  on AWS Lambda and API Gateway.
* `claudia <https://github.com/claudiajs/claudia>`__ - Deploy node.js projects
  to AWS Lambda and API Gateway.
