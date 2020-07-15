import json
import os

import boto3
from chalice import Chalice
from chalice import NotFoundError
from chalicelib import db
from chalicelib import rekognition

app = Chalice(app_name='media-query')

_MEDIA_DB = None
_REKOGNITION_CLIENT = None
_SUPPORTED_IMAGE_EXTENSIONS = (
    '.jpg',
    '.png',
)
_SUPPORTED_VIDEO_EXTENSIONS = (
    '.mp4',
    '.flv',
    '.mov',
)


def get_media_db():
    global _MEDIA_DB
    if _MEDIA_DB is None:
        _MEDIA_DB = db.DynamoMediaDB(
            boto3.resource('dynamodb').Table(
                os.environ['MEDIA_TABLE_NAME']))
    return _MEDIA_DB


def get_rekognition_client():
    global _REKOGNITION_CLIENT
    if _REKOGNITION_CLIENT is None:
        _REKOGNITION_CLIENT = rekognition.RekognitonClient(
            boto3.client('rekognition'))
    return _REKOGNITION_CLIENT


# Start of Event Handlers.
@app.on_s3_event(bucket=os.environ['MEDIA_BUCKET_NAME'],
                 events=['s3:ObjectCreated:*'])
def handle_object_created(event):
    if _is_image(event.key):
        _handle_created_image(bucket=event.bucket, key=event.key)
    elif _is_video(event.key):
        _handle_created_video(bucket=event.bucket, key=event.key)


@app.on_s3_event(bucket=os.environ['MEDIA_BUCKET_NAME'],
                 events=['s3:ObjectRemoved:*'])
def handle_object_removed(event):
    if _is_image(event.key) or _is_video(event.key):
        get_media_db().delete_media_file(event.key)


@app.on_sns_message(topic=os.environ['VIDEO_TOPIC_NAME'])
def add_video_file(event):
    message = json.loads(event.message)
    labels = get_rekognition_client().get_video_job_labels(message['JobId'])
    get_media_db().add_media_file(
        name=message['Video']['S3ObjectName'],
        media_type=db.VIDEO_TYPE,
        labels=labels)


@app.route('/')
def list_media_files():
    params = {}
    if app.current_request.query_params:
        params = _extract_db_list_params(app.current_request.query_params)
    return get_media_db().list_media_files(**params)


@app.route('/{name}')
def get_media_file(name):
    item = get_media_db().get_media_file(name)
    if item is None:
        raise NotFoundError('Media file (%s) not found' % name)
    return item
# End of Event Handlers.


def _extract_db_list_params(query_params):
    valid_query_params = [
        'startswith',
        'media-type',
        'label'
    ]
    return {
        k.replace('-', '_'): v
        for k, v in query_params.items() if k in valid_query_params
    }


def _is_image(key):
    return key.endswith(_SUPPORTED_IMAGE_EXTENSIONS)


def _handle_created_image(bucket, key):
    labels = get_rekognition_client().get_image_labels(bucket=bucket, key=key)
    get_media_db().add_media_file(key, media_type=db.IMAGE_TYPE, labels=labels)


def _is_video(key):
    return key.endswith(_SUPPORTED_VIDEO_EXTENSIONS)


def _handle_created_video(bucket, key):
    get_rekognition_client().start_video_label_job(
        bucket=bucket, key=key, topic_arn=os.environ['VIDEO_TOPIC_ARN'],
        role_arn=os.environ['VIDEO_ROLE_ARN']
    )
