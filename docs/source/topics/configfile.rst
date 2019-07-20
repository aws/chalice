Configuration File
==================

Whenever you create a new project using
``chalice new-project``, a ``.chalice`` directory is created
for you.  In this directory is a ``config.json`` file that
you can use to control what happens when you ``chalice deploy``::


    $ tree -a
    .
    ├── .chalice
    │   └── config.json
    ├── app.py
    └── requirements.txt

    1 directory, 3 files


.. _stage-config:

Stage Specific Configuration
----------------------------

As of version 0.7.0 of chalice, you can specify configuration
that is specific to a chalice stage as well as configuration that should
be shared across all stages.  See the :doc:`stages` doc for more
information about chalice stages.

* ``stages`` - This value of this key is a mapping of chalice stage
  name to stage configuration.  Chalice assumes a default stage name
  of ``dev``.  If you run the ``chalice new-project`` command on
  chalice 0.7.0 or higher, this key along with the default ``dev``
  key will automatically be created for you.  See the examples
  section below for some stage specific configurations.

The following config values can either be specified per stage config
or as a top level key which is not tied to a specific key.  Whenever
a stage specific configuration value is needed, the ``stages`` mapping
is checked first.  If no value is found then the top level keys will
be checked.

* ``api_gateway_stage`` - The name of the API gateway stage.  This
  will also be the URL prefix for your API
  (``https://endpoint/prefix/your-api``).

* ``api_gateway_endpoint_type`` - The endpoint configuration of the
  deployed API Gateway which determines how the API will be accessed,
  can be EDGE, REGIONAL, PRIVATE. Note this value can only be set as a
  top level key and defaults to EDGE. For more information see
  https://amzn.to/2LofApt

* ``api_gateway_endpoint_vpce`` - When configuring a Private API a VPC
  Endpoint must be specified to configure a default resource policy on
  the API if an explicit policy is not specified.

* ``api_gateway_policy`` - The IAM resource policy for the REST API.
  Note this should be a dictionary, and several variables are
  interpolated in strings {account_id}, {region_name}, {rest_api_id}.

* ``minimum_compression_size`` - An integer value that indicates
  the minimum compression size to apply to the API gateway. If
  this key is specified in both a stage specific config option
  as well as a top level key, the stage specific key will
  override the top level key for the given stage. For more information
  check out the `Service Docs <https://docs.aws.amazon.com/apigateway/latest/developerguide/api-gateway-gzip-compression-decompression.html>`__

* ``manage_iam_role`` - ``true``/``false``.  Indicates if you
  want chalice to create and update the IAM role
  used for your application.  By default, this value is ``true``.
  However, if you have a pre-existing role you've created, you
  can set this value to ``false`` and a role will not be created
  or updated.
  ``"manage_iam_role": false`` means that you are responsible for
  managing the role and any associated policies associated with
  that role.  If this value is ``false`` you must specify
  an ``iam_role_arn``, otherwise an error is raised when you
  try to run ``chalice deploy``.

* ``iam_role_arn`` - If ``manage_iam_role`` is ``false``, you
  must specify this value that indicates which IAM role arn to
  use when configuration your application.  This value is only
  used if ``manage_iam_role`` is ``false``.

* ``autogen_policy`` - A boolean value that indicates if chalice
  should try to automatically generate an IAM policy based on
  analyzing your application source code.  The default value is
  ``true``.  If this value is ``false`` then chalice will load
  try to a local file in ``.chalice/policy-<stage-name>.json``
  instead of auto-generating a policy from source code analysis.

* ``iam_policy_file`` - When ``autogen_policy`` is false, chalice
  will try to load an IAM policy from disk instead of auto-generating
  one based on source code analysis.  The default location of this
  file is ``.chalice/policy-<stage-name>.json``, e.g
  ``.chalice/policy-dev.json``, ``.chalice/policy-prod.json``, etc.
  You can change the filename by providing this ``iam_policy_file``
  config option.  This filename is relative to the ``.chalice``
  directory.

* ``environment_variables`` - A mapping of key value pairs.  These
  key value pairs will be set as environment variables in your
  application.  All environment variables must be strings.
  If this key is specified in both a stage specific config option
  as well as a top level key, the stage specific environment
  variables will be merged into the top level keys.  See the
  examples section below for a concrete example.

* ``lambda_timeout`` - An integer representing the function execution time,
  in seconds, at which AWS Lambda should terminate the function. The
  default ``lambda_timeout`` is ``60`` seconds.

* ``lambda_memory_size`` - An integer representing the amount of memory, in
  MB, your Lambda function is given. AWS Lambda uses this memory size
  to infer the amount of CPU allocated to your function. The default
  ``lambda_memory_size`` value is ``128``. The value must be a multiple of
  64 MB.

* ``tags`` - A mapping of key value pairs. These key value pairs will
  be set as the tags on the resources running your deployed
  application. All tag keys and values must be strings. Similar to
  ``environment_variables``, if a key is specified in both a stage
  specific config option as well as a top level key, the stage specific
  tags will be merged into the top level keys. By default, all chalice
  deployed resources are tagged with the key ``'aws-chalice'`` whose
  value is ``'version={chalice-version}:stage={stage-name}:app={app-name}'``.
  Currently only the following chalice deployed resources are tagged:
  Lambda functions.

* ``subnet_ids`` - A list of subnet ids for VPC configuration.  This
  value can be provided per stage as well as per Lambda function.
  In order for this value to take effect, you must also provide the
  ``security_group_ids`` value.  When both values are provided and
  ``autogen_policy`` is True, chalice will automatically update your
  IAM role with the necessary permissions to create, describe, and delete
  ENIs.  If you are managing the IAM role policy yourself, make sure
  to update your permissions accordingly, as described in the
  `AWS Lambda VPC documentation`_.

* ``security_group_ids`` - A list of security groups for VPC configuration.
  This value can be provided per stage as well as per Lambda function.
  In order for this value to take effect, you must also provide the
  ``subnet_ids`` value.

* ``reserved_concurrency`` - An integer representing each function's reserved
  concurrency.  This value can be provided per stage as well as per Lambda
  function. AWS Lambda reserves this value of concurrency to each lambda
  deployed in this stage. If the value is set to 0, invocations to this
  function are blocked. If the value is unset, there will be no reserved
  concurrency allocations. For more information, see `AWS Documentation on
  managing concurrency`_.

* ``layers`` - A list of Lambda Layers arns. This value can be provided
  per stage as well as per Lambda function. See `AWS Lambda Layers
  Configuration`_.


.. _lambda-config:

Lambda Specific Configuration
-----------------------------

In addition to a chalice stage, there are also some configuration values
that can be specified per Lambda function.  A chalice app can have many
stages, and a stage can have many Lambda functions.  To configure
per lambda configuration, you add a ``lambda_functions`` key in your
stage configuration::

  {
    "version": "2.0",
    "app_name": "app",
    "stages": {
      "dev": {
        "lambda_functions": {
          "foo": {
            "lambda_timeout": 120
          }
        }
      }
    }
  }

Each key in the ``lambda_functions`` dictionary is the name of a Lambda
function in your app.  The value is a dictionary of configuration that
will be applied to that function.  These are the configuration options
that can be applied per function:

* ``iam_policy_file``
* ``lambda_memory_size``
* ``lambda_timeout``
* ``iam_role_arn``
* ``manage_iam_role``
* ``autogen_policy``
* ``environment_variables``
* ``tags``
* ``subnet_ids``
* ``security_group_ids``
* ``reserved_concurrency``
* ``layers``


See the :ref:`stage-config` section above for a description
of these config options.

Examples
--------

Below are examples that show how you can configure your chalice app.


IAM Roles and Policies
~~~~~~~~~~~~~~~~~~~~~~


Here's an example for configuring IAM policies across stages::

  {
    "version": "2.0",
    "app_name": "app",
    "stages": {
      "dev": {
        "autogen_policy": true,
        "api_gateway_stage": "dev"
      },
      "beta": {
        "autogen_policy": false,
        "iam_policy_file": "beta-app-policy.json"
      },
      "prod": {
        "manage_iam_role": false,
        "iam_role_arn": "arn:aws:iam::...:role/prod-role"
      }
    }
  }

In this config file we're specifying three stages, ``dev``, ``beta``,
and ``prod``.  In the ``dev`` stage, chalice will automatically
generate an IAM policy based on analyzing the application source code.
For the ``beta`` stage, chalice will load the
``.chalice/beta-app-policy.json`` file and use it as the policy to
associate with the IAM role for that stage.  In the ``prod`` stage,
chalice won't modify any IAM roles.  It will just set the IAM role
for the Lambda function to be ``arn:aws:iam::...:role/prod-role``.

Here's an example that show config precedence::


  {
    "version": "2.0",
    "app_name": "app",
    "api_gateway_stage": "api",
    "stages": {
      "dev": {
      },
      "beta": {
      },
      "prod": {
        "api_gateway_stage": "prod",
        "manage_iam_role": false,
        "iam_role_arn": "arn:aws:iam::...:role/prod-role"
      }
    }
  }

In this config file, both the ``dev`` and ``beta`` stage will
have an API gateway stage name of ``api`` because they will
default to the top level ``api_gateway_stage`` key.
However, the ``prod`` stage will have an API gateway stage
name of ``prod`` because the ``api_gateway_stage`` is specified
in ``{"stages": {"prod": ...}}`` mapping.



Environment Variables
~~~~~~~~~~~~~~~~~~~~~


In the following example, environment variables are specified
both as top level keys as well as per stage.  This allows us to
provide environment variables that all stages should have as well
as stage specific environment variables::


  {
    "version": "2.0",
    "app_name": "app",
    "environment_variables": {
      "SHARED_CONFIG": "foo",
      "OTHER_CONFIG": "from-top"
    },
    "stages": {
      "dev": {
        "environment_variables": {
          "TABLE_NAME": "dev-table",
          "OTHER_CONFIG": "dev-value"
        }
      },
      "prod": {
        "environment_variables": {
          "TABLE_NAME": "prod-table",
          "OTHER_CONFIG": "prod-value"
        }
      }
    }
  }

For the above config, the ``dev`` stage will have the
following environment variables set::

  {
    "SHARED_CONFIG": "foo",
    "TABLE_NAME": "dev-table",
    "OTHER_CONFIG": "dev-value",
  }

The ``prod`` stage will have these environment variables set::

  {
    "SHARED_CONFIG": "foo",
    "TABLE_NAME": "prod-table",
    "OTHER_CONFIG": "prod-value",
  }


Per Lambda Examples
~~~~~~~~~~~~~~~~~~~

Suppose we had the following chalice app:

.. code-block:: python

    from chalice import Chalice

    app = Chalice(app_name='demo')

    @app.lambda_function()
    def foo(event, context):
        pass

    @app.lambda_function()
    def bar(event, context):
        pass


Given these two functions, we'd like to configure the functions
as follows:

* Both functions should have an environment variable ``OWNER`` with value
  ``dev-team``.
* The ``foo`` function should have an autogenerated IAM policy managed by
  chalice.
* The ``foo`` function should be run in a VPC with subnet ids ``sn-1`` and
  ``sn-2``, with security groups ``sg-10`` and ``sg-11``.  Chalice should
  also automatically configure the IAM policy with permissions to modify
  EC2 network interfaces.
* The ``foo`` function should have two connected layers as ``layer-arn-1`` and
  ``layer-arn-2``. Chalice should automatically configure the IAM policy.
* The ``bar`` function should use a pre-existing IAM role that was created
  outside of chalice.  Chalice should not perform an IAM role management for
  the ``bar`` function.
* The ``bar`` function should have an environment variable ``TABLE_NAME`` with
  value ``mytable``.

We can accomplish all this with this config file::

  {
    "stages": {
      "dev": {
        "environment_variables": {
          "OWNER": "dev-team"
        }
        "api_gateway_stage": "api",
        "lambda_functions": {
          "foo": {
            "subnet_ids": ["sn-1", "sn-2"],
            "security_group_ids": ["sg-10", "sg-11"],
            "layers": ["layer-arn-1", "layer-arn-2"],
          },
          "bar": {
            "manage_iam_role": false,
            "iam_role_arn": "arn:aws:iam::my-role-name",
            "environment_variables": {"TABLE_NAME": "mytable"}
          }
        }
      }
    },
    "version": "2.0",
    "app_name": "demo"
  }

.. _AWS Lambda VPC documentation: https://docs.aws.amazon.com/lambda/latest/dg/vpc.html#vpc-configuring
.. _AWS Documentation on managing concurrency: https://docs.aws.amazon.com/lambda/latest/dg/concurrent-executions.html
.. _AWS Lambda Layers Configuration: https://docs.aws.amazon.com/lambda/latest/dg/configuration-layers.html
