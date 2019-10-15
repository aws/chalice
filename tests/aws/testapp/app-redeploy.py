"""Test app redeploy.

This file is copied over to app.py during the integration
tests to test behavior on redeploys.

"""
import os

from chalice import Chalice


app = Chalice(app_name=os.environ['APP_NAME'])


# Test an unchanged view, this is the exact
# version from app.py
@app.route('/')
def index():
    return {'hello': 'world'}


# Test same route info but changed view code.
@app.route('/a/b/c/d/e/f/g')
def nested_route():
    return {'redeployed': True}


# Test route deletion.  This view is in the original
# app.py but is now deleted.
# @app.route('/path/{name}')
# def supports_path_params(name):
#     return {'path': name}

# Test route modification with the same view code.
# The original version had methods=['GET', 'POST']
@app.route('/multimethod', methods=['GET', 'PUT'])
def multiple_methods():
    return {'method': app.current_request.method}


# Test new view function added that wasn't in the original
# app.py file.
@app.route('/redeploy')
def redeploy():
    return {'success': True}
