.. _websocket-tutorial:

Websocket Tutorials
===================

Echo Server Example
-------------------

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

Chat Server Example
-------------------


Note::

  This example is for illustration purposes and does not represent best
  practices.

A simple chat server example application. This example will walk through
deploying a chat application with separate chat rooms and nicknames. It uses
a DynamoDB table to store state like connection IDs between websocket messages.


First install a copy of Chalice in a fresh environment, create a new project
and cd into the directory::

  $ pip install -U chalice
  $ chalice new-project chalice-chat-example
  $ cd chalice-chat-example


Our Chalice application will need boto3 as a dependency for both DynamoDB
access and in order to communicate back with API Gateway to send websocket
messages. Let's add a boto3 to the ``requirements.txt`` file::

  $ echo "boto3>=1.9.91" > requirements.txt


Now that the requirement has been added. Let's install it locally since our
next script will need it as well::

  $ pip install -r requirements.txt

To set up the DynamoDB table use the following script. Create a new file
in the root of the project called ``create-resources.py``.


.. code-block:: python
   :caption: create-resources.py

   import json

   import boto3


   def iam_policy(table_arn):
       resources = [
           table_arn,
           '%s/index/ReverseLookup' % table_arn,
       ]
       return {
           "Version": "2012-10-17",
           "Statement": [
               {
                   "Effect": "Allow",
                   "Action": [
                       "dynamodb:DeleteItem",
                       "dynamodb:PutItem",
                       "dynamodb:GetItem",
                       "dynamodb:UpdateItem",
                       "dynamodb:Query",
                       "dynamodb:Scan"
                   ],
                   "Resource": resources,
               },
               {
                   "Effect": "Allow",
                   "Action": [
                       "logs:CreateLogGroup",
                       "logs:CreateLogStream",
                       "logs:PutLogEvents"
                   ],
                   "Resource": "arn:aws:logs:*:*:*"
               },
               {
                   "Effect": "Allow",
                   "Action": [
                       "execute-api:ManageConnections"
                   ],
                   "Resource": "arn:aws:execute-api:*:*:*/@connections/*"
               }
           ]
       }


   def main():
       ddb = boto3.client('dynamodb')
       result = ddb.create_table(
           AttributeDefinitions=[
               {
                   'AttributeName': 'PK',
                   'AttributeType': 'S',
               },
               {
                   'AttributeName': 'SK',
                   'AttributeType': 'S',
               },
           ],
           TableName='ChaliceChatTable',
           KeySchema=[
               {
                   'AttributeName': 'PK',
                   'KeyType': 'HASH',
               },
               {
                   'AttributeName': 'SK',
                   'KeyType': 'RANGE',
               },
           ],
           ProvisionedThroughput={
               'ReadCapacityUnits': 5,
               'WriteCapacityUnits': 5,
           },
           GlobalSecondaryIndexes=[
               {
                   'IndexName': 'ReverseLookup',
                   'KeySchema': [
                       {
                           'AttributeName': 'SK',
                           'KeyType': 'HASH',
                       },
                       {
                           'AttributeName': 'PK',
                           'KeyType': 'RANGE',
                       },
                   ],
                   'Projection': {
                       'ProjectionType': 'ALL',
                   },
                   'ProvisionedThroughput': {
                       'ReadCapacityUnits': 1,
                       'WriteCapacityUnits': 1,
                   }
               },
           ],
       )
       table_arn = result['TableDescription']['TableArn']
       with open('.chalice/config.json', 'r') as f:
           config = json.loads(f.read())

       config['stages']['dev']['environment_variables'] = {
           'TABLE': 'ChaliceChatTable',
       }
       config['autogen_policy'] = False

       with open('.chalice/config.json', 'w') as f:
           f.write(json.dumps(config, indent=2))

       with open('.chalice/policy-dev.json', 'w') as f:
           f.write(json.dumps(iam_policy(table_arn), indent=2))


   if __name__ == "__main__":
        main()


The current directory layout should now look like this::

 tree -a .
 .
 ├── .chalice
 │   └── config.json
 ├── .gitignore
 ├── app.py
 ├── create-resources.py
 └── requirements.txt

 1 directory, 5 files

