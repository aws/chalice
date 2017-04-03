Upgrade Notes
=============

This document provides additional documentation
on upgrading your version of chalice.  If you're just
interested in the high level changes, see the
`CHANGELOG.rst <https://github.com/awslabs/chalice/blob/master/CHANGELOG.rst>`__)
file.


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
