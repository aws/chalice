import os
import unittest
import boto3
from uuid import uuid4

from chalicelib.db import InMemoryTodoDB
from chalicelib.db import DynamoDBTodo


class TestTodoDB(unittest.TestCase):
    def setUp(self):
        self.db_dict = {}
        self.db = InMemoryTodoDB(self.db_dict)

    def tearDown(self):
        response = self.db.list_all_items()
        for item in response:
            self.db.delete_item(item['uid'], username=item['username'])

    def test_can_add_and_retrieve_data(self):
        todo_id = self.db.add_item('First item')
        must_contain = {'description': 'First item',
                        'state': 'unstarted',
                        'metadata': {}}
        full_record = self.db.get_item(todo_id)
        assert dict(full_record, **must_contain) == full_record

    def test_can_add_and_list_data(self):
        todo_id = self.db.add_item('First item')
        todos = self.db.list_items()
        self.assertEqual(len(todos), 1)
        self.assertEqual(todos[0]['uid'], todo_id)

    def test_can_add_and_delete_data(self):
        todo_id = self.db.add_item('First item')
        self.assertEqual(len(self.db.list_items()), 1)
        self.db.delete_item(todo_id)
        self.assertEqual(len(self.db.list_items()), 0)

    def test_can_add_and_update_data(self):
        todo_id = self.db.add_item('First item')
        self.db.update_item(todo_id, state='started')
        self.assertEqual(self.db.get_item(todo_id)['state'], 'started')

    def test_can_add_and_retrieve_data_with_specified_username(self):
        username = 'myusername'
        todo_id = self.db.add_item('First item', username=username)
        must_contain = {
            'description': 'First item',
            'state': 'unstarted',
            'metadata': {},
            'username': username
        }
        full_record = self.db.get_item(todo_id, username=username)
        assert dict(full_record, **must_contain) == full_record

    def test_can_add_and_list_data_with_specified_username(self):
        username = 'myusername'
        todo_id = self.db.add_item('First item', username=username)
        todos = self.db.list_items(username=username)
        self.assertEqual(len(todos), 1)
        self.assertEqual(todos[0]['uid'], todo_id)
        self.assertEqual(todos[0]['username'], username)

    def test_can_add_and_delete_data_with_specified_username(self):
        username = 'myusername'
        todo_id = self.db.add_item('First item', username=username)
        self.assertEqual(len(self.db.list_items(username=username)), 1)
        self.db.delete_item(todo_id, username=username)
        self.assertEqual(len(self.db.list_items(username=username)), 0)

    def test_can_add_and_update_data_with_specified_username(self):
        username = 'myusername'
        todo_id = self.db.add_item('First item', username=username)
        self.db.update_item(todo_id, state='started', username=username)
        self.assertEqual(self.db.get_item(
            todo_id, username=username)['state'], 'started')

    def test_list_all_items(self):
        todo_id = self.db.add_item('First item', username='user')
        other_todo_id = self.db.add_item('First item', username='otheruser')
        all_todos = self.db.list_all_items()
        self.assertEqual(len(all_todos), 2)
        users = [todo['username'] for todo in all_todos]
        todo_ids = [todo['uid'] for todo in all_todos]
        self.assertCountEqual(['user', 'otheruser'], users)
        self.assertCountEqual([todo_id, other_todo_id], todo_ids)


@unittest.skipUnless(os.environ.get('RUN_INTEG_TESTS', False),
                     "Skipping integ tests (RUN_INTEG_TESTS) not test.")
class TestDynamoDB(TestTodoDB):
    @classmethod
    def setUpClass(cls):
        cls.TABLE_NAME = 'todo-integ-%s' % str(uuid4())
        client = boto3.client('dynamodb')
        client.create_table(
            TableName=cls.TABLE_NAME,
            KeySchema=[
                {
                    'AttributeName': 'username',
                    'KeyType': 'HASH'
                },
                {
                    'AttributeName': 'uid',
                    'KeyType': 'RANGE',
                }
            ],
            AttributeDefinitions=[
                {
                    'AttributeName': 'username',
                    'AttributeType': 'S',
                },
                {
                    'AttributeName': 'uid',
                    'AttributeType': 'S',
                }
            ],
            ProvisionedThroughput={
                'ReadCapacityUnits': 5,
                'WriteCapacityUnits': 5,
            }
        )
        waiter = client.get_waiter('table_exists')
        waiter.wait(TableName=cls.TABLE_NAME, WaiterConfig={'Delay': 1})

    @classmethod
    def tearDownClass(cls):
        client = boto3.client('dynamodb')
        client.delete_table(TableName=cls.TABLE_NAME)
        waiter = client.get_waiter('table_not_exists')
        waiter.wait(TableName=cls.TABLE_NAME, WaiterConfig={'Delay': 1})

    def setUp(self):
        resource = boto3.resource('dynamodb')
        self.table = resource.Table(self.TABLE_NAME)
        self.db = DynamoDBTodo(self.table)
