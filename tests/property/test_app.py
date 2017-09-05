import json
import base64

import hypothesis.strategies as st
from hypothesis import given, assume
import six

from chalice.app import Request, Response, handle_decimals
from chalice.app import APIGateway


STR_MAP = st.dictionaries(st.text(), st.text())
HTTP_METHOD = st.sampled_from(['GET', 'POST', 'PUT', 'PATCH',
                               'OPTIONS', 'HEAD', 'DELETE'])
HTTP_BODY = st.none() | st.text()
HTTP_REQUEST = st.fixed_dictionaries({
    'query_params': STR_MAP,
    'headers': STR_MAP,
    'uri_params': STR_MAP,
    'method': HTTP_METHOD,
    'body': HTTP_BODY,
    'context': STR_MAP,
    'stage_vars': STR_MAP,
    'is_base64_encoded': st.booleans(),
})
BINARY_TYPES = APIGateway().binary_types


@given(http_request_kwargs=HTTP_REQUEST)
def test_http_request_to_dict_is_json_serializable(http_request_kwargs):
    # We have to do some slight pre-preocessing here
    # to maintain preconditions.  If the
    # is_base64_encoded arg is True, we'll
    # base64 encode the body.  We assume API Gateway
    # upholds this precondition.
    is_base64_encoded = http_request_kwargs['is_base64_encoded']
    if is_base64_encoded:
        # Confirmed that if you send an empty body,
        # API Gateway will always say the body is *not*
        # base64 encoded.
        assume(http_request_kwargs['body'] is not None)
        body = base64.b64encode(
            http_request_kwargs['body'].encode('utf-8'))
        http_request_kwargs['body'] = body.decode('ascii')

    request = Request(**http_request_kwargs)
    assert isinstance(request.raw_body, bytes)
    request_dict = request.to_dict()
    # We should always be able to dump the request dict
    # to JSON.
    assert json.dumps(request_dict, default=handle_decimals)


@given(body=st.text(), headers=STR_MAP,
       status_code=st.integers(min_value=200, max_value=599))
def test_http_response_to_dict(body, headers, status_code):
    r = Response(body=body, headers=headers, status_code=status_code)
    apig = APIGateway()
    serialized = r.to_dict()
    assert 'headers' in serialized
    assert 'statusCode' in serialized
    assert 'body' in serialized
    assert isinstance(serialized['body'], six.string_types)


@given(body=st.binary(), content_type=st.sampled_from(BINARY_TYPES))
def test_handles_binary_responses(body, content_type):
    r = Response(body=body, headers={'Content-Type': content_type})
    serialized = r.to_dict(BINARY_TYPES)
    # A binary response should always result in the
    # response being base64 encoded.
    assert serialized['isBase64Encoded']
    assert isinstance(serialized['body'], six.string_types)
    assert isinstance(base64.b64decode(serialized['body']), bytes)
