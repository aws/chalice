Deploying with the AWS CDK
==========================

In this tutorial, we're going to create a REST API with an Amazon DynamoDB
table as our data store.  We'll be using the `AWS Cloud Development Kit (CDK)
<https://aws.amazon.com/cdk/>`__
to deploy our application, and we'll show how to use the integration between
Chalice and the CDK in order to build and deploy our application.

By combining Chalice and the CDK together, you can use Chalice to
write your application code using its familiar, decorator-based APIs, and
use the CDK and the full breadth of its construct libraries to create the
service infrastructure and resources needed for your application.
We'll also see how we can use the Chalice construct to manipulate our
Chalice application using the CDK APIs as well as take resources from
CDK constructs and map them into our Chalice application.


Installation and Configuration
------------------------------

This tutorial requires that both Chalice and the AWS CDK is installed.
The CDK is written in Typescript and requires node and npm to be installed.
See the `Getting started with the AWS CDK <https://docs.aws.amazon.com/cdk/latest/guide/getting_started.html#getting_started_prerequisites>`__
for more details on install the CDK.

First, we'll install the CDK.

::

  $ npm install -g aws-cdk

You should now have a ``cdk`` executable you can run.

::

  $ cdk --version
  1.83.0 (build 827c5f4)

Next we'll create a Python virtual environment and install Chalice.  Be sure
to use Python 3.6 or greater.

::

  $ python3 -m venv demo
  $ . demo/bin/activate
  $ python3 -m pip install chalice
  $ chalice --version
  chalice 1.22.0, python 3.7.8, darwin 19.6.0

CDK integration with Chalice is available as an optional package installation.
To install the necessary dependencies run the following command:

::

  $ python3 -m pip install "chalice[cdk]"

You're now ready to create your first Chalice and CDK application.


Project Creation
----------------

To create a new project we'll use the ``chalice new-project`` command with no
arguments.  Enter a name for your project and select
``[CDK] REST API with DynamoDB backend`` for the project type.

