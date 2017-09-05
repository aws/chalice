import os
from hypothesis import settings

# From:
# http://hypothesis.readthedocs.io/en/latest/settings.html#settings-profiles
# On travis we'll have it run through more iterations.
settings.register_profile('ci', settings(max_examples=2000))
settings.load_profile(os.getenv('HYPOTHESIS_PROFILE', 'default'))
