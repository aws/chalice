from boto3.dynamodb.conditions import Attr


IMAGE_TYPE = 'image'
VIDEO_TYPE = 'video'


class MediaDB(object):
    def list_media_files(self, label=None):
        pass

    def add_media_file(self, name, media_type, labels=None):
        pass

    def get_media_file(self, name):
        pass

    def delete_media_file(self, name):
        pass


class DynamoMediaDB(MediaDB):
    def __init__(self, table_resource):
        self._table = table_resource

    def list_media_files(self, startswith=None, media_type=None, label=None):
        scan_params = {}
        filter_expression = None
        if startswith is not None:
            filter_expression = self._add_to_filter_expression(
                filter_expression, Attr('name').begins_with(startswith)
            )
        if media_type is not None:
            filter_expression = self._add_to_filter_expression(
                filter_expression, Attr('type').eq(media_type)
            )
        if label is not None:
            filter_expression = self._add_to_filter_expression(
                filter_expression, Attr('labels').contains(label)
            )
        if filter_expression:
            scan_params['FilterExpression'] = filter_expression
        response = self._table.scan(**scan_params)
        return response['Items']

    def add_media_file(self, name, media_type, labels=None):
        if labels is None:
            labels = []
        self._table.put_item(
            Item={
                'name': name,
                'type': media_type,
                'labels': labels,
            }
        )

    def get_media_file(self, name):
        response = self._table.get_item(
            Key={
                'name': name,
            },
        )
        return response.get('Item')

    def delete_media_file(self, name):
        self._table.delete_item(
            Key={
                'name': name,
            }
        )

    def _add_to_filter_expression(self, expression, condition):
        if expression is None:
            return condition
        return expression & condition
