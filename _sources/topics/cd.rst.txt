===========================
Continuous Deployment (CD)
===========================

Chalice can be used to set up a basic Continuous Deployment pipeline. The
``chalice deploy`` command is good for getting up and running quickly with
Chalice, but in a team environment properly managing permissions and sharing
and updating the ``deployed.json`` file will get messy.

One way to scale up your chalice app is to create a continuous deployment
pipeline. The pipeline can run tests on code changes and, if they pass, promote
the new build to a testing stage. More checks can be put in place to manually
promote a build to production, or you can do so automatically. This model
greatly simplifies managing what resources belong to your Chalice app as they
are all stored in the Continuous Deployment pipeline.

Chalice can generate a CloudFormation template that will create a starter CD
pipeline. By default it contains an AWS CodeCommit repo, an AWS CodeBuild stage
for packaging your chalice app, and an AWS CodePipeline stage to deploy your
application using CloudFormation.

You can also configure a source repository hosted on GitHub instead of
a CodeCommit repository.

Pipeline Template Versions
==========================

This starter pipeline template can be generated using the ``generate-pipeline``
command.  There are two versions of this pipeline.  The older ``v1`` template
is the default (for backwards compatibility reasons), but the newer template
version, ``v2``, is recommended.  The version can be specified using the
``--pipeline-version`` option.  These are the differences between ``v1`` and
``v2`` templates:

* The ``v1`` templates use version ``0.1`` of the CodeBuild buildspec, whereas
  ``v2`` uses ``0.2`` of the CodeBuild buildspec.  Buildspec ``0.2`` is the
  recommended version to use with CodeBuild.  See their
  `documentation <https://docs.aws.amazon.com/codebuild/latest/userguide/build-spec-ref.html>`__
  for more information.
* The ``v2`` template uses `AWS Secrets Manager <https://aws.amazon.com/secrets-manager/>`__
  to configure access to a GitHub repository.
* The ``v2`` buildspec uses `runtime-versions <https://docs.aws.amazon.com/codebuild/latest/userguide/build-spec-ref.html#build-spec.phases.install.runtime-versions>`__
  to configure which version of Python to use instead of a Python
  version specific CodeBuild image.  For ``v2`` templates the
  ``aws/codebuild/amazonlinux2-x86_64-standard`` image.

**The v2 pipeline template requires Python 3.7 or higher.** If you're using
Python versions less than 3.7 you must use the ``v1`` pipeline template.


Usage example
=============

Setting up the deployment pipeline is a two step process. First use the
``chalice generate-pipeline`` command to generate a base CloudFormation
template. Second use the AWS CLI to deploy the CloudFormation template using
the ``aws cloudformation deploy`` command. Below is an example.

::

   $ chalice generate-pipeline --pipeline-version v2 pipeline.json
   $ aws cloudformation deploy --stack-name mystack
         --template-file pipeline.json --capabilities CAPABILITY_IAM
   Waiting for changeset to be created..
   Waiting for stack create/update to complete
   Successfully created/updated stack - mystack

.. note::
   To configure your Chalice app to use a GitHub repository instead of
   CodeCommit see the :ref:`cicd-github-repo` section below.


Once the CloudFormation template has finished creating the stack, you will have
several new AWS resources that make up a bare bones CD pipeline.

* **CodeCommit Repository** - The `CodeCommit <https://aws.amazon.com/codecommit/>`_
  repository is the entrypoint into the pipeline. Any code you want to deploy
  should be pushed to this remote.
* **CodePipeline Pipeline** - The
  `CodePipeline <https://aws.amazon.com/codepipeline/>`_ is what coordinates
  the build process, and pushes the released code out.
* **CodeBuild Project** - The `CodeBuild <https://aws.amazon.com/codebuild/>`_
  project is where the code bundle is built that will be pushed to Lambda. The
  default CloudFormation template will create a CodeBuild stage that builds
  a package using ``chalice package`` and then uploads those artifacts for
  CodePipeline to deploy.
* **S3 Buckets** - Two S3 buckets are created on your behalf.

  * **artifactbucketstore** - This bucket stores artifacts that are built by
    the CodeBuild project. The only artifact by default is the
    ``transformed.yaml`` created by the ``aws cloudformation package`` command.
  * **applicationbucket** - Stores the application bundle after the Chalice
    application has been packaged in the CodeBuild stage.
* Each resource is created with all the required IAM roles and policies.


CodeCommit repository
---------------------

The CodeCommit repository can be added as a git remote for deployment. This
makes it easy to kick off deployments. The developer doing the deployment only
needs to push the release code up to the CodeCommit repository master branch.
All the developer needs is keys that allow for push access to the CodeCommit
repository. This is a lot easier than managing a set of ``deployed.json``
resources across a repsoitory and manually doing ``chalice deploy`` whenever
a change needs to be deployed.

The default CodeCommit repository that is created is empty, you will have to
populate it with the Chalice application code. Permissions will also need to be
set up, you can find the documentation on how to do that
`here <https://docs.aws.amazon.com/codebuild/latest/userguide/setting-up.html>`_
.

