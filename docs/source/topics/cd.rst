Continuous Deployment (CD)
===========================

Chalice can be used to set up a basic Continuous Deployment pipeline. The
``chalice deploy`` command is good for getting up and running quickly with
Chalice, but in a team environment properly managing permissions and sharing
and updating the ``deployed.yml`` file will get messy.

One way to scale up your chalice app is to create a continuous deployment
pipeline. The pipeline can run tests on code changes and, if they pass, promote
the new build to a testing stage. More checks can be put in place to manually
promote a build to production, or you can do so automatically. This model
greatly simplifies managing what resources belong to your Chalice app as they
are all stored in the Continuous Deployment pipeline.

Chalice can generate a CloudFormation template that will create a starter CD
pipeline. It contains a CodeCommit repo, a CodeBuild stage for
packaging your chalice app, and a CodePipeline stage to deploy your
application using CloudFormation.


Usage example
-------------

Setting up the deployment pipeline is a two step process. First use the
``chalice generate-pipeline`` command to generate a base CloudFormation
template. Second use the AWS CLI to deploy the CloudFormation template using
the ``aws cloudformation deploy`` command. Below is an example.

::

   $ chalice generate-pipeline pipeline.yml
   $ aws cloudformation deploy --stack-name mystack
         --template-file pipeline.yml --capabilities CAPABILITY_IAM
   Waiting for changeset to be created..
   Waiting for stack create/update to complete
   Successfully created/updated stack - mystack

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
repository. This is a lot easier than managing a set of ``deployed.yml``
resources across a repsoitory and manually doing ``chalice deploy`` whenever
a change needs to be deployed.

The default CodeCommit repository that is created is empty, you will have to
populate it with the Chalice application code. Permissions will also need to be
set up, you can find the documentation on how to do that
`here <https://docs.aws.amazon.com/codebuild/latest/userguide/setting-up.html>`_
.


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
          tmp/packaged/sam.yml --s3-bucket ${APP_S3_BUCKET}
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
