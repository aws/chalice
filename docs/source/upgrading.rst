Upgrade Notes
=============

This document provides additional documentation
on upgrading your version of chalice.  If you're just
interested in the high level changes, see the
`CHANGELOG.rst <https://github.com/awslabs/chalice/blob/master/CHANGELOG.rst>`__)
file.


0.7.0
-----

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
