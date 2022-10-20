import os
import json

from typing import Dict


def load_layer_versions():
    # type: () -> Dict[str, str]
    layers_json = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        'layer-versions.json')
    with open(layers_json) as f:
        return json.loads(f.read())


LAYER_VERSIONS = load_layer_versions()
