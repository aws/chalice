Upgrade Notes
=============

This document provides additional documentation
on upgrading your version of chalice.  If you're just
interested in the high level changes, see the
`CHANGELOG.rst <https://github.com/awslabs/chalice/blob/master/CHANGELOG.rst>`__)
file.


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
