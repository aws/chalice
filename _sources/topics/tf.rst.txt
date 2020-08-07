Terraform Support
=================

When you run ``chalice deploy``, chalice will deploy your application using the
`AWS SDK for Python <http://boto3.readthedocs.io/en/docs/>`__).  Chalice also
provides functionality that allows you to manage deployments yourself using
terraform.  This is provided via the ``chalice package --pkg-format terraform``
command.

When you run this command, chalice will generate the AWS Lambda
deployment package that contains your application and a `Terraform
<https://www.terraform.io>`__ configuration file. You can then use the
terraform cli to deploy your chalice application.

Considerations
--------------

Using the ``chalice package`` command is useful when you don't want to
use ``chalice deploy`` to manage your deployments.  There's several reasons
why you might want to do this:

* You have pre-existing infrastructure and tooling set up to manage
  Terraform deployments.
* You want to integrate with other Terraform resources to manage all
  your application resources, including resources outside of your
  chalice app.
* You'd like to integrate with `AWS CodePipeline
  <https://aws.amazon.com/codepipeline/>`__ to automatically deploy
  changes when you push to a git repo.

Keep in mind that you can't switch between ``chalice deploy`` and
``chalice package`` + Terraform for deploying your app.

If you choose to use ``chalice package`` and Terraform to deploy
your app, you won't be able to switch back to ``chalice deploy``.
Running ``chalice deploy`` would create an entirely new set of AWS
resources (API Gateway Rest API, AWS Lambda function, etc).

Example
-------

In this example, we'll create a chalice app and deploy it using
the AWS CLI.

First install the necessary packages::

    $ virtualenv /tmp/venv
    $ . /tmp/venv/bin/activate
    $ pip install chalice awscli
    $ chalice new-project test-tf-deploy
    $ cd test-tf-deploy

At this point we've installed chalice and the AWS CLI and we have
a basic app created locally.  Next we'll run the ``package`` command::

    $ chalice package --pkg-format terraform /tmp/packaged-app/
    Creating deployment package.
    $ ls -la /tmp/packaged-app/
    -rw-r--r--   1 j         wheel  3355270 May 25 14:20 deployment.zip
    -rw-r--r--   1 j         wheel     3068 May 25 14:20 chalice.tf.json

    $ unzip -l /tmp/packaged-app/deployment.zip  | tail -n 5
        17292  05-25-17 14:19   chalice/app.py
          283  05-25-17 14:19   chalice/__init__.py
          796  05-25-17 14:20   app.py
     --------                   -------
      9826899                   723 files


As you can see in the above example, the ``package --pkg-format``
command created a directory that contained two files, a
``deployment.zip`` file, which is the Lambda deployment package, and a
``chalice.tf.json`` file, which is the Terraform template that can be
deployed using Terraform.  Next we're going to use the Terraform CLI
to deploy our app.

Note terraform will deploy run against all terraform files in this
directory, so we can add additional resources for our application by
adding terraform additional files here. The Chalice terraform template
includes two static data values (`app` and `stage` names) that we can
optionally use when constructing these additional resources,
ie. `${data.null_data_source.chalice.outputs.app}`

First let's run Terraform init to install the AWS Terraform Provider::

    $ cd /tmp/packaged-app
    $ terraform init

Now we can deploy our app using the ``terraform apply`` command::

  $ terraform apply
  data.aws_region.chalice: Refreshing state...
  data.aws_caller_identity.chalice: Refreshing state...

  An execution plan has been generated and is shown below.
  Resource actions are indicated with the following symbols:
  + create

  ... (omit plan output)

  Plan: 14 to add, 0 to change, 0 to destroy.

  Do you want to perform these actions?
    Terraform will perform the actions described above.
    Only 'yes' will be accepted to approve.
  Enter a value: yes

  ... (omit apply output)

  Apply complete! Resources: 14 added, 0 changed, 0 destroyed.

  Outputs:

  EndpointURL = https://7bnxriulj5.execute-api.us-east-1.amazonaws.com/dev
  RestApiId = 7bnxriulj5

This will take a minute to complete, but once it's done, the endpoint url
will be available as an output which we can then curl::

    $ http "$(terraform output EndpointURL)"
    HTTP/1.1 200 OK
    Connection: keep-alive
    Content-Length: 18
    Content-Type: application/json
    ...

    {
        "hello": "world"
    }
