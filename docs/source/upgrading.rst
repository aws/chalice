Upgrade Notes
=============

This document provides additional documentation
on upgrading your version of chalice.  If you're just
interested in the high level changes, see the
`CHANGELOG.md <https://github.com/aws/chalice/blob/master/CHANGELOG.md>`__)
file.

.. _v1-2-0:

1.2.0
-----

This release features a rewrite of the Chalice deployer
(`#604 <https://github.com/aws/chalice/issues/604>`__).
This is a backwards compatible change, and should not have any
noticeable changes with deployments with the exception of
fixing deployer bugs (e.g. https://github.com/aws/chalice/issues/604).
This code path affects the ``chalice deploy``, ``chalice delete``, and
``chalice package`` commands.

While this release is backwards compatible, you will notice several
changes when you upgrade to version 1.2.0.

The output of ``chalice deploy`` has changed in order to give
more details about the resources it creates along with a more detailed
summary at the end::

    $ chalice deploy
    Creating deployment package.
    Creating IAM role: myapp-dev
    Creating lambda function: myapp-dev-foo
    Creating lambda function: myapp-dev
    Creating Rest API
    Resources deployed:
      - Lambda ARN: arn:aws:lambda:us-west-2:12345:function:myapp-dev-foo
      - Lambda ARN: arn:aws:lambda:us-west-2:12345:function:myapp-dev
      - Rest API URL: https://abcd.execute-api.us-west-2.amazonaws.com/api/

Also, the files used to store deployed values has changed.  These files are
used internally by the ``chalice deploy/delete`` commands and you typically
do not interact with these files directly.  It's mentioned here in case
you notice new files in your ``.chalice`` directory.  Note that these files
are *not* part of the public interface of Chalice and are documented here
for completeness and to help with debugging issues.

In versions < 1.2.0, the value of deployed resources was stored in
``.chalice/deployed.json`` and looked like this::

  {
    "dev": {
      "region": "us-west-2",
      "api_handler_name": "demoauth4-dev",
      "api_handler_arn": "arn:aws:lambda:us-west-2:123:function:myapp-dev",
      "rest_api_id": "abcd",
      "lambda_functions": {
        "myapp-dev-foo": {
          "type": "pure_lambda",
          "arn": "arn:aws:lambda:us-west-2:123:function:myapp-dev-foo"
        }
      },
      "chalice_version": "1.1.1",
      "api_gateway_stage": "api",
      "backend": "api"
    },
    "prod": {...}
  }


In version 1.2.0, the deployed resources are split into multiple files, one
file per chalice stage.  These files are in the
``.chalice/deployed/<stage.json>``, so if you had a dev and a prod chalice
stage you'd have ``.chalice/deployed/dev.json`` and
``.chalice/deployed/prod.json``.  The schema has also changed and looks
like this::


  $ cat .chalice/deployed/dev.json
  {
    "schema_version": "2.0",
    "resources": [
      {
        "role_name": "myapp-dev",
        "role_arn": "arn:aws:iam::123:role/myapp-dev",
        "name": "default-role",
        "resource_type": "iam_role"
      },
      {
        "lambda_arn": "arn:aws:lambda:us-west-2:123:function:myapp-dev-foo",
        "name": "foo",
        "resource_type": "lambda_function"
      },
      {
        "lambda_arn": "arn:aws:lambda:us-west-2:123:function:myapp-dev",
        "name": "api_handler",
        "resource_type": "lambda_function"
      },
      {
        "name": "rest_api",
        "rest_api_id": "abcd",
        "rest_api_url": "https://abcd.execute-api.us-west-2.amazonaws.com/api",
        "resource_type": "rest_api"
      }
    ],
    "backend": "api"
  }

When you run ``chalice deploy`` for the first time after upgrading to version
1.2.0, chalice will automatically converted ``.chalice/deployed.json`` over to
the format as you deploy a given stage.

.. warning::

  Once you upgrade to 1.2.0, chalice will only update the new
  ``.chalice/deployed/<stage>.json``.  This means you cannot downgrade
  to earlier versions of chalice unless you manually update
  ``.chalice/deployed.json`` as well.


The ``chalice package`` command has also been updated to use the
deployer.  This results in several changes compared to the previous
version:

* Pure lambdas are supported
* Scheduled events are supported
* Parity between the behavior of ``chalice deploy`` and ``chalice package``

As part of this change, the CFN resource names have been updated
to use ``CamelCase`` names.  Previously, chalice converted your
python function names to CFN resource names by removing all
non alphanumeric characters and appending an md5 checksum,
e.g ``my_function -> myfunction3bfc``.  With this new packager
update, the resource name would be converted as
``my_function -> MyFunction``.  Note, the ``Outputs`` section
renames unchanged in order to preserve backwards compatibility.
In order to fix parity issues with ``chalice deploy`` and
``chalice package``, we now explicitly create an IAM role
resource as part of the default configuration.


.. _v1-0-0b2:

1.0.0b2
-------

The url parameter names and the function argument names must match.
Previously, the routing code would use positional args ``handler(*args)``
to invoke a view function.  In this version, kwargs are now used instead:
``handler(**view_args)``.  For example, this code will no longer work:

.. code-block:: python

    @app.route('/{a}/{b}')
    def myview(first, second)
        return {}


The example above must be updated to:


.. code-block:: python

    @app.route('/{a}/{b}')
    def myview(a, b)
        return {}

Now that functions are invoked with kwargs, the order doesn't matter.  You may
also write the above view function as:


.. code-block:: python

    @app.route('/{a}/{b}')
    def myview(b, a)
        return {}


This was done to have consistent behavior with other web frameworks such as
Flask.

.. _v1-0-0b1:

1.0.0b1
-------

The ``Chalice.define_authorizer`` method has been removed.  This has been
deprecated since v0.8.1.  See :doc:`topics/authorizers` for updated
information on configuring authorizers in Chalice as well as the
original deprecation notice in the :ref:`v0-8-1` upgrade notes.

The optional deprecated positional parameter in the ``chalice deploy`` command
for specifying the API Gateway stage has been removed.  If you want to
specify the API Gateway stage, you can use the ``--api-gateway-stage``
option in the ``chalice deploy`` command::

    # Deprecated and removed in 1.0.0b1
    $ chalice deploy prod

    # Equivalent and updated way to specify an API Gateway stage:
    $ chalice deploy --api-gateway-stage prod


.. _v0-9-0:

0.9.0
-----

The 0.9.0 release changed the type of ``app.current_request.raw_body`` to
always be of type ``bytes()``.  This only affects users that were using
python3.  Previously you would get a type ``str()``, but with the introduction
of `binary content type support
<https://github.com/aws/chalice/issues/348>`__, the ``raw_body`` attribute
was made to consistently be of type ``bytes()``.


.. _v0-8-1:

0.8.1
-----

The 0.8.1 changed the preferred way of specifying authorizers for view
functions.  You now specify either an instance of
``chalice.CognitoUserPoolAuthorizer`` or ``chalice.CustomAuthorizer``
to an ``@app.route()`` function using the ``authorizer`` argument.

Deprecated:

.. code-block:: python

    @app.route('/user-pools', methods=['GET'], authorizer_name='MyPool')
    def authenticated():
        return {"secure": True}

    app.define_authorizer(
        name='MyPool',
        header='Authorization',
        auth_type='cognito_user_pools',
        provider_arns=['arn:aws:cognito:...:userpool/name']
    )

Equivalent, and preferred way

.. code-block:: python

    from chalice import CognitoUserPoolAuthorizer

    authorizer = CognitoUserPoolAuthorizer(
        'MyPool', header='Authorization',
        provider_arns=['arn:aws:cognito:...:userpool/name'])

    @app.route('/user-pools', methods=['GET'], authorizer=authorizer)
    def authenticated():
        return {"secure": True}


The ``define_authorizer`` is still available, but is now deprecated and will
be removed in future versions of chalice.  You can also use the new
``authorizer`` argument to provider a ``CustomAuthorizer``:


.. code-block:: python

    from chalice import CustomAuthorizer

    authorizer = CustomAuthorizer(
        'MyCustomAuth', header='Authorization',
        authorizer_uri=('arn:aws:apigateway:region:lambda:path/2015-03-01'
                        '/functions/arn:aws:lambda:region:account-id:'
                        'function:FunctionName/invocations'))

    @app.route('/custom-auth', methods=['GET'], authorizer=authorizer)
    def authenticated():
        return {"secure": True}


.. _v0-7-0:

0.7.0
-----

The 0.7.0 release adds several major features to chalice.  While the majority
of these features are introduced in a backwards compatible way, there are a few
backwards incompatible changes that were made in order to support these new
major features.

Separate Stages
~~~~~~~~~~~~~~~

Prior to this version, chalice had a notion of a "stage" that corresponded to
an API gateway stage.  You can create and deploy a new API gateway stage by
running ``chalice deploy <stage-name>``.  In 0.7.0, stage support was been
reworked such that a chalice stage is a completely separate set of AWS
resources.  This means that if you have two chalice stages, say ``dev`` and
``prod``, then you will have two separate sets of AWS resources, one set per
stage:

* Two API Gateway Rest APIs
* Two separate Lambda functions
* Two separate IAM roles

The :doc:`topics/stages` doc has more details on the new chalice stages
feature.  This section highlights the key differences between the old stage
behavior and the new chalice stage functionality in 0.7.0.  In order to ease
transition to this new model, the following changes were made:

* A new ``--stage`` argument was added to the ``deploy``, ``logs``, ``url``,
  ``generate-sdk``, and ``package`` commands.  If this value is specified
  and the stage does not exist, a new chalice stage with that name will
  be created for you.
* The existing form ``chalice deploy <stage-name>`` has been deprecated.
  The command will still work in version 0.7.0, but a deprecation warning
  will be printed to stderr.
* If you want the pre-existing behavior of creating a new API gateway stage
  (while using the same Lambda function), you can use the
  ``--api-gateway-stage`` argument.  This is the replacement for the
  deprecated form ``chalice deploy <stage-name>``.
* The default stage if no ``--stage`` option is provided is ``dev``.  By
  defaulting to a ``dev`` stage, the pre-existing behavior of not
  specifying a stage name, e.g ``chalice deploy``, ``chalice url``, etc.
  will still work exactly the same.
* A new ``stages`` key is supported in the ``.chalice/config.json``.  This
  allows you to specify configuration specific to a chalice stage.
  See the :doc:`topics/configfile` doc for more information about stage
  specific configuration.
* Setting ``autogen_policy`` to false will result in chalice looking
  for a IAM policy file named ``.chalice/policy-<stage-name>.json``.
  Previously it would look for a file named ``.chalice/policy.json``.
  You can also explicitly set this value to
  In order to ease transition, chalice will check for a
  ``.chalice/policy.json`` file when depoying to the ``dev`` stage.
  Support for ``.chalice/policy.json`` will be removed in future
  versions of chalice and users are encouraged to switch to the
  stage specific ``.chalice/policy-<stage-name>.json`` files.


See the :doc:`topics/stages` doc for more details on the new chalice stages
feature.

**Note, the AWS resource names it creates now have the form
``<app-name>-<stage-name>``, e.g. ``myapp-dev``, ``myapp-prod``.**

We recommend using the new stage specific resource names.  However, If you
would like to use the existing resource names for a specific stage, you can
create a ``.chalice/deployed.json`` file that specifies the existing values::

  {
    "dev": {
      "backend": "api",
      "api_handler_arn": "lambda-function-arn",
      "api_handler_name": "lambda-function-name",
      "rest_api_id": "your-rest-api-id",
      "api_gateway_stage": "dev",
      "region": "your region (e.g us-west-2)",
      "chalice_version": "0.7.0",
    }
  }


This file is discussed in the next section.

Deployed Values
~~~~~~~~~~~~~~~

In version 0.7.0, the way deployed values are stored and retrieved
has changed.  In prior versions, only the ``lambda_arn`` was saved,
and its value was written to the ``.chalice/config.json`` file.
Any of other deployed values that were needed (for example the
API Gateway rest API id) was dynamically queried by assuming the
resource names matches the app name.  In this version of chalice,
a separate ``.chalice/deployed.json`` file is written on every
deployement which contains all the resources that have been created.
While this should be a transparent change, you may noticed
issues if you run commands such as ``chalice url`` and ``chalice logs``
without first deploying.  To fix this issue, run ``chalice deploy``
and version 0.7.0 of chalice so a ``.chalice/deployed.json`` will
be created for you.


Authorizer Changes
~~~~~~~~~~~~~~~~~~

**The ``authorizer_id`` and ``authorization_type`` args are
no longer supported in ``@app.route(...)`` calls.**


They have been replaced with an ``authorizer_name`` parameter and an
``app.define_authorizer`` method.

This version changed the internals of how an API gateway REST API is created.
Prior to 0.7.0, the AWS SDK for Python was used to make the appropriate service
API calls to API gateway include ``create_rest_api`` and ``put_method /
put_method_response`` for each route.  In version 0.7.0, this internal
mechanism was changed to instead generate a swagger document.  The rest api is
then created or updated by calling ``import_rest_api`` or ``put_rest_api`` and
providing the swagger document.  This simplifies the internals and also unifies
the code base for the newly added ``chalice package`` command (which uses a
swagger document internally).  One consequence of this change is that the
entire REST API must be defined in the swagger document.  With the previous
``authorizer_id`` parameter, you would create/deploy a rest api, create your
authorizer, and then provide that ``authorizer_id`` in your ``@app.route``
calls.  Now they must be defined all at once in the ``app.py`` file:


.. code-block:: python

    app = chalice.Chalice(app_name='demo')

    @app.route('/auth-required', authorizer_name='MyUserPool')
    def foo():
        return {}

    app.define_authorizer(
        name='MyUserPool',
        header='Authorization',
        auth_type='cognito_user_pools',
        provider_arns=['arn:aws:cognito:...:userpool/name']
    )


.. _v0-6-0:

0.6.0
-----

This version changed how the internals of how API gateway resources are created
by chalice.  The integration type changed from ``AWS`` to ``AWS_PROXY``.  This
was to enable additional functionality, notable to allows users to provide
non-JSON HTTP responses and inject arbitrary headers to the HTTP responses.
While this change to the internals is primarily internal, there are several
user-visible changes.


* Uncaught exceptions with ``app.debug = False`` (the default value)
  will result in a more generic ``InternalServerError`` error.  The
  previous behavior was to return a ``ChaliceViewError``.
* When you enabled debug mode via ``app.debug = True``, the HTTP
  response will contain the python stack trace as the entire request
  body.  This is to improve the readability of stack traces.
  For example::

    $ http https://endpoint/dev/
    HTTP/1.1 500 Internal Server Error
    Content-Length: 358
    Content-Type: text/plain

    Traceback (most recent call last):
      File "/var/task/chalice/app.py", line 286, in __call__
        response = view_function(*function_args)
      File "/var/task/app.py", line 12, in index
        return a()
      File "/var/task/app.py", line 16, in a
        return b()
      File "/var/task/app.py", line 19, in b
        raise ValueError("Hello, error!")
    ValueError: Hello, error!

* Content type validation now has error responses that match the same error
  response format used for other chalice built in responses.  Chalice was
  previously relying on API gateway to perform the content type validation.
  As a result of the ``AWS_PROXY`` work, this logic has moved into the chalice
  handler and now has a consistent error response::

    $ http https://endpoint/dev/ 'Content-Type: text/plain'
    HTTP/1.1 415 Unsupported Media Type
    Content-Type: application/json

    {
        "Code": "UnsupportedMediaType",
        "Message": "Unsupported media type: text/plain"
    }
* The keys in the ``app.current_request.to_dict()`` now match the casing used
  by the ``AWS_PPROXY`` lambda integration, which are ``lowerCamelCased``.
  This method is primarily intended for introspection purposes.
