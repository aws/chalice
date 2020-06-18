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


Chalice supports websockets through integration with an API Gateway Websocket
API. If any of the decorators are present in a Chalice app, then an API
Gateway Websocket API will be deployed and wired to Lambda Functions.


Responding to websocket events
------------------------------

In a Chalice app the websocket API is accessed through the three decorators
``on_ws_connect``, ``on_ws_message``, ``on_ws_disconnect``. These handle a new
websocket connection, an incoming message on an existing connection, and a
connection being cleaned up respectively.

A decorated websocket handler function takes one argument ``event`` with the
type :ref:`WebsocketEvent <websocket-api>`. This class allows easy access to
information about the API Gateway Websocket API, and information about the
particular socket the handler is being invoked to serve.

Below is a simple working example application that prints to CloudWatch Logs
for each of the events.

.. code-block:: python

    from boto3.session import Session
    from chalice import Chalice

    app = Chalice(app_name='test-websockets')
    app.experimental_feature_flags.update([
        'WEBSOCKETS',
    ])
    app.websocket_api.session = Session()


    @app.on_ws_connect()
    def connect(event):
        print('New connection: %s' % event.connection_id)


    @app.on_ws_message()
    def message(event):
        print('%s: %s' % (event.connection_id, event.body))


    @app.on_ws_disconnect()
    def disconnect(event):
        print('%s disconnected' % event.connection_id)


Sending a message over a websocket
----------------------------------

To send a message to a websocket client Chalice, use the
:ref:`app.websocket_api.send() <websocket-send>` method. This method will work in any
of the decorated functions outlined in the above section.

Two pieces of information are needed to send a message. The identifier of the
websocket, and the contents for the message. Below is a simple example that when
it receives a message, it sends back the message ``"I got your message!"`` over
the same socket.

.. code-block:: python

    from boto3.session import Session
    from chalice import Chalice

    app = Chalice(app_name='test-websockets')
    app.experimental_feature_flags.update([
        'WEBSOCKETS',
    ])
    app.websocket_api.session = Session()


    @app.on_ws_message()
    def message(event):
        app.websocket_api.send(event.connection_id, 'I got your message!')


See :ref:`websocket-tutorial` for completely worked example applications.
