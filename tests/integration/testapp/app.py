from chalice import Chalice, BadRequestError, NotFoundError, Response

import  urlparse
# This is a test app that is used by integration tests.
# This app exercises all the major features of chalice
# and helps prevent regressions.

app = Chalice(app_name='smoketestapp')


@app.route('/')
def index():
    return {'hello': 'world'}


@app.route('/a/b/c/d/e/f/g')
def nested_route():
    return {'nested': True}


@app.route('/path/{name}')
def supports_path_params(name):
    return {'path': name}


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
    parsed = urlparse.parse_qs(app.current_request.raw_body)
    return {
        'parsed': parsed
    }


@app.route('/cors', methods=['GET', 'POST', 'PUT'], cors=True)
def supports_cors():
    # It doesn't really matter what we return here because
    # we'll be checking the response headers to verify CORS support.
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
