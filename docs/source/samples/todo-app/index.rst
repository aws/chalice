================
Todo Application
================

This is a sample application that allows you to manage Todo items.  This
tutorial will walk through creating a serverless web API to create, update,
get, and delete Todos, managing Todos in a database, and adding authorization
with JWT.  AWS services covered include AWS Lambda, Amazon API Gateway, Amazon
DynamoDB, AWS CodeBuild, and AWS Systems Manager.

You can find the full source code for this application in our
`samples directory on GitHub <https://github.com/aws/chalice/tree/master/docs/source/samples/todo-app/code/>`__.

::

    $ git clone git://github.com/aws/chalice
    $ cd chalice/docs/source/samples/todo-app/code

We'll now walk through the architecture of this application,
how to deploy and use the application, and finally we'll go over
the main components of the application code.

.. note::
    This sample application is also available as a `workshop
    <https://chalice-workshop.readthedocs.io/en/latest/todo-app/index.html>`__.
    The main difference between the sample apps here and the Chalice workshops
    is that the workshop is a detailed step by step process for how to create
    this application from scratch.  You build the app by gradually adding each
    feature piece by piece.  In the workshop, we first create a REST API with
    no authentication or data store.  Then we introduce DynamoDB, then JWT
    auth, etc.  The workshop also shows you how to set up a CI/CD pipeline
    to automatically deploy your application whenever you push to your git
    repository.  It takes several hours to work through all the workshop
    material.  In this document we review the architecture, the deployment process,
    then walk through the main sections of the final version of this
    application.

Architecture
============

The main component of this application is a REST API backed by Amazon API
Gateway and AWS Lambda.  The rest API lets you manage a Todo list.  It lets you
create a new Todo list as well as check off existing Todo items.

In order to see a list of your Todo items, you must first log in.  Information
about our users is stored in an Amazon DynamoDB table.  The authentication is
done using a builtin authorizer.  This lets you define a Lambda function to
perform your custom auth process.  For this sample app, we're using JSON Web
Tokens (JWT).

The Todo items are stored in a separate DynamoDB table.  Below is
an architecture diagram of our sample app.  It shows the API Gateway
REST API, along with a Lambda function for our authorizer, a Lambda function
for our REST API, and two DynamoDB tables.

.. image:: docs/assets/architecture.jpg
  :width: 100%
  :alt: Architecture diagram

.. _todo-sample-rest-api:

REST API
--------

The REST API supports the following resources:

* GET    - ``/todos/`` - Gets a list of all todo items
* POST   - ``/todos/`` - Creates a new Todo item
* GET    - ``/todos/{id}`` - Gets a specific todo item
* DELETE - ``/todos/{id}`` - Deletes a specific todo item
* PUT    - ``/todos/{id}`` - Updates the state of a todo item

