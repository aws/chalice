Chalice Stages
==============

Chalice has the concept of stages, which are completely
separate sets of AWS resources.  When you first create a chalice
project and run commands such as ``chalice deploy`` and ``chalice url``,
you don't have to specify any stage values or stage configuration.
This is because chalice will use a stage named ``dev`` by default.

You may eventually want to have multiple stages of your application.  A
common configuration would be to have a ``dev``, ``beta`` and ``prod``
stage.  A ``dev`` stage would be used by developers to test out new
features.  Completed features would be deployed to ``beta``, and the
``prod`` stage would be used for serving production traffic.

Chalice can help you manage this.

To create a new chalice stage, specify the ``--stage`` argument.
If the stage does not exist yet, it will be created for you::

    $ chalice deploy --stage prod

By creating a new chalice stage, a new API Gateway rest API, Lambda
function, and potentially (depending on config settings) a new IAM role
will be created for you.


Example
-------

Let's say we have a new app::

    $ chalice new-project myapp
    $ cd myapp
    $ chalice deploy
    ...
    https://mmnkdi.execute-api.us-west-2.amazonaws.com/v1/

We've just created our first stage, ``dev``.  We can iterate on our
application and continue to run ``chalice deploy`` to deploy our code
to the ``dev`` stage.  Let's say we want to now create a ``prod`` stage.
To do this, we can run::

    $ chalice deploy --stage prod
    ...
    https://wk9fhx.execute-api.us-west-2.amazonaws.com/v1/

We now have two completely separate rest APIs::

    $ chalice url --stage dev
    https://mmnkdi.execute-api.us-west-2.amazonaws.com/v1/

    $ chalice url --stage prod
    https://wk9fhx.execute-api.us-west-2.amazonaws.com/v1/

Additionally, we can see all our deployed values by looking
at the ``.chalice/deployed.json`` file::

    $ cat .chalice/deployed.json
    {
      "dev": {
        "region": "us-west-2",
        "api_handler_name": "myapp-dev",
        "api_handler_arn": "arn:aws:lambda:...:function:myapp",
        "rest_api_id": "wk9fhx",
        "chalice_version": "0.7.0",
        "api_gateway_stage": "dev",
        "backend": "api"
      },
      "prod": {
        "rest_api_id": "mmnkdi",
        "chalice_version": "0.7.0",
        "region": "us-west-2",
        "backend": "api",
        "api_handler_name": "myapp-prod",
        "api_handler_arn": "arn:aws:lambda:...:function:myapp-prod",
        "api_gateway_stage": "dev"
      }
    }
