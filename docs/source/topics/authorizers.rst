Authorization
=============

Chalice supports multiple mechanisms for authorization.  This topic
covers how you can integrate authorization into your Chalice applications.

In Chalice, all the authorizers are configured per-route and specified
using the ``authorizer`` kwarg to an ``@app.route()`` call.  You
control which type of authorizer to use based on what's passed as the
``authorizer`` kwarg.  You can use the same authorizer instance for
multiple routes.

The first set of authorizers chalice supports cover the scenario where
you have some existing authorization mechanism that you just want your
Chalice app to use.

Chalice also supports built-in authorizers, which allows Chalice to
manage your custom authorizers as part of ``chalice deploy``.  This is
covered in the Built-in Authorizers section.


AWS IAM Authorizer
------------------

The IAM Authorizer allows you to control access to API Gateway with
`IAM permissions`_

To associate an IAM authorizer with a route in chalice, you use the
:class:`IAMAUthorizer` class:

.. code-block:: python

    from chalice import IAMAuthorizer

    authorizer = IAMAuthorizer()

    @app.route('/iam-auth', methods=['GET'], authorizer=authorizer)
    def authenticated():
        return {"success": True}


See the `API Gateway documentation
<https://docs.aws.amazon.com/apigateway/latest/developerguide/permissions.html>`__
for more information on controlling access to API Gateway with IAM permissions.

Amazon Cognito User Pools
-------------------------

In addition to using IAM roles and policies with the :class:`IAMAuthorizer` you
can also use a `Cognito user pools`_ to control who can access your Chalice
app.  A cognito user pool serves as your own identity provider to maintain a
user directory.

To integrate Cognito user pools with Chalice, you'll need to have an existing
cognito user pool configured.


.. code-block:: python

    from chalice import CognitoUserPoolAuthorizer

    authorizer = CognitoUserPoolAuthorizer(
        'MyPool', provider_arns=['arn:aws:cognito:...:userpool/name'])

    @app.route('/user-pools', methods=['GET'], authorizer=authorizer)
    def authenticated():
        return {"success": True}


For more information about using Cognito user pools with API Gateway,
see the `Use Amazon Cognito User Pools documentation
<https://docs.aws.amazon.com/apigateway/latest/developerguide/apigateway-integrate-with-cognito.html>`__.


Custom Authorizers
------------------

API Gateway also lets you write custom authorizers using a Lambda function.
You can configure a Chalice route to use a pre-existing Lambda function as
a custom authorizer.  If you also want to write and manage your Lambda
authorizer using Chalice, see the next section, Built-in Authorizers.

To connect an existing Lambda function as a custom authorizer in chalice,
you use the ``CustomAuthorizer`` class:

.. code-block:: python

    from chalice import CustomAuthorizer

    authorizer = CustomAuthorizer(
        'MyCustomAuth', header='Authorization',
        authorizer_uri=('arn:aws:apigateway:region:lambda:path/2015-03-31'
                        '/functions/arn:aws:lambda:region:account-id:'
                        'function:FunctionName/invocations'))

    @app.route('/custom-auth', methods=['GET'], authorizer=authorizer)
    def authenticated():
        return {"success": True}


Built-in Authorizers
--------------------

The ``IAMAuthorizer``, ``CognitoUserPoolAuthorizer``, and the
``CustomAuthorizer`` classes are all for cases where you have existing
resources for managing authorization and you want to wire them together with
your Chalice app.  A Built-in authorizer is used when you'd like to write your
custom authorizer in Chalice, and have the additional Lambda functions managed
when you run ``chalice deploy/delete``.  This section will cover how to use the
built-in authorizers in chalice.

