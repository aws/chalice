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
    ddb.put_item(
        TableName=os.environ['APP_NAME'],
        Item={
            'entry': {
                'N': event.body
            },
        },
    )
    app.websocket_api.send(event.connection_id, event.body)