Run the python script we just created (``create-resources.py``), which will
deploy our DynamoDB table, and setup the Chalice configuration to have an
environment variable with the table name in it, as well as a policy that allows
the Lambda function to access the table::

  $ python create-resources.py


You can verify the configuration is correct by checking config file looks
correct::

  $ cat .chalice/config.json
  {
    "version": "2.0",
    "app_name": "chalice-chat-example",
    "stages": {
      "dev": {
        "api_gateway_stage": "api",
        "environment_variables": {
          "TABLE": "ChaliceChatTable"
        }
      }
    },
    "autogen_policy": false
  }

And the policy file is correct::

  $ cat .chalice/policy-dev.json
  {
    "Version": "2012-10-17",
    "Statement": [
      {
        "Effect": "Allow",
        "Action": [
          "dynamodb:DeleteItem",
          "dynamodb:PutItem",
          "dynamodb:GetItem",
          "dynamodb:UpdateItem",
          "dynamodb:Query",
          "dynamodb:Scan"
        ],
        "Resource": [
          "arn:aws:dynamodb:{region}:{id}:table/ChaliceChatTable",
          "arn:aws:dynamodb:{region}:{id}:table/ChaliceChatTable/index/ReverseLookup"
        ]
      },
      {
        "Effect": "Allow",
        "Action": [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ],
        "Resource": "arn:aws:logs:*:*:*"
      },
      {
        "Effect": "Allow",
        "Action": [
          "execute-api:ManageConnections"
        ],
        "Resource": "arn:aws:execute-api:*:*:*/@connections/*"
      }
    ]
  }


Next let's fill out the ``app.py`` file since it is pretty simple. Most of this
example is contained in the ``chalicelib/`` directory.

.. code-block:: python
   :caption: chalice-chat-example/app.py

   from boto3.session import Session

   from chalice import Chalice

   from chalicelib import Storage
   from chalicelib import Sender
   from chalicelib import Handler

   app = Chalice(app_name="chalice-chat-example")
   app.websocket_api.session = Session()
   app.experimental_feature_flags.update([
       'WEBSOCKETS'
   ])

   STORAGE = Storage.from_env()
   SENDER = Sender(app, STORAGE)
   HANDLER = Handler(STORAGE, SENDER)


   @app.on_ws_connect()
   def connect(event):
       STORAGE.create_connection(event.connection_id)


   @app.on_ws_disconnect()
   def disconnect(event):
       STORAGE.delete_connection(event.connection_id)


   @app.on_ws_message()
   def message(event):
       HANDLER.handle(event.connection_id, event.body)


Similar to the previous example. We need to use ``boto3`` to construct a
Session and pass it to ``app.websocket_api.session``. We opt into the
usage of the ``WEBSOCKET`` experimental feature. Most of the actual work is
done in some classes that we import from ``chalicelib/``. These classes are
detailed below, and the various parts are explained in comments and Doc
strings. In addition to the previous example, we register a handler for
``on_ws_connect`` and ``on_ws_disconnect`` to handle events from API gateway
when a new socket is trying to connect, or an existing socket is disconnected.


Finally before being able to deploy and test the app out, we need to fill out
the chalicelib directory. This is the bulk of the app and it is explained
inline in comments. Create a new directory called ``chalicelib`` and inside
that directory create an ``__init__.py`` file and fill it out with the
following file.

