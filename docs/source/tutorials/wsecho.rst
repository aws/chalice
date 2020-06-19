Echo Server Example
===================

An echo server is a simple server that echos any message it receives back to
the client that sent it.

First install a copy of Chalice in a fresh environment, create a new project
and cd into the directory::

  $ pip install -U chalice
  $ chalice new-project echo-server
  $ cd echo-server

Our Chalice application will need boto3 as a dependency for both API Gateway
to send websocket messages. Let's add a boto3 to the ``requirements.txt``
file::

  $ echo "boto3>=1.9.91" > requirements.txt


Now that the requirement has been added. Let's install it locally since our
next script will need it as well::

  $ pip install -r requirements.txt


Next replace the contents of the ``app.py`` file with the code below.

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
assigned to ``app.websocket_api.session``.
This is needed because in order to send websocket responses to API Gateway we
need to construct a boto3 client. Chalice does not take a direct dependency
on boto3 or botocore, so we need to provide the Session ourselves.

.. code-block:: python

   from boto3.session import Session
   app.websocket_api.session = Session()


Next we enable the experimental feature ``WEBSOCKETS``. Websockets are an
experimental feature and are subject to API changes. This includes all aspects
of the Websocket API exposted in Chalice. Including any public members of
``app.websocket_api``, and the three decorators ``on_ws_connect``,
``on_ws_message``, and ``on_ws_disconnect``.

.. code-block:: python

   app.experimental_feature_flags.update([
       'WEBSOCKETS'
   ])


To register a websocket handler, and cause Chalice to deploy an
API Gateway Websocket API we use the ``app.on_ws_message()`` decorator.
The event parameter here is a wrapper object with some convenience
parameters attached. The most useful are ``event.connection_id`` and
``event.body``. The ``connection_id`` is an API Gateway specific identifier
that allows you to refer to the connection that sent the message. The ``body``
is the content of the message.

.. code-block:: python

   @app.on_ws_message()
   def message(event):


Since this is an echo server, the message handler simply reads the content it
received on the socket, and rewrites it back to the same socket. To send a
message to a socket we call ``app.websocket_api.send(connection_id, message)``.
In this case, we just use the same ``connection_id`` we got the message from,
and use the ``body`` we got from the event as the ``message`` to send.

.. code-block:: python

   app.websocket_api.send(
       connection_id=event.connection_id,
       message=event.body,
    )


Finally, we catch the exception ``WebsocketDisconnectedError`` which is raised
by ``app.websocket_api.send`` if the provided ``connection_id`` is not
connected anymore. In our case this doesn't really matter since we don't have
anything tracking our connections. The error has a ``connection_id`` property
that contains the offending connection id.

.. code-block:: python

   except WebsocketDisconnectedError as e:
       pass  # Disconnected so we can't send the message back.


Now that we understand the code, lets deploy it with ``chalice deploy``::

   $ chalice deploy
     Creating deployment package.
     Creating IAM role: echo-server-dev
     Creating lambda function: echo-server-dev-websocket_message
     Creating websocket api: echo-server-dev-websocket-api
     Resources deployed:
       - Lambda ARN: arn:aws:lambda:region:0123456789:function:echo-server-dev-websocket_message
       - Websocket API URL: wss://{websocket_api_id}.execute-api.region.amazonaws.com/api/

To test out the echo server we will use the  ``websocket-client`` package. You
install it from PyPI::

  $ pip install websocket-client


After deploying the Chalice app the output will contain a URL for connecting
to the websocket API labeled: ``- Websocket API URL:``. The
``websocket-client`` package installs a command line tool called ``wsdump.py``
which can be used to test websocket echo server::

  $ wsdump.py wss://{websocket_api_id}.execute-api.region.amazonaws.com/api/
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

If something goes wrong, you can check the chalice error logs using the
following command::

  $ chalice logs -n websocket_message

.. note::
   If you encounter an Internal Server Error here it is likely that you forgot
   to include ``boto3>=1.9.91`` in the ``requirements.txt`` file.

To tear down the example. Just run::

  $ chalice delete
    Deleting Websocket API: {websocket_api_id}
    Deleting function: arn:aws:lambda:us-west-2:0123456789:function:echo-server-dev-websocket_message
    Deleting IAM role: echo-server-dev

Next Steps
----------

In this tutorial, we created an echo server with websockets.
If you'd like to try something more ambitious, you can follow our
tutorial for creating a sample :doc:`Chat application with websocket <wschat>`.
