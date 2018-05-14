import os
import sys
from chalice import Chalice

app = Chalice(app_name='env')

try:
    foo = os.environ['FOO']
except KeyError:
    raise AssertionError("Env vars were not loaded at import time.")


@app.route('/')
def index():
    return {'hello': foo}


sys.stderr.write("READY")
sys.stderr.flush()