A todo item has this schema::

  {
    "description": {"type": "str"},
    "uid": {"type: "str"},
    "state": {"type: "str", "enum": ["unstarted", "started", "completed"]},
    "metadata": {
      "type": "object"
    }
  }


Deployment
==========

To run and deploy this application, first create a virtual environment
and install the dependencies.  Python 3.7 is used for this sample app.

::

    $ python3 -m /tmp/venv37
    $ . /tmp/venv37/bin/activate
    $ pip install ./requirements-dev.txt
    $ pip install ./requirements.txt

As part of this application, there are additional resources that
are created that are used by this application, including two DynamoDB
tables as well as an SSM parameter used to store our secret key used
in our JWT auth.  To create these resources, you can run::

    $ python create-resources.py

This will also update your ``.chalice/config.json`` file with environment
variables containing the name of the DynamoDB tables that were created.

At this point, you can either test the application by running ``chalice
local``.  This will start a local HTTP server on port 8000 that emulates API
Gateway so that you can test without having to deploy your application to AWS.
You can also run ``chalice deploy`` to deploy your application to
AWS, which allows you to test on an actual API Gateway REST API::

     $ chalice deploy
     Creating deployment package.
     Creating IAM role: mytodo-dev-api_handler
     Creating lambda function: mytodo-dev
     Creating IAM role: mytodo-dev-jwt_auth
     Creating lambda function: mytodo-dev-jwt_auth
     Creating Rest API
     Resources deployed:
       - Lambda ARN: arn:aws:lambda:us-east-1:12345:function:mytodo-dev
       - Lambda ARN: arn:aws:lambda:us-east-1:12345:function:mytodo-dev-jwt_auth
       - Rest API URL: https://abcd.execute-api.us-west-2.amazonaws.com/api/


Using the Application
=====================

If you've deployed your application using ``chalice deploy``, you can test
the REST API by making requests to the ``Rest API URL``, shown in the output
of ``chalice deploy``, in our example that would be
``https://abcd.execute-api.us-west-2.amazonaws.com/api/``.  If you're using
``chalice local``, you'll make requests to ``http://localhost:8000/``.

Before we can make requests we need to authenticate with the API.  In order
to authenticate with the API we need to create user accounts.

A helper script, ``users.py`` is included in the repository to help you
manage users.  The first thing we'll need to do is create a user::

    $ python users.py --create-user
    Username: myusername
    Password:

This will create a new entry in our users DynamoDB table.
You can then test that the password verification works by running::

    $ python users.py --test-password
    Username: myusername
    Password:
    Password verified.

Once we've created a test user, we can now login by sending a POST
request to the ``/login`` URL::

    $ echo '{"username": "myusername", "password": "mypassword"}' | \
        http POST https://abcd.execute-api.us-west-2.amazonaws.com/api/login/
    {
        "token": "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJteXVzZXJuYW1lIiwiaWF0IjoxNTk1NDU3Njg5LCJuYmYiOjE1OTU0NTc2ODksImp0aSI6IjMxNjc4YzFkLTdkZjEtNGEzOC04YmZiLTllZjZiMGM1YzAyNyJ9.w46RdtzZdk_P0LAh_St3wjsqgh-k-Hp1ykTpbDqad2k",
    }

.. note::
  We're using the HTTPie command line tool instead of cURL.  You can
  install this tool by running ``pip install httpie``.

Now whenever we make any requests to our REST API, we need to include
the token value in the output above as the value of our ``Authorization``
header.  For example, we can list all of our Todos, which is initially
empty::

    $ http https://abcd.execute-api.us-west-2.amazonaws.com/api/todos/ 'Authorization: my.jwt.token'
    HTTP/1.1 200 OK
    Content-Length: 2
    Content-Type: application/json

    []


If you omit the ``Authorization`` header, you'll see this error response::

    $ http https://abcd.execute-api.us-west-2.amazonaws.com/api/todos/
    HTTP/1.1 401 Unauthorized
    Content-Length: 26
    Content-Type: application/json
    x-amzn-ErrorType: UnauthorizedException

    {
        "message": "Unauthorized"
    }


We can create a new Todo::

    $ echo '{"description": "My first Todo", "metadata": {}}' \
        |  http POST https://abcd.execute-api.us-west-2.amazonaws.com/api/todos/ \
           'Authorization: my.jwt.token'
    HTTP/1.1 200 OK
    Content-Length: 36
    Content-Type: application/json

    e25643f7-0b18-47d2-b124-4e6713ab527c

Now when we list our Todos, we'll see our new entry we created::

    $ http https://abcd.execute-api.us-west-2.amazonaws.com/api/todos/ 'Authorization: my.jwt.token'
    HTTP/1.1 200 OK
    Content-Length: 136
    Content-Type: application/json

    [
        {
            "description": "My first Todo",
            "metadata": {},
            "state": "unstarted",
            "uid": "e25643f7-0b18-47d2-b124-4e6713ab527c",
            "username": "myusername"
        }
    ]

We can update our Todo and mark it completed::


    $ echo '{"state": "completed"}' |  \
        http PUT https://abcd.execute-api.us-west-2.amazonaws.com/api/todos/e25643f7-0b18-47d2-b124-4e6713ab527c \
        'Authorization: my.jwt.token'
    HTTP/1.1 200 OK
    Content-Length: 4
    Content-Type: application/json

    null

And we can now verify that the Todo item shows up as completed::

    $ http https://abcd.execute-api.us-west-2.amazonaws.com/api/todos/e25643f7-0b18-47d2-b124-4e6713ab527c \
        'Authorization: my.jwt.token'
    HTTP/1.1 200 OK
    Content-Length: 134
    Content-Type: application/json

    {
        "description": "My first Todo",
        "metadata": {},
        "state": "completed",
        "uid": "e25643f7-0b18-47d2-b124-4e6713ab527c",
        "username": "myusername"
    }


Code Walkthrough
================


.. _todo-app-rest-api:

Rest API
--------

Below is the code for the five routes defined in the
:ref:`todo-sample-rest-api` section defined in the ``app.py`` file:

.. literalinclude:: code/app.py
   :caption: app.py
   :linenos:
   :lineno-match:
   :lines: 67-105

The first thing all of these routes do is extract the current username from the
request.  This is done by examining the context associated with the current
request.  This will include the ``principalId``, or the current username, which
is discussed in more detail in the :ref:`todo-app-jwt-auth` section below.

Each of these routes then makes a call into the data storage layer,
and either retrieves or updates data in the ``Todo`` DynamoDB table.
This is discussed in the next section on data storage.

The application DB is tracked as a module level variable that is
retrieved through the ``get_app_db()`` function.  The name of the
DynamoDB table is provided through the ``APP_TABLE_NAME`` environment
variable, which is specified in your ``.chalice/config.json`` file.
This was automatically filled in for you when you ran the
``create-resources.py`` script.

User input is extracted from both the URL (the ``uid`` associated with
a Todo item is provided as part of the URL) as well as the JSON
request body.  A key takeaway from these routes is that there's
minimal logic in the route definitions themselves.  They're primarily
about extracting user input and then delegating the heavy lifting to
other objects that are independent of any routing information.


Data Storage
------------

Each route in this sample application app makes a call to the
data storage layer, which is backed by a DynamoDB table.  This interface
is defined by the ``TodoDB`` interface, which is defined in the
``chalicelib/db.py`` file:

.. literalinclude:: code/chalicelib/db.py
  :caption: chalicelib/db.py
  :linenos:
  :lineno-match:
  :pyobject: TodoDB

There are two different implementations of this interface.  The first one,
``InMemoryTodoDB``, is an in-memory implementation of this interface where
all data is stored within the process.  The purpose of this implementation
is for testing purposes when you don't want to work with the real DynamoDB
service.  This allows you to develop your application locally and test
using ``chalice local``.  The other implementation of ``TodoDB`` interface is
``DynamoDBTodo``, which communicates with the actual DynamoDB service
to store and retrieve Todo items.  It uses the Table resource of ``boto3``,
created via ``boto3.resource('dynamodb').Table(TABLE_NAME)``.  This allows
us to use the `high level querying interface of boto3 <https://boto3.amazonaws.com/v1/documentation/api/latest/reference/customizations/dynamodb.html#dynamodb-conditions>`__.
The implementation is shown below.

.. literalinclude:: code/chalicelib/db.py
  :caption: chalicelib/db.py
  :linenos:
  :lineno-match:
  :pyobject: DynamoDBTodo

.. _todo-app-jwt-auth:

JWT Authentication
------------------

.. note::
  This example is for illustration purposes and does not necessarily
  represent best practices.  Its intent is to show how custom
  authentication can be implemented in a Chalice app.

Our REST API for our Todo items requires that you send an appropriate
``Authorization`` header when making HTTP requests.  You can retrieve
a auth token by making a request to the ``/login`` route with your
user name and password.  The underlying mechanism used to handle
our auth functionality is through issuing a `JWT <https://jwt.io/>`__
when you login.

Users Table
~~~~~~~~~~~

In order to login, we need a way to store and retrieve user information.  This
is done through our ``Users`` DynamoDB table.  This was created when you ran
the ``create-resoureces.py`` file.  Each user record stores their username and
information about their password.  We're using PBKDF2 as our key derivation
function for password hashing, which is available in Python's standard library
through the `hashlib.pbkdf2_hmac
<https://docs.python.org/3/library/hashlib.html#hashlib.pbkdf2_hmac>`__
function.  The parameters needed by ``pbkdf2_hmac`` are stored in each user's
record, including the password hash, salt, number of rounds, and the hash used
for PBKDF2 (sha256 in our example).  These user entries were created and stored
in the ``Users`` DynamoDB table when you ran the ``python users.py
--create-user`` command.
You can see the fields for a specific user by using the ``--get-user`` option
to the ``users.py`` script::


    $ python users.py --get-user myusername
    Entry for user: myusername
      hash      : sha256
      username  : myusername
      hashed    : Hym8Ss6WIArus+aZ6BucZ3sz6Wu5w8Tc3lPUivTuUi4=
      salt      : rXMPBx8ZriKU3SQTh58BlxQQtpcLHfmITTB2tpRs/sM=
      rounds    : 100000


Login Flow
~~~~~~~~~~

Below is the code for the ``/login`` route:

.. literalinclude:: code/app.py
  :caption: app.py
  :linenos:
  :lineno-match:
  :pyobject: login

In this login view, we first lookup the user record fom our users DB,
and then try to generate a JWT token for this entry.  The
``auth.get_jwt_token`` will first verify that the password hash
matches what's stored in our users DB, and then generate a JWT token
for this user as shown in the code below:

.. literalinclude:: code/chalicelib/auth.py
  :caption: chalicelib/auth.py
  :linenos:
  :lineno-match:
  :pyobject: get_jwt_token

The call to ``jwt.encode()`` requires a payload and a secret.
This secret is a value that is only known to our application and is
used in our built-in authorizer to verify the JWT is valid.
This secret value is stored as an SSM parameter.  A random secret
was automatically generated and stored in SSM for you when running the
``create-resources.py`` script.  When we call ``auth.get_jwt_token`` we first
retrieve this value from SSM as shown in the ``get_auth_key()`` function
defined in our ``app.py`` file:

.. literalinclude:: code/app.py
  :caption: app.py
  :linenos:
  :lineno-match:
  :pyobject: get_auth_key

Once we've generated a JWT token, we return the token back to the caller.
They must then provide that same token in the ``Authorization`` header
whenever they make API calls to the REST API.

Custom Authorizer
~~~~~~~~~~~~~~~~~

In order to require that a specific route requires proper authorization,
we must first create an authorizer, and then associate it with any routes
that require auth.  Chalice supports different types of
:doc:`../../topics/authorizers`, and in this example we're using the
:ref:`builtin-authorizers` type provided by Chalice.  This lets us write
our custom authorization logic as part of our Chalice app.  To do this,
we decorate our auth function with the ``@app.authorizer`` decorator.
Our custom authorizer logic takes the JWT token (accessible through the
``auth_request.token`` attribute, and verifies the token is valid
using our secret key retrieved via ``get_auth_key()``.  The custom
authorizer is shown below:

.. literalinclude:: code/app.py
  :caption: app.py
  :linenos:
  :lineno-match:
  :pyobject: jwt_auth

Once we verify that JWT token is valid, we return an ``AuthResponse`` that
specifies what routes the user is allowed to access.  In our example, we're
giving them access to all routes, denoted by a ``*``.

Now that we have our authorizer, we can associate with a route by providing
the function as the value of the ``authorizer=`` parameter.  We saw this in the
:ref:`todo-app-rest-api` section above.  For example, note that the
``@app.route()`` decorator is being provided an ``authorizer`` function:

.. literalinclude:: code/app.py
  :caption: app.py
  :linenos:
  :lineno-match:
  :pyobject: list_todos


Cleaning Up
===========

Once you're finished experimenting with this sample app, you can cleanup your
resources by deleting the Chalice app and deleting any additional resources
associated with this app.  To do this, first delete your Chalice app::

    $ chalice delete
    Deleting Rest API: q7dc49grhk
    Deleting function: arn:aws:lambda:us-west-w:12345:function:mytodo-dev-jwt_auth
    Deleting IAM role: mytodo-dev-jwt_auth
    Deleting function: arn:aws:lambda:us-west-w:12345:function:mytodo-dev
    Deleting IAM role: mytodo-dev-api_handler

Then to cleanup the remaining resources, rerun the
``create-resources.py`` script with the ``--cleanup`` flag.  This will delete
the DynamoDB tables and the SSM parameter, along with any additional resources
created as part of your Chalice app::

    $ python create-resources.py --cleanup
    Deleting table: todo-app-632a558c-8355-4c2d-a46e-24350f371389
    Deleting table: users-app-05b34fa2-1ae6-4d81-95d1-7ced59878a2b
    Deleting SSM param: /todo-sample-app/auth-key
    Resources deleted.  If you haven't already, be sure to run 'chalice delete' to delete your Chalice application.
