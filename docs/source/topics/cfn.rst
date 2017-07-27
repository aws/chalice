AWS CloudFormation Support
==========================

When you run ``chalice deploy``, chalice will deploy your application using the
`AWS SDK for Python <http://boto3.readthedocs.org/>`__).  Chalice also provides
functionality that allows you to manage deployments yourself using
cloudformation.  This is provided via the ``chalice package`` command.

When you run this command, chalice will generate the AWS Lambda deployment
package that contains your application as well as a `Serverless Application
Model (SAM) <https://github.com/awslabs/serverless-application-model>`__
template.  You can then use a tool like the AWS CLI, or any cloudformation
deployment tools you use, to deploy your chalice application.

Considerations
==============

Using the ``chalice package`` command is useful when you don't want to
use ``chalice deploy`` to manage your deployments.  There's several reasons
why you might want to do this:

* You have pre-existing infrastructure and tooling set up to manage
  cloudformation stacks.
* You want to integrate with other cloudformation stacks to manage
  all your AWS resources, including resources outside of your chalice
  app.
* You'd like to integrate with `AWS CodePipeline
  <https://aws.amazon.com/codepipeline/>`__ to automatically deploy
  changes when you push to a git repo.

Keep in mind that you can't switch between ``chalice deploy`` and
``chalice package`` + CloudFormation for deploying your app.

If you choose to use ``chalice package`` and CloudFormation to deploy
your app, you won't be able to switch back to ``chalice deploy``.
Running ``chalice deploy`` would create an entirely new set of AWS
resources (API Gateway Rest API, AWS Lambda function, etc).

Example
=======

In this example, we'll create a chalice app and deploy it using
the AWS CLI.

First install the necessary packages::

    $ virtualenv /tmp/venv
    $ . /tmp/venv/bin/activate
    $ pip install chalice awscli
    $ chalice new-project test-cfn-deploy
    $ cd test-cfn-deploy

At this point we've installed chalice and the AWS CLI and we have
a basic app created locally.  Next we'll run the ``package`` command
and look at its contents::

    $ $ chalice package /tmp/packaged-app/
    Creating deployment package.
    $ ls -la /tmp/packaged-app/
    -rw-r--r--   1 j         wheel  3355270 May 25 14:20 deployment.zip
    -rw-r--r--   1 j         wheel     3068 May 25 14:20 sam.json

    $ unzip -l /tmp/packaged-app/deployment.zip  | tail -n 5
        17292  05-25-17 14:19   chalice/app.py
          283  05-25-17 14:19   chalice/__init__.py
          796  05-25-17 14:20   app.py
     --------                   -------
      9826899                   723 files

    $ head < /tmp/packaged-app/sam.json
    {
      "AWSTemplateFormatVersion": "2010-09-09",
      "Outputs": {
        "RestAPIId": {
          "Value": {
            "Ref": "RestAPI"
          }
        },
        "APIHandlerName": {
          "Value": {

As you can see in the above example, the ``package`` command created a
directory that contained two files, a ``deployment.zip`` file, which is the
Lambda deployment package, and a ``sam.json`` file, which is the SAM template
that can be deployed using CloudFormation.  Next we're going to use the AWS CLI
to deploy our app.  To this, we'll first run the ``aws cloudformation package``
command, which will take our deployment.zip file and upload to an S3 bucket
we specify::

    $ aws cloudformation package \
         --template-file /tmp/packaged-app/sam.json \
         --s3-bucket myapp-bucket \
         --output-template-file /tmp/packaged-app/packaged.yaml

Now we can deploy our app using the ``aws cloudformation deploy`` command::

    $ aws cloudformation deploy \
        --template-file /tmp/packaged-app/packaged.yaml \
        --stack-name test-cfn-stack \
        --capabilities CAPABILITY_IAM
    Waiting for changeset to be created..
    Waiting for stack create/update to complete
    Successfully created/updated stack - test-cfn-stack

This will take a few minutes to complete, but once it's done, the endpoint url
will be available as an output::

    $ aws cloudformation describe-stacks --stack-name test-cfn-stack \
      --query "Stacks[].Outputs[?OutputKey=='EndpointURL'][] | [0].OutputValue"
    "https://abc29hkq0i.execute-api.us-west-2.amazonaws.com/api/"

    $ http "https://abc29hkq0i.execute-api.us-west-2.amazonaws.com/api/"
    HTTP/1.1 200 OK
    Connection: keep-alive
    Content-Length: 18
    Content-Type: application/json
    ...

    {
        "hello": "world"
    }


