import os
import json
try:
    from urllib.parse import parse_qs
except ImportError:
    from urlparse import parse_qs


import boto3.session
from chalice import Chalice, BadRequestError, NotFoundError, Response,\
    CORSConfig, UnauthorizedError, AuthResponse, AuthRoute


# This is a test app that is used by integration tests.
# This app exercises all the major features of chalice
# and helps prevent regressions.

app = Chalice(app_name=os.environ['APP_NAME'])
app.websocket_api.session = boto3.session.Session()
app.experimental_feature_flags.update([
    'WEBSOCKETS'
])
app.api.binary_types.append('application/binary')


@app.authorizer(ttl_seconds=300)
def dummy_auth(auth_request):
    if auth_request.token == 'yes':
        return AuthResponse(
            routes=['/builtin-auth',
                    AuthRoute('/fake-profile', methods=['POST'])],
            context={'foo': 'bar'},
            principal_id='foo'
        )
    else:
        raise UnauthorizedError('Authorization failed')


@app.route('/')
def index():
    return {'hello': 'world'}


@app.route('/a/b/c/d/e/f/g')
def nested_route():
    return {'nested': True}


@app.route('/path/{name}')
def supports_path_params(name):
    return {'path': name}


@app.route('/singledoc')
def single_doc():
    """Single line docstring."""
    return {'docstring': 'single'}


@app.route('/multidoc')
def multi_doc():
    """Multi-line docstring.

    And here is another line.
    """
    return {'docstring': 'multi'}


@app.route('/post', methods=['POST'])
def supports_only_post():
    return {'success': True}


@app.route('/put', methods=['PUT'])
def supports_only_put():
    return {'success': True}


@app.route('/jsonpost', methods=['POST'])
def supports_post_body_as_json():
    json_body = app.current_request.json_body
    return {'json_body': json_body}


@app.route('/multimethod', methods=['GET', 'POST'])
def multiple_methods():
    return {'method': app.current_request.method}


@app.route('/badrequest')
def bad_request_error():
    raise BadRequestError("Bad request.")


@app.route('/notfound')
def not_found_error():
    raise NotFoundError("Not found")


@app.route('/arbitrary-error')
def raise_arbitrary_error():
    raise TypeError("Uncaught exception")


@app.route('/formencoded', methods=['POST'],
           content_types=['application/x-www-form-urlencoded'])
def form_encoded():
    parsed = parse_qs(app.current_request.raw_body.decode('utf-8'))
    return {
        'parsed': parsed
    }


@app.route('/json-only', content_types=['application/json'])
def json_only():
    return {'success': True}


@app.route('/cors', methods=['GET', 'POST', 'PUT'], cors=True)
def supports_cors():
    # It doesn't really matter what we return here because
    # we'll be checking the response headers to verify CORS support.
    return {'cors': True}


@app.route('/custom_cors', methods=['GET', 'POST', 'PUT'], cors=CORSConfig(
    allow_origin='https://foo.example.com',
    allow_headers=['X-Special-Header'],
    max_age=600,
    expose_headers=['X-Special-Header'],
    allow_credentials=True))
def supports_custom_cors():
    return {'cors': True}


@app.route('/todict', methods=['GET'])
def todict():
    return app.current_request.to_dict()


@app.route('/multifile')
def multifile():
    from chalicelib import MESSAGE
    return {"message": MESSAGE}


@app.route('/custom-response', methods=['GET'])
def custom_response():
    return Response(status_code=204, body='',
                    headers={'Content-Type': 'text/plain'})


@app.route('/api-key-required', methods=['GET'], api_key_required=True)
def api_key_required():
    return {"success": True}


@app.route('/binary', methods=['POST'],
           content_types=['application/octet-stream'])
def binary_round_trip():
    return Response(
        app.current_request.raw_body,
        headers={
            'Content-Type': 'application/octet-stream'
        },
        status_code=200)


@app.route('/custom-binary', methods=['POST'],
           content_types=['application/binary'])
def custom_binary_round_trip():
    return Response(
        app.current_request.raw_body,
        headers={
            'Content-Type': 'application/binary'
        },
        status_code=200)


@app.route('/get-binary', methods=['GET'])
def binary_response():
    return Response(
        body=b'\xDE\xAD\xBE\xEF',
        headers={
            'Content-Type': 'application/octet-stream'
        },
        status_code=200)


@app.route('/shared', methods=['GET'])
def shared_get():
    return {'method': 'GET'}


@app.route('/shared', methods=['POST'])
def shared_post():
    return {'method': 'POST'}


@app.route('/builtin-auth', authorizer=dummy_auth)
def builtin_auth():
    return {'success': True, 'context': app.current_request.context}


# Testing a common use case where you can have read only GET access
# but you need to be auth'd to POST.

@app.route('/fake-profile', methods=['GET'])
def fake_profile_read_only():
    return {'success': True, 'context': app.current_request.context}


@app.route('/fake-profile', authorizer=dummy_auth,
           methods=['POST'])
def fake_profile_post():
    return {'success': True, 'context': app.current_request.context}


@app.route('/repr-raw-body', methods=['POST'])
def repr_raw_body():
    return {'repr-raw-body': app.current_request.raw_body.decode('utf-8')}


SOCKET_MESSAGES = {
    'connect': [],
    'message': [],
    'disconnect': [],
}


@app.on_ws_connect()
def connect(event):
    SOCKET_MESSAGES['connect'].append(event.connection_id)


@app.on_ws_message()
def message(event):
    SOCKET_MESSAGES['message'].append((event.connection_id, event.body))
    app.websocket_api.send(event.connection_id, json.dumps(SOCKET_MESSAGES))


@app.on_ws_disconnect()
def disconnect(event):
    SOCKET_MESSAGES['disconnect'].append(event.connection_id)
