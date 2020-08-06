from uuid import uuid4

from boto3.dynamodb.conditions import Key


DEFAULT_USERNAME = 'default'


class TodoDB(object):
    def list_items(self):
        pass

    def add_item(self, description, metadata=None):
        pass

    def get_item(self, uid):
        pass

    def delete_item(self, uid):
        pass

    def update_item(self, uid, description=None, state=None,
                    metadata=None):
        pass


class InMemoryTodoDB(TodoDB):
    def __init__(self, state=None):
        if state is None:
            state = {}
        self._state = state

    def list_all_items(self):
        all_items = []
        for username in self._state:
            all_items.extend(self.list_items(username))
        return all_items

    def list_items(self, username=DEFAULT_USERNAME):
        return list(self._state.get(username, {}).values())

    def add_item(self, description, metadata=None, username=DEFAULT_USERNAME):
        if username not in self._state:
            self._state[username] = {}
        uid = str(uuid4())
        self._state[username][uid] = {
            'uid': uid,
            'description': description,
            'state': 'unstarted',
            'metadata': metadata if metadata is not None else {},
            'username': username
        }
        return uid

    def get_item(self, uid, username=DEFAULT_USERNAME):
        return self._state[username][uid]

    def delete_item(self, uid, username=DEFAULT_USERNAME):
        del self._state[username][uid]

    def update_item(self, uid, description=None, state=None,
                    metadata=None, username=DEFAULT_USERNAME):
        item = self._state[username][uid]
        if description is not None:
            item['description'] = description
        if state is not None:
            item['state'] = state
        if metadata is not None:
            item['metadata'] = metadata


class DynamoDBTodo(TodoDB):
    def __init__(self, table_resource):
        self._table = table_resource

    def list_all_items(self):
        response = self._table.scan()
        return response['Items']

    def list_items(self, username=DEFAULT_USERNAME):
        response = self._table.query(
            KeyConditionExpression=Key('username').eq(username)
        )
        return response['Items']

    def add_item(self, description, metadata=None, username=DEFAULT_USERNAME):
        uid = str(uuid4())
        self._table.put_item(
            Item={
                'username': username,
                'uid': uid,
                'description': description,
                'state': 'unstarted',
                'metadata': metadata if metadata is not None else {},
            }
        )
        return uid

    def get_item(self, uid, username=DEFAULT_USERNAME):
        response = self._table.get_item(
            Key={
                'username': username,
                'uid': uid,
            },
        )
        return response['Item']

    def delete_item(self, uid, username=DEFAULT_USERNAME):
        self._table.delete_item(
            Key={
                'username': username,
                'uid': uid,
            }
        )

    def update_item(self, uid, description=None, state=None,
                    metadata=None, username=DEFAULT_USERNAME):
        # We could also use update_item() with an UpdateExpression.
        item = self.get_item(uid, username)
        if description is not None:
            item['description'] = description
        if state is not None:
            item['state'] = state
        if metadata is not None:
            item['metadata'] = metadata
        self._table.put_item(Item=item)
