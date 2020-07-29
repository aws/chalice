Sample Applications
===================

Below are a collection of Chalice sample applications.  They
show you how you can write more real-world serverless applications.
The code for all of these sample applications is available in
the `Chalice repository on GitHub
<https://github.com/aws/chalice/tree/master/docs/source/samples>`__.

For each of these sample apps, we'll cover what is does,
the architecture of the app, how to deploy and test the app,
and we'll walk through the key parts of the application code.

:doc:`todo-app/index`
  This app is a REST API that manages Todo
  items.  These items are stored in an Amazon DynamoDB database.
  The REST API is protected with JWT auth.  We show you how to
  implement auth and login with Chalice's :ref:`builtin-authorizers`.

:doc:`media-query/index`
  This app shows how to create an image
  processing pipeline that can analyze images and videos to detect
  real world objects.  The results of this analysis are then
  stored in a database and exposed through a queryable REST API.


.. toctree::
   :hidden:
   :glob:

   ./*/index