.. code-block:: python
   :caption: chalice-chat-example/chalicelib/__init__.py

   import os

   import boto3
   from boto3.dynamodb.conditions import Key

   from chalice import WebsocketDisconnectedError


   class Storage(object):
       """An abstraction to interact with the DynamoDB Table."""
       def __init__(self, table):
           """Initialize Storage object

           :param table: A boto3 dynamodb Table resource object.
           """
           self._table = table

       @classmethod
       def from_env(cls):
           """Create table from the environment.

           The environment variable TABLE is assumed to be present
           as it is set by the create-resources.py file.
           """
           table_name = os.environ.get('TABLE')
           table = boto3.resource('dynamodb').Table(table_name)
           return cls(table)

       def create_connection(self, connection_id):
           """Create a new connection object in the dtabase.

           When a new connection is created, we create a stub for
           it in the table. The stub uses a primary key of the
           connection_id and a sort key of username_. This translates
           to a connection with an unset username. The first message
           sent over the wire from the connection is to be used as the
           username, and this entry will be re-written.

           :param connection_id: The connection id to write to
               the table.
           """
           self._table.put_item(
               Item={
                   'PK': connection_id,
                   'SK': 'username_',
               },
           )

       def set_username(self, connection_id, old_name, username):
           """Set the username.

           The SK entry that goes with this conneciton id that starts
           with username_ is taken to be the username. The previous
           entry needs to be deleted, and a new entry needs to be
           written.

           :param connection_id: Connection id of the user trying to
               change their name.

           :param old_name: The original username. Since this is part of
               the key, it needs to be deleted and re-created rather than
               updated.

           :param username: The new username the user wants.
           """
           self._table.delete_item(
               Key={
                   'PK': connection_id,
                   'SK': 'username_%s' % old_name,
               },
           )
           self._table.put_item(
               Item={
                   'PK': connection_id,
                   'SK': 'username_%s' % username,
               },
           )

       def list_rooms(self):
           """Get a list of all rooms that exist.

           Scan through the table looking for SKs that start with room_
           which indicates a room that a user is in. Collect a unique set
           of those and return them.
           """
           r = self._table.scan()
           rooms = set([item['SK'].split('_', 1)[1] for item in r['Items']
                        if item['SK'].startswith('room_')])
           return rooms

       def set_room(self, connection_id, room):
           """Set the room a user is currently in.

           The room a user is in is in the form of an SK that starts with
           room_ prefix.

           :param connection_id: The connection id to move to a room.

           :param room: The room name to join.
           """
           self._table.put_item(
               Item={
                   'PK': connection_id,
                   'SK': 'room_%s' % room,
               },
           )

       def remove_room(self, connection_id, room):
           """Remove a user from a room.

           The room a user is in is in the form of an SK that starts with
           room_ prefix. To leave a room we need to delete this entry.

           :param connection_id: The connection id to move to a room.

           :param room: The room name to join.
           """
           self._table.delete_item(
               Key={
                   'PK': connection_id,
                   'SK': 'room_%s' % room,
               },
           )

       def get_connection_ids_by_room(self, room):
           """Find all connection ids that go to a room.

           This is needed whenever we broadcast to a room. We collect all
           their connection ids so we can send messages to them. We use a
           ReverseLookup table here which inverts the PK, SK relationship
           creating a partition called room_{room}. Everything in that
           partition is a connection in the room.

           :param room: Room name to get all connection ids from.
           """
           r = self._table.query(
               IndexName='ReverseLookup',
               KeyConditionExpression=(
                   Key('SK').eq('room_%s' % room)
               ),
               Select='ALL_ATTRIBUTES',
           )
           return [item['PK'] for item in r['Items']]

       def delete_connection(self, connection_id):
           """Delete a connection.

           Called when a connection is disconnected and all its entries need
           to be deleted.

           :param connection_id: The connection partition to delete from
               the table.
           """
           try:
               r = self._table.query(
                   KeyConditionExpression=(
                       Key('PK').eq(connection_id)
                   ),
                   Select='ALL_ATTRIBUTES',
               )
               for item in r['Items']:
                   self._table.delete_item(
                       Key={
                           'PK': connection_id,
                           'SK': item['SK'],
                       },
                   )
           except Exception as e:
               print(e)

       def get_record_by_connection(self, connection_id):
           """Get all the properties associated with a connection.

           Each connection_id creates a partition in the table with multiple
           SK entries. Each SK entry is in the format {property}_{value}.
           This method reads all those records from the database and puts them
           all into dictionary and returns it.

           :param connection_id: The connection to get properties for.
           """
           r = self._table.query(
               KeyConditionExpression=(
                   Key('PK').eq(connection_id)
               ),
               Select='ALL_ATTRIBUTES',
           )
           r = {
               entry['SK'].split('_', 1)[0]: entry['SK'].split('_', 1)[1]
               for entry in r['Items']
           }
           return r


   class Sender(object):
       """Class to send messages over websockets."""
       def __init__(self, app, storage):
           """Initialize a sender object.

           :param app: A Chalice application object.

           :param storage: A Storage object.
           """
           self._app = app
           self._storage = storage

       def send(self, connection_id, message):
           """Send a message over a websocket.

           :param connection_id: API Gateway Connection ID to send a
               message to.

           :param message: The message to send to the connection.
           """
           try:
               # Call the chalice websocket api send method
               self._app.websocket_api.send(connection_id, message)
           except WebsocketDisconnectedError as e:
               # If the websocket has been closed, we delete the connection
               # from our database.
               self._storage.delete_connection(e.connection_id)

       def broadcast(self, connection_ids, message):
           """"Send a message to multiple connections.

           :param connection_id: A list of API Gateway Connection IDs to
               send the message to.

           :param message: The message to send to the connections.
           """
           for cid in connection_ids:
               self.send(cid, message)


   class Handler(object):
       """Handler object that handles messages received from a websocket.

       This class implements the bulk of our app behavior.
       """
       def __init__(self, storage, sender):
           """Initialize a Handler object.

           :param storage: Storage object to interact with database.

           :param sender: Sender object to send messages to websockets.
           """
           self._storage = storage
           self._sender = sender
           # Command table to translate a string command name into a
           # method to call.
           self._command_table = {
               'help': self._help,
               'nick': self._nick,
               'join': self._join,
               'room': self._room,
               'quit': self._quit,
               'ls': self._list,
           }

       def handle(self, connection_id, message):
           """Entry point for our application.

           :param connection_id: Connection id that the message came from.

           :param message: Message we got from the connection.
           """
           # First look the user up in the database and get a record for it.
           record = self._storage.get_record_by_connection(connection_id)
           if record['username'] == '':
               # If the user does not have a username, we assume that the message
               # is the username they want and we call _handle_login_message.
               self._handle_login_message(connection_id, message)
           else:
               # Otherwise we assume the user is logged in. So we call
               # a method to handle the message. We pass along the
               # record we loaded from the database so we don't need to
               # again.
               self._handle_message(connection_id, message, record)

       def _handle_login_message(self, connection_id, message):
           """Handle a login message.

           The message is the username to give the user. Re-write the
           database entry for this user to reset their username from ''
           to {message}. Once that is done send a message back to the user
           to confirm the name choice. Also send a /help prompt.
           """
           self._storage.set_username(connection_id, '', message)
           self._sender.send(
               connection_id,
               'Using nickname: %s\nType /help for list of commands.' % message
           )

       def _handle_message(self, connection_id, message, record):
           """"Handle a message from a connected and logged in user.

           If the message starts with a / it's a command. Otherwise its a
           text message to send to all rooms in the room.

           :param connection_id: Connection id that the message came from.

           :param message: Message we got from the connection.

           :param record: A data record about the sender.
           """
           if message.startswith('/'):
               self._handle_command(connection_id, message[1:], record)
           else:
               self._handle_text(connection_id, message, record)

       def _handle_command(self, connection_id, message, record):
           """Handle a command message.

           Check the command name and look it up in our command table.
           If there is an entry, we call that method and pass along
           the connection_id, arguments, and the loaded record.

           :param connection_id: Connection id that the message came from.

           :param message: Message we got from the connection.

           :param record: A data record about the sender.
           """
           args = message.split(' ')
           command_name = args.pop(0).lower()
           command = self._command_table.get(command_name)
           if command:
               command(connection_id, args, record)
           else:
               # If no command method is found, send an error message
               # back to the user.
               self._sender(
                   connection_id, 'Unknown command: %s' % command_name)

       def _handle_text(self, connection_id, message, record):
           """Handle a raw text message.

           :param connection_id: Connection id that the message came from.

           :param message: Message we got from the connection.

           :param record: A data record about the sender.
           """
           if 'room' not in record:
               # If the user is not in a room send them an error message
               # and return early.
               self._sender.send(
                   connection_id, 'Cannot send message if not in chatroom.')
               return
           # Collect a list of connection_ids in the same room as the message
           # sender.
           connection_ids = self._storage.get_connection_ids_by_room(
               record['room'])
           # Prefix the message with the sender's name.
           message = '%s: %s' % (record['username'], message)
           # Broadcast the new message to everyone in the room.
           self._sender.broadcast(connection_ids, message)

       def _help(self, connection_id, _message, _record):
           """Send the help message.

           Build a help message and send back to the same connection.

           :param connection_id: Connection id that the message came from.
           """
           self._sender.send(
               connection_id,
               '\n'.join([
                   'Commands available:',
                   '    /help',
                   '          Display this message.',
                   '    /join {chat_room_name}',
                   '          Join a chatroom named {chat_room_name}.',
                   '    /nick {nickname}',
                   '          Change your name to {nickname}. If no {nickname}',
                   '          is provided then your current name will be printed',
                   '    /room',
                   '          Print out the name of the room you are currently ',
                   '          in.',
                   '    /ls',
                   '          If you are in a room, list all users also in the',
                   '          room. Otherwise, list all rooms.',
                   '    /quit',
                   '          Leave current room.',
                   '',
                   'If you are in a room, raw text messages that do not start ',
                   'with a / will be sent to everyone else in the room.',
               ]),
           )

       def _nick(self, connection_id, args, record):
           """Change or check nickname (username).

           :param connection_id: Connection id that the message came from.

           :param args: Argument list that came after the command.

           :param record: A data record about the sender.
           """
           if not args:
               # If a nickname argument was not provided, we just want to
               # report the current nickname to the user.
               self._sender.send(
                   connection_id, 'Current nickname: %s' % record['username'])
               return
           # The first argument is assumed to be the new desired nickname.
           nick = args[0]
           # Change the username from record['username'] to nick in the storage
           # layer.
           self._storage.set_username(connection_id, record['username'], nick)
           # Send a message to the requestor to confirm the nickname change.
           self._sender.send(connection_id, 'Nickname is: %s' % nick)
           # Get the room the user is in.
           room = record.get('room')
           if room:
               # If the user was in a room, announce to the room they have
               # changed their name. Don't send this me sage to the user since
               # they already got a name change message.
               room_connections = self._storage.get_connection_ids_by_room(room)
               room_connections.remove(connection_id)
               self._sender.broadcast(
                   room_connections,
                   '%s is now known as %s.' % (record['username'], nick))

       def _join(self, connection_id, args, record):
           """Join a chat room.

           :param connection_id: Connection id that the message came from.

           :param args: Argument list. The first argument should be the
              name of the room to join.

           :param record: A data record about the sender.
           """
           # Get the room name to join.
           room = args[0]
           # Call quit to leave the current room we are in if there is any.
           self._quit(connection_id, '', record)
           # Get a list of connections in the target chat room.
           room_connections = self._storage.get_connection_ids_by_room(room)
           # Join the target chat room.
           self._storage.set_room(connection_id, room)
           # Send a message to the requestor that they have joined the room.
           # At the same time send an announcement to everyone who was already
           # in the room to alert them of the new user.
           self._sender.send(
               connection_id, 'Joined chat room "%s"' % room)
           message = '%s joined room.' % record['username']
           self._sender.broadcast(room_connections, message)

       def _room(self, connection_id, _args, record):
           """Report the name of the current room.

           :param connection_id: Connection id that the message came from.

           :param record: A data record about the sender.
           """
           if 'room' in record:
               # If the user is in a room send them the name back.
               self._sender.send(connection_id, record['room'])
           else:
               # If the user is not in a room. Tell them so, and how to
               # join a room.
               self._sender.send(
                   connection_id,
                   'Not currently in a room. Type /join {room_name} to do so.'
               )

       def _quit(self, connection_id, _args, record):
           """Quit from a room.

           :param connection_id: Connection id that the message came from.

           :param record: A data record about the sender.
           """
           if 'room' not in record:
               # If the user is not in a room there is nothing to do.
               return
           # Find the current room name, and delete that entry from
           # the database.
           room_name = record['room']
           self._storage.remove_room(connection_id, room_name)
           # Send a message to the user to inform them they left the room.
           self._sender.send(
               connection_id, 'Left chat room "%s"' % room_name)
           # Tell everyone in the room that the user has left.
           self._sender.broadcast(
               self._storage.get_connection_ids_by_room(room_name),
               '%s left room.' % record['username'],
           )

       def _list(self, connection_id, _args, record):
           """Show a context dependent listing.

           :param connection_id: Connection id that the message came from.

           :param record: A data record about the sender.
           """
           room = record.get('room')
           if room:
               # If the user is in a room, get a listing of everyone
               # in the room.
               result = [
                   self._storage.get_record_by_connection(c_id)['username']
                   for c_id in self._storage.get_connection_ids_by_room(room)
               ]
           else:
               # If they are not in a room. Get a listing of all rooms
               # currently open.
               result = self._storage.list_rooms()
           # Send the result list back to the requestor.
           self._sender.send(connection_id, '\n'.join(result))


