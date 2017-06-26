import socket
import six

from six import StringIO


if six.PY3:
    from urllib.parse import urlparse, parse_qs
    lambda_abi = 'cp36m'

    def is_broken_pipe_error(error):
        # type: (Exception) -> bool
        return isinstance(error, BrokenPipeError)  # noqa
else:
    from urlparse import urlparse, parse_qs
    lambda_abi = 'cp27mu'

    def is_broken_pipe_error(error):
        # type: (Exception) -> bool

        # In python3, this is a BrokenPipeError. However in python2, this
        # is a socket.error that has the message 'Broken pipe' in it. So we
        # don't want to be assuming all socket.error are broken pipes so just
        # check if the message has 'Broken pipe' in it.
        return isinstance(error, socket.error) and 'Broken pipe' in str(error)
