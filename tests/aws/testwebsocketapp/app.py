import os

import boto3
from chalice import Chalice

app = Chalice(app_name=os.environ['APP_NAME'])
app.websocket_api.session = boto3.session.Session()
app.experimental_feature_flags.update([
    'WEBSOCKETS'
])
ddb = boto3.client('dynamodb')


@app.on_ws_message()
def message(event):
    try:
        ddb.put_item(
            TableName=os.environ['APP_NAME'],
            Item={
                'entry': {
                    'N': event.body
                },
            },
        )
    except Exception as e:
        # If we get an exception, we need to log it somehow.  We can't
        # return this back to the user so we'll add something to the ddb
        # table to denote that we failed.
        ddb.put_item(
            TableName=os.environ['APP_NAME'],
            Item={
                'entry': {
                    'N': "-9999"
                },
                'errormsg': {
                    'S': '%s: %s,\noriginal event: %s' % (
                        e.__class__, e, event.to_dict())
                }
            }
        )