The final directory layout should be ::

    $ tree -a .
    .
    ├── .chalice
    │   ├── config.json
    │   └── policy-dev.json
    ├── .gitignore
    ├── app.py
    ├── chalicelib
    │   └── __init__.py
    ├── create-resources.py
    └── requirements.txt

    2 directories, 7 files


To deploy the app run the following command::

   $ chalice deploy
   Creating deployment package.
   Creating IAM role: chalice-chat-example-dev-websocket_handler
   Creating lambda function: chalice-chat-example-dev-websocket_handler
   Creating websocket api: chalice-chat-example-dev-websocket-api
   Resources deployed:
     - Lambda ARN: arn:aws:lambda:::chalice-chat-example-dev-websocket_handler
     - Websocket API URL: wss://{id}.execute-api.{region}.amazonaws.com/api/

Once deployed we can take the ``Websocket API URL`` and connect to it in the
same way we did in the previous example using the ``wsdump.py`` command line
tool. Below is a sample of two running clients, the first message sent to the
server is used as the client's username.


.. code-block:: bash
   :caption: client-1

   $ wsdump.py wss://{id}.execute-api.{region}.amazonaws.com/api/
   Press Ctrl+C to quit
   > John
   < Using nickname: John
   Type /help for list of commands.
   > /help
   < Commands available:
       /help
             Display this message.
       /join {chat_room_name}
             Join a chatroom named {chat_room_name}.
       /nick {nickname}
             Change your name to {nickname}. If no {nickname}
             is provided then your current name will be printed
       /room
             Print out the name of the room you are currently
             in.
       /ls
             If you are in a room, list all users also in the
             room. Otherwise, list all rooms.
       /quit
             Leave current room.

   If you are in a room, raw text messages that do not start
   with a / will be sent to everyone else in the room.
   > /join chalice
   < Joined chat room "chalice"
   < Jenny joined room.
   > Hi
   < John: Hi
   < Jenny is now known as JennyJones.
   > /quit
   < Left chat room "chalice"
   > /ls
   < chalice
   > Ctrl-C

