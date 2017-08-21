=====================
Pure Lambda Functions
=====================


Chalice provides abstractions over AWS Lambda functions, including:

* An API handler the coordinates with API Gateway for creating rest APIs.
* A custom authorizer that allows you to integrate custom auth logic in your
  rest API.
* A scheduled event that includes managing the CloudWatch Event rules, targets,
  and permissions.

However, chalice also supports managing pure Lambda functions that don't have
any abstractions built on top.  This is useful if you want to create a Lambda
function for something that's not supported by chalice or if you just want to
create Lambda functions but don't want to manage handling dependencies and
deployments yourself.

In order to do this, you can use the :ref:`Chalice.lambda_function` decorator
to denote that this python function is a pure lambda function that should
be invoked as is, without any input or output mapping.  When you use
this function, you must provide a function that maps to the same function
signature expected by AWS Lambda as `defined here`_.

Let's look at an example.

.. code-block:: python

    app = chalice.Chalice(app_name='foo')
    
    @app.route('/')
    def index():
        return {'hello': 'world'}

    @app.lambda_function()
    def custom_lambda_function(event, context):
        # Anything you want here.
        return {}

    @app.lambda_function(name='MyFunction')
    def other_lambda_function(event, context):
        # Anything you want here.
        return {}

In this example, we've updated the starter hello world app with
two extra Lambda functions.  When you run ``chalice deploy`` Chalice will create
three Lambda functions.  The first lambda function is for the API handler
used by API gateway.  The second and third lambda function will be pure lambda
functions.  These two additional lambda functions won't be hooked up to anything.
You'll need to manage connecting them to any additional AWS Resources on your
own.


Limitations:

* You must provide at least 1 ``@app.route`` decorator.  It is not
  possible to deploy only lambda functions without an API Gateway API.


.. _defined here: http://docs.aws.amazon.com/lambda/latest/dg/python-programming-model-handler-types.html