Creating an authorizer in chalice requires you use the ``@app.authorizer``
decorator to a function.  The function must accept a single arg, which will be
an instance of :class:`AuthRequest`.  The function must return a
:class:`AuthResponse`.  As an example, we'll port the example from the `API
Gateway documentation`_.  First, we'll show the code and then walk through it:

.. code-block:: python

    from chalice import Chalice, AuthResponse

    app = Chalice(app_name='demoauth1')


    @app.authorizer()
    def demo_auth(auth_request):
        token = auth_request.token
        # This is just for demo purposes as shown in the API Gateway docs.
        # Normally you'd call an oauth provider, validate the
        # jwt token, etc.
        # In this exampe, the token is treated as the status for demo
        # purposes.
        if token == 'allow':
            return AuthResponse(routes=['/'], principal_id='user')
        else:
            # By specifying an empty list of routes,
            # we're saying this user is not authorized
            # for any URLs, which will result in an
            # Unauthorized response.
            return AuthResponse(routes=[], principal_id='user')


    @app.route('/', authorizer=demo_auth)
    def index():
        return {'context': app.current_request.context}


In the example above we define a built-in authorizer by decorating
the ``demo_auth`` function with the ``@app.authorizer()`` decorator.
Note you must use ``@app.authorizer()`` and not ``@app.authorizer``.
A built-in authorizer function has this type signature::

    def auth_handler(auth_request: AuthRequest) -> AuthResponse: ...

Within the auth handler you must determine if the request is
authorized or not.  The ``AuthResponse`` contains the allowed
URLs as well as the principal id of the user.  You can optionally
return a dictionary of key value pairs (as the ``context`` kwarg).
This dictionary will be passed through on subsequent requests.
In our example above we're not using the context dictionary.
API Gateway will convert all the values in the ``context``
dictionary to string values.

Now let's deploy our app.  As usual, we just need to run
``chalice deploy`` and chalice will automatically deploy all the
necessary Lambda functions for us.

Now when we try to make a request, we'll get an Unauthorized error::

  $ http https://api.us-west-2.amazonaws.com/api/
  HTTP/1.1 401 Unauthorized

  {
      "message": "Unauthorized"
  }

If we add the appropriate authorization header, we'll see the call succeed::

  $ http https://api.us-west-2.amazonaws.com/api/ 'Authorization: allow'
  HTTP/1.1 200 OK

  {
      "context": {
          "accountId": "12345",
          "apiId": "api",
          "authorizer": {
              "principalId": "user"
          },
          "httpMethod": "GET",
          "identity": {
              "accessKey": null,
              "accountId": null,
              "apiKey": "",
              "caller": null,
              "cognitoAuthenticationProvider": null,
              "cognitoAuthenticationType": null,
              "cognitoIdentityId": null,
              "cognitoIdentityPoolId": null,
              "sourceIp": "1.1.1.1",
              "user": null,
              "userAgent": "HTTPie/0.9.9",
              "userArn": null
          },
          "path": "/api/",
          "requestId": "d35d2063-56be-11e7-9ce1-dd61c24a3668",
          "resourceId": "id",
          "resourcePath": "/",
          "stage": "dev"
      }
  }

The low level API for API Gateway's custom authorizer feature requires
that an IAM policy must be returned.  The :class:`AuthResponse` class we're
using is a wrapper over building the IAM policy ourself.  If you want
low level control and would prefer to construct the IAM policy yourself
you can return a dictionary of the IAM policy instead of an instance of
:class:`AuthResponse`.  If you do that, the dictionary is returned
without modification back to API Gateway.

For more information on custom authorizers, see the
`Use API Gateway Custom Authorizers
<https://docs.aws.amazon.com/apigateway/latest/developerguide/apigateway-use-lambda-authorizer.html>`__
page in the API Gateway user guide.


Scopes
-------------------------

OAuth 2.0 and OpenID Connect (OIDC) scopes can be used to implement access
controls in your Chalice app. Scopes are supported when using the Cognito
Authorizer, Custom Authorizers, and Built-In Authorizers.

To integrate Scopes with a Cognito Authorizer in Chalice, you'll need to have
an existing `Cognito user pools`_ and `Cognito resource server`_ configured.
Scopes for Cognito Authorizers need to include the full identifier
which is ``resourceServerIdentifier/scopeName``.

Scopes can be configured per-authorizer using the ``scopes`` attribute.

.. code-block:: python

    from chalice import CognitoUserPoolAuthorizer

    authorizer = CognitoUserPoolAuthorizer(
        'MyPool', provider_arns=['arn:aws:cognito:...:userpool/name'],
        scopes=["https://mychaliceapp.example.com/todos.read"])

    @app.route('/user-pools', methods=['GET'], authorizer=authorizer)
    def authenticated():
        return {"success": True}

Scopes can be configured per-route for an Authorizer using ``with_scopes``.

.. code-block:: python

    from chalice import CognitoUserPoolAuthorizer

    authorizer = CognitoUserPoolAuthorizer(
        'MyPool', provider_arns=['arn:aws:cognito:...:userpool/name'])

    @app.route(
        '/user-pools',
        methods=['GET'],
        authorizer=authorizer.with_scopes(["https://mychaliceapp.example.com/todos.read"]))
    def authenticated():
        return {"success": True}

Scopes can also be used with custom authorizers and built-in authorizers.
These authorizers will need to inspect the access token to determine if access
should be granted based on the scopes configured for the authorizer and route.


.. _IAM permissions: https://docs.aws.amazon.com/IAM/latest/UserGuide/access_controlling.html
.. _Cognito User Pools: https://docs.aws.amazon.com/cognito/latest/developerguide/cognito-user-identity-pools.html
.. _Cognito Resource Server: https://docs.aws.amazon.com/cognito/latest/developerguide/cognito-user-pools-define-resource-servers.html
.. _API Gateway documentation: https://docs.aws.amazon.com/apigateway/latest/developerguide/apigateway-use-lambda-authorizer.html
