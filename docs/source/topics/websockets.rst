Websockets
==========

.. warning::

  Websockets are considered an experimental API.  You'll need to opt-in
  to this feature using the ``WEBSOCKETS`` feature flag:

  .. code-block:: python

    app = Chalice('myapp')
    app.experimental_feature_flags.extend([
        'WEBSOCKETS'
    ])

  See :doc:`experimental` for more information.


Echo Server Example
===================

Below is an example of a simple echo server written with Chalice.

.. code-block:: text
   :caption: requirements.txt

    boto3>=1.9.91


.. code-block:: python
   :caption: app.py
   :linenos:

    from boto3.session import Session

    from chalice import Chalice
    from chalice import WebsocketDisconnectedError

    app = Chalice(app_name="echo-server")
    app.websocket_api.session = Session()
    app.experimental_feature_flags.update([
        'WEBSOCKETS'
    ])


    @app.on_ws_message()
    def message(event):
    try:
        app.websocket_api.send(
        connection_id=event.connection_id,
        message=event.body,
        )
    except WebsocketDisconnectedError as e:
        pass  # Disconnected so we can't send the message back.


Stepping through this app line by line, the first thing to note is that we
need to import and instantiate a boto3 session. This session is manually
assigned to ``app.websocket_api.session`` property on line 7. This is needed
because in order to send websocket responses to API Gateway we need to
construct a boto3 client. Chalice does not take a direct dependency on boto3
or botocore, so we need to provide the Session ourselves.

Next we enable the experimental feature ``WEBSOCKETS`` on line 8-10. As noted
at the top of this file, websockets are an experimental feature and are
subject to API changes.

To acutally register a websocket handler, and cause Chalice to deploy an
API Gateway Websocket API we use the ``app.on_ws_message()`` decorator on
line 13. The event parameter here is a wrapper object with some convenience
parameters attached. The most useful are ``event.connection_id`` and
``event.body``. The ``connection_id`` is an API Gateway specific identifier
that allows you to refer to the connection that sent the message. The ``body``
is the content of the message.

Since this is an echo server, the content of the message handler simply returns
the message it received on the socket, back to the same socket. To send a
message to a socket we call ``app.websocket_api.send(connection_id, message)``
on line 16-20. In this case, we just use the same ``connection_id`` we got the
message from, and use the ``body`` we got from the event as the ``message`` to
send.

Finally, we catch the exception ``WebsocketDisconnectError`` which is raised
by ``app.websocket_api.send`` if the provided ``connetion_id`` is not connected
anymore. In our case this doesn't really matter since we don't have anything
tracking our connections.

To test out the echo server you can install ``websocket-client`` from pypi::

  pip install websocket-client


After deploying the Chalice app the output will contain a URL for connecting
to the websocket API labeled: ``- Websocket API URL:``. The
``websocket-client`` package installs a command line tool called ``wsdump.py``
which can be used to test websocket echo server pretty easily::

  $ wsdump.py wss://{websocket_api_id}.execute-api.us-west-2.amazonaws.com/api/
  Press Ctrl+C to quit
  > foo
  < foo
  > bar
  < bar
  > foo bar baz
  < foo bar baz
  >


Every message sent to the server (lines that start with ``>``) result in a
message sent to us (lines that start with ``<``) with the same content.
