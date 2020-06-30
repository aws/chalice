Quickstart
==========

.. include:: ../../README.rst
  :start-after: quick-start-begin
  :end-before: quick-start-end

Cleaning Up
-----------

If you're done experimenting with Chalice and you'd like to cleanup, you can
use the ``chalice delete`` command, and Chalice will delete all the resources
it created when running the ``chalice deploy`` command.

::

    $ chalice delete
    Deleting Rest API: abcd4kwyl4
    Deleting function aws:arn:lambda:region:123456789:helloworld-dev
    Deleting IAM Role helloworld-dev


Next Steps
----------

At this point, there are several tutorials you can follow based on what
you're interested in:

* :doc:`Creating REST APIs <tutorials/basicrestapi>` - Dive into more detail on
  how to create a REST API using Chalice.  We'll explore URL parameters, error
  messages, content types, CORs, and more.
* :doc:`Event Sources <tutorials/events>` - In this tutorial, we'll focus on
  difference event sources you can connect with a Lambda function other than a
  REST API with Amazon API Gateway.
* :doc:`Websockets <tutorials/wschat>` - In this tutorial, we'll show you
  how to create a websocket API and create a sample chat application.

You can also jump into specific :doc:`topic guides <topics/index>`.  These are
more detailed than the tutorials, and provide more reference style
documentation on specific features of Chalice.

And finally, you can look at the :doc:`API Reference <api>` for detailed API
documentation for Chalice.  This is useful if you know exactly what feature
you're using but need to lookup a specific parameter name or return value.