.. code-block:: bash
   :caption: client-2

   $ wsdump.py wss://{id}.execute-api.{region}.amazonaws.com/api/
   Press Ctrl+C to quit
   > Jenny
   < Using nickname: Jenny
   Type /help for list of commands.
   > /help
   < Commands available:
       /help
             Display this message.
       /join {chat_room_name}
             Join a chatroom named {chat_room_name}.
       /nick {nickname}
             Change your name to {nickname}. If no {nickname}
             is provided then your current name will be printed
       /room
             Print out the name of the room you are currently
             in.
       /ls
             If you are in a room, list all users also in the
             room. Otherwise, list all rooms.
       /quit
             Leave current room.

   If you are in a room, raw text messages that do not start
   with a / will be sent to everyone else in the room.
   > /join chalice
   < Joined chat room "chalice"
   > /ls
   < John
   Jenny
   < John: Hi
   > /nick JennyJones
   < Nickname is: JennyJones
   < John left room.
   > /ls
   < JennyJones
   > /room
   < chalice
   > /nick
   < Current nickname: JennyJones
   > Ctrl-C


To delete the resources you can run chalice delete and use the AWS CLI
to delete the DynamoDB table::

  $ chalice delete
  $ pip install -U awscli
  $ aws dynamodb delete-table --table-name ChaliceChatTable