::

  $ chalice new-project


     ___  _  _    _    _     ___  ___  ___
    / __|| || |  /_\  | |   |_ _|/ __|| __|
   | (__ | __ | / _ \ | |__  | || (__ | _|
    \___||_||_|/_/ \_\|____||___|\___||___|


  The python serverless microframework for AWS allows
  you to quickly create and deploy applications using
  Amazon API Gateway and AWS Lambda.

  Please enter the project name
  [?] Enter the project name: cdkdemo
  [?] Select your project type: [CDK] REST API with DynamoDB backend
     REST API
     S3 Event Handler
     Lambda Functions only
     Legacy REST API Template
     [CDK] REST API with DynamoDB backend

  Your project has been generated in ./cdkdemo

Next, we'll ``cd`` into the ``cdkdemo`` directory and see what Chalice has
generated.

::

  $ cd cdkdemo
  $ tree
  .
  ├── README.rst
  ├── infrastructure           # CDK Application
  │   ├── app.py
  │   ├── cdk.json
  │   ├── requirements.txt
  │   └── stacks
  │       ├── __init__.py
  │       └── chaliceapp.py
  ├── requirements.txt
  └── runtime                  # Chalice Application
      ├── app.py
      └── requirements.txt


There's two top level directories, ``infrastructure`` and ``runtime``, which
correspond to the CDK application and the Chalice application.  The
``infrastructure`` directory is where we can add additional AWS resources
needed by our application, and the ``runtime`` directory is where we write
our application code for our Lambda functions.  We'll look at these in more
detail, but first we'll deploy our application.

In order to build and deploy our application, we need to install the
dependencies used by our application.  We can do this by installing the
requirements file in the top level directory of our project.

::

  $ python3 -m pip install -r requirements.txt

If this is your first time using the CDK, you'll need to bootstrap your
account, which will deploy an AWS CloudFormation stack that contains
resources needed to store our application.  You can do this by running the
``cdk bootstrap`` command from the ``infrastructure`` directory.


::

  $ cd infrastructure
  $ cdk bootstrap
  Packaging Chalice app for cdkdemo
  Creating deployment package.
  The stack cdkdemo already includes a CDKMetadata resource
   ⏳  Bootstrapping environment aws://12345/us-west-2...
  CDKToolkit: creating CloudFormation changeset...
  [██████████████████████████████████████████████████████████] (3/3)


   ✅  Environment aws://12345/us-west-2 bootstrapped.

We can now deploy our applicaation using the ``cdk deploy`` command.  Make sure
you're still in the ``infrastructure`` directory.


::

  $ cdk deploy
  Packaging Chalice app for cdkdemo
  Creating deployment package.
  Reusing existing deployment package.
  The stack cdkdemo already includes a CDKMetadata resource
  This deployment will make potentially sensitive changes according to your current security approval level (--require-approval broadening).
  Please confirm you intend to make the following modifications:

  ...

  Do you wish to deploy these changes (y/n)? y
  cdkdemo: deploying...
  [0%] start: Publishing abcd:current
  [100%] success: Published abcd:current
  cdkdemo: creating CloudFormation changeset...
  [██████████████████████████████████████████████████████████] (10/10)


   ✅  cdkdemo

  Outputs:
  cdkdemo.APIHandlerArn = arn:aws:lambda:us-west-2:12345:function:cdkdemo-APIHandler-C8OLGQT9YIDO
  cdkdemo.APIHandlerName = cdkdemo-APIHandler-C8OLGQT9YIDO
  cdkdemo.AppTableName = cdkdemo-AppTable815C50BC-1OPGOPFYODZOJ
  cdkdemo.EndpointURL = https://abcd.execute-api.us-west-2.amazonaws.com/api/
  cdkdemo.RestAPIId = abcd

  Stack ARN:
  arn:aws:cloudformation:us-west-2:12345:stack/cdkdemo/574c4850-1d23-11eb-8cae-0aea264da24f

We've now deployed a Chalice application powered by the CDK.  We can now test
our REST API.


.. note::
   If you've Chalice before, you may be familiar with the ``chalice deploy``
   command.  When we use the AWS CDK to deploy our application we no longer
   use ``chalice deploy`` and instead we run ``cdk deploy`` from the
   ``infrastructure/`` directory.  You should not use ``chalice deploy``
   to deploy your application when using Chalice's CDK integration.

Testing
-------

To test our application, we make HTTP requests to our ``EndpointUrl``, which is
shown as the value for ``cdkdemo.EndpointUrl`` in the output section above.
We're using `httpie <https://httpie.io/>`__ to make our HTTP requests from the
command line.

::

  $ python3 -m pip install httpie
  $ http POST https://abcd.execute-api.us-west-2.amazonaws.com/api/users/ username=jamesls name=James
  HTTP/1.1 200 OK
  ...

  {}

  $ http https://abcd.execute-api.us-west-2.amazonaws.com/api/users/jamesls
  HTTP/1.1 200 OK
  Content-Type: application/json
  ...

  {
      "name": "James",
      "username": "jamesls"
  }

Now that we have our sample application up and running, let's walk through the
project code so we can better understand what's happening.


Code Walkthrough
----------------

The ``runtime/`` directory contains code where you define your Lambda event
handlers (e.g. ``@app.route()``, ``@app.on_s3_event()``, etc.).  When you
create a Chalice application without the CDK, this is normally the root
directory for your application.  You should also see your Chalice config file
in ``.chalice/config.json``.  The ``infrastructure/`` directory contains the
definitions for the AWS resources used by your application.  This is the
directory structure that would be generated if you were only using the
CDK and not Chalice.  This is why the combined Chalice/CDK application template
has a new top level directory with separate sub directories for the CDK app
and the Chalice app.

To better understand how the two applications communicate with each other,
we'll examine how the DynamoDB table was added to the application.

First, let’s look at the code for our REST API in ``runtime/app.py``.


.. code-block:: python

  import os
  import boto3
  from chalice import Chalice


  app = Chalice(app_name='cdkdemo')
  dynamodb = boto3.resource('dynamodb')
  dynamodb_table = dynamodb.Table(os.environ.get('APP_TABLE_NAME', ''))


  @app.route('/users', methods=['POST'])
  def create_user():
      ...


  @app.route('/users/{username}', methods=['GET'])
  def get_user(username):
      ...

The name of the DynamoDB table is passed through an environment variable,
``APP_TABLE_NAME``.  We then create a ``dynamodb.Table`` resource given this
name.  This environment variable is generated and mapped in the CDK stack that
Chalice generated for us.  This is located in
``../infrastructure/stacks/chaliceapp.py``.

Let's look at the contents of the ``../infrastructure/stacks/chaliceapp.py``
file now.


.. code-block:: python

  import os

  from aws_cdk import (
      aws_dynamodb as dynamodb,
      core as cdk
  )
  from chalice.cdk import Chalice


  RUNTIME_SOURCE_DIR = os.path.join(
      os.path.dirname(os.path.dirname(__file__)), os.pardir, 'runtime')


  class ChaliceApp(cdk.Stack):

      def __init__(self, scope: cdk.Construct, id: str, **kwargs) -> None:
          super().__init__(scope, id, **kwargs)
          self.dynamodb_table = self._create_ddb_table()
          self.chalice = Chalice(
              self, 'ChaliceApp', source_dir=RUNTIME_SOURCE_DIR,
              stage_config={
                  'environment_variables': {
                      'APP_TABLE_NAME': self.dynamodb_table.table_name
                  }
              }
          )
          self.dynamodb_table.grant_read_write_data(
              self.chalice.get_role('DefaultRole')
          )

      def _create_ddb_table(self):
          dynamodb_table = dynamodb.Table(
              self, 'AppTable',
              partition_key=dynamodb.Attribute(
                  name='PK', type=dynamodb.AttributeType.STRING),
              sort_key=dynamodb.Attribute(
                  name='SK', type=dynamodb.AttributeType.STRING
              ),
              removal_policy=cdk.RemovalPolicy.DESTROY)
          cdk.CfnOutput(self, 'AppTableName',
                        value=dynamodb_table.table_name)
          return dynamodb_table


Our CDK stack is using the Chalice construct from the ``chalice.cdk``
package.  This provides us two benefits.  First, we can generate CDK resources
and pass them into our Chalice application by mapping environment variables.
Second, we can take resources generated in our Chalice application and
reference them with the CDK API.  For example, we’re generating a DynamoDB
table in the ``self._create_ddb_table()`` method, and then mapping it into our
Chalice application by providing a ``stage_config`` override.  This dictionary
is merged with the existing Chalice configuration located in
./runtime/.chalice/config.json.  If we want to pass additional values into our
Chalice application we can update the environment_variables dictionary in our
stage_config.

We’re also able to retrieve references to our resources in our Chalice
application and reference them in our CDK stack.  For example, once we’ve
created our DynamoDB table we also need to grant the IAM role associated with
your Lambda function access to this table.  We do this by using the
``grant_read_write_data`` method on our table resource, and we provide a
reference to the default role that Chalice creates for us by using the
``self.chalice.get_role()`` method.


Next Steps
----------


Feel free to experiment with this sample app.  Add new resources to your
application by updating the ``infrastructure/stacks/chaliceapp.py`` file, map
CDK resources into your Chalice app through environment variables, and
redeploy your application by running ``cdk deploy`` from the
``infrastructure/`` directory.
