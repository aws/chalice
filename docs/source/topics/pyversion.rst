Python Version Support
======================

Chalice supports all versions of python supported by AWS Lambda, which is
currently Python 3.6 and greater.  You can see the list of
supported python versions for Lambda in their
`docs <https://docs.aws.amazon.com/lambda/latest/dg/lambda-python.html>`__.

Chalice will automatically pick which version of python to use for Lambda
based on the major version of python you are using.  You don't have to
explicitly configure which version of python you want to use. For example::

    $ python --version
    Python 3.6.1
    $ chalice new-project test-versions
    $ cd test-versions
    $ chalice package test-package
    $ grep -C 3 python test-package/sam.json
        "APIHandler": {
          "Type": "AWS::Serverless::Function",
          "Properties": {
            "Runtime": "python3.6",
            "Handler": "app.app",
            "CodeUri": "./deployment.zip",
            "Events": {

    # Similarly, if we were to run "chalice deploy" we'd
    # use python3.6 for the runtime.
    $ chalice --debug deploy
    Initiating first time deployment...
    Deploying to: dev
    ...
    "Runtime":"python3.6"
    ...
    https://rest-api-id.execute-api.us-west-2.amazonaws.com/api/


In the example above, we're using python 3.6.1 so chalice automatically
selects the ``python3.6`` runtime for lambda.  If we were using python 3.9.6,
chalice would automatically select ``python3.9`` as the runtime.

Chalice will emit a warning if the minor version does not match a python
version supported by Lambda.  Chalice will select the closest Lambda version
in this scenario, as shown in the table below.

We strongly encourage you to develop your application using the same
major/minor version of python you plan on using on AWS Lambda.


Changing Python Runtime Versions
================================

The version of the python runtime to use in AWS Lambda can be reconfigured
whenever you deploy your chalice app.  This allows you to migrate to newer
Python versions in AWS Lambda by creating a new virtual environment that uses
python3.  For example, suppose you have an existing chalice app that uses
Python 3.6 ::

    $ python --version
    Python 3.6.1
    $ chalice deploy
    ...
    https://endpoint/api

To upgrade the application to use Python 3.9, create a python3 virtual environment
and redeploy.

::

    $ deactivate
    $ python3 -m venv /tmp/venv3
    $ source /tmp/venv3/bin/activate
    $ python --version
    Python 3.9.6
    $ chalice deploy
    ...
