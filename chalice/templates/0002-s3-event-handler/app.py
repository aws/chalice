import os

from chalice import Chalice

app = Chalice(app_name='{{app_name}}')
app.debug = True


# Set the value of APP_BUCKET_NAME in the .chalice/config.json file.
S3_BUCKET = os.environ.get('APP_BUCKET_NAME', '')


@app.on_s3_event(bucket=S3_BUCKET, events=['s3:ObjectCreated:*'])
def s3_handler(event):
    app.log.debug("Received event for bucket: %s, key: %s",
                  event.bucket, event.key)