You can retrieve the CodeCommit clone URL by searching for the
``SourceRepoURL`` in the CloudFormation stack output::

    $ aws cloudformation describe-stacks --stack-name mysack \
       --query "Stacks[0].Outputs[?OutputKey=='SourceRepoURL'] | [0].OutputValue"


CodePipeline
------------

CodePipeline is the main coordinator between all the other resources. It
watches for changes on the CodeCommit repository, and triggers builds in the
CodeBuild project. If the build succeeds then it will start a CloudFormation
deployment of the built artifacts to a beta stage. This should be treated as
a starting point, not a fully featured CD system.


CodeBuild build script
----------------------

By default Chalice will create the CodeBuild project with a default buildspec
that does the following.

.. code-block:: yaml

  version: 0.1
  phases:
    install:
      commands:
      - sudo pip install --upgrade awscli
      - aws --version
      - sudo pip install chalice
      - sudo pip install -r requirements.txt
      - chalice package /tmp/packaged
      - aws cloudformation package --template-file
          tmp/packaged/sam.json --s3-bucket ${APP_S3_BUCKET}
          --output-template-file transformed.yaml
  artifacts:
    type: zip
    files:
      - transformed.yaml

The CodeBuild stage installs both the AWS CLI and Chalice, then creates a
package out of your chalice project, pushing the package to the application
S3 bucket that was created for you. The transformed CloudFormation template
is the only artifact, and can be run by CodePipeline after the build has
succeeded.


Deploying to beta stage
-----------------------

Once the CodeBuild stage has finished building the Chalice package and
creating the ``transformed.yaml``, CodePipeline will take these artifacts and
use them to create or update the beta stage. The ``transformed.yaml``
is a CloudFormation template that CodePipeline will execute, all the code it
references has been uploaded to the application bucket by the AWS CLI in the
CodeBuild stage, so this is the only artifact we need.

Once the CodePipeline beta build stage is finished, the beta version of the app
is deployed and ready for testing.


Extending
---------

It is recommended to use this pipeline as a starting point. The default
template does not run any tests on the Chalice app before deploying to beta.
There is also no mechanism provided by Chalice for a production stage.
Ideally the CodeBuild stage would be used to run unit and functional tests
before deploying to beta. After the beta stage is up, integration tests can be
run against that endpoint, and if they all pass the beta stage could be
promoted to a production stage using the CodePipleine manual approval feature.

.. _cicd-github-repo:

Configuring a GitHub Repository
===============================

You can configure a GitHub repository instead of a CodeCommit repo when
setting up your deployment pipeline by specifying the ``--source github``
option.  When generating a CloudFormation template for a GitHub repository,
there are several parameters that are added to your template that allow
you to configure how to connect your GitHub repository with your CodePipeline.

You must store your OAuth token that enables access to a GitHub repository
in AWS Secrets Manager.  You then specify the secret name/id and the JSON
key name as CloudFormation parameters.  This values default to a secret
name of ``GithubRepoAccess`` and a JSON key name of ``OAuthToken``.

Below is an example of how to configure a GitHub repository as the
source for your deployment pipeline.

First create a `GitHub token <https://docs.github.com/en/github/authenticating-to-github/creating-a-personal-access-token>`__
that can be used in this template.  Next create a secret in AWS Secrets
Manager.  You can either follow the documentation
`here <https://docs.aws.amazon.com/secretsmanager/latest/userguide/manage_create-basic-secret.html>`__
or use the AWS CLI or any AWS SDK.  For this example, we'll use the AWS CLI
to create our secret.  Create a file named ``/tmp/secrets.json`` with these
contents::

    {"OAuthToken": "abcdefghhijklmnop"}

Be sure to replace the value of ``OAuthToken`` with the value of your GitHub
token you created.  Next we can create the secret using this command::

    $ aws secretsmanager create-secret --name GithubRepoAccess \
      --description "Token for Github Repo Access" \
      --secret-string file:///tmp/secrets.json

Now we can generate our deployment pipeline::

    $ aws generate-pipeline --pipeline-version v2 \
      --source github --buildspec-file buildspec.yml pipeline.json

This will create two files, a ``pipeline.json`` file containing our
deployment pipeline and a ``buildspec.yml`` file.  This buildspec file
lets us update what commands should be run as part of our build process
without having to redeploy our CloudFormation template.

We now add and commit our changes to our repository.

::

    $ git add buildspec.yml pipeline.json
    $ git commit -m "Add deployment pipeline template"
    $ git push

Now we're ready to deploy our CloudFormation template using the AWS CLI.  Be
sure to replace the ``GithubOwner`` and ``GithubRepoName`` with your own
values for your GitHub repository.  You'll also need to specify the
``GithubRepoSecretId`` and ``GithubRepoSecretJSONKey`` if you used values
other than the default vaues of ``GithubRepoAccess`` and ``OAuthToken`` when
creating your secret in Secrets Manager.

::

    $ aws cloudformation deploy --template-file pipeline.json \
      --stack-name MyChaliceApp --parameter-overrides \
      GithubOwner=repo-owner-name \
      GithubRepoName=repo-name \
      --capabilities CAPABILITY_IAM

We've now created a deployment pipeline that will automatically deploy our
Chalice app whenever we push to our GitHub repository.
