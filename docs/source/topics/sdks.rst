SDK Generation
==============

The ``@app.route(...)`` information you provide chalice allows
it to create corresponding routes in API Gateway.  One of the benefits of this
approach is that we can leverage API Gateway's SDK generation process.
Chalice offers a ``chalice generate-sdk`` command that will automatically
generate an SDK based on your declared routes.

.. note::
  The only supported language at this time is javascript.

Keep in mind that chalice itself does not have any logic for generating
SDKs.  The SDK generation happens service side in `API Gateway`_, the
``chalice generate-sdk`` is just a high level wrapper around that
functionality.

To generate an SDK for a chalice app, run this command from the project
directory::

    $ chalice generate-sdk /tmp/sdk

You should now have a generated javascript sdk in ``/tmp/sdk``.
API Gateway includes a ``README.md`` as part of its SDK generation
which contains details on how to use the javascript SDK.

Example
-------

Suppose we have the following chalice app:

.. code-block:: python

    from chalice import Chalice

    app = Chalice(app_name='sdktest')

    @app.route('/', cors=True)
    def index():
        return {'hello': 'world'}

    @app.route('/foo', cors=True)
    def foo():
        return {'foo': True}

    @app.route('/hello/{name}', cors=True)
    def hello_name(name):
        return {'hello': name}

    @app.route('/users/{user_id}', methods=['PUT'], cors=True)
    def update_user(user_id):
        return {"msg": "fake updated user", "userId": user_id}


Let's generate a javascript SDK and test it out in the browser.
Run the following command from the project dir::

    $ chalice generate-sdk /tmp/sdkdemo
    $ cd /tmp/sdkdemo
    $ ls -la
    -rw-r--r--   1 jamessar  r  3227 Nov 21 17:06 README.md
    -rw-r--r--   1 jamessar  r  9243 Nov 21 17:06 apigClient.js
    drwxr-xr-x   6 jamessar  r   204 Nov 21 17:06 lib

You should now be able to follow the instructions from API Gateway in the
``README.md`` file. Below is a snippet that shows how the generated
javascript SDK methods correspond to the ``@app.route()`` calls in chalice.

.. code-block:: html

  <script type="text/javascript">
    // Below are examples of how the javascript SDK methods
    // correspond to chalice @app.routes()
    var apigClient = apigClientFactory.newClient();

    // @app.route('/')
    apigClient.rootGet().then(result => {
        document.getElementById('root-get').innerHTML = JSON.stringify(result.data);
    });

    // @app.route('/foo')
    apigClient.fooGet().then(result => {
        document.getElementById('foo-get').innerHTML = JSON.stringify(result.data);
    });

    // @app.route('/hello/{name}')
    apigClient.helloNameGet({name: 'jimmy'}).then(result => {
        document.getElementById('helloname-get').innerHTML = JSON.stringify(result.data);
    });

    // @app.route('/users/{user_id}', methods=['PUT'])
    apigClient.usersUserIdPut({user_id: '123'}, 'body content').then(result => {
        document.getElementById('users-userid-put').innerHTML = JSON.stringify(result.data);
    });
  </script>





Example HTML File
~~~~~~~~~~~~~~~~~

If you want to try out the example above, you can use the following index.html
page to test:

.. code-block:: html

    <!DOCTYPE html>
    <html lang="en">
        <head>
            <title>SDK Test</title>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1">
            <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/skeleton/2.0.4/skeleton.min.css">
            <script type="text/javascript" src="lib/axios/dist/axios.standalone.js"></script>
            <script type="text/javascript" src="lib/CryptoJS/rollups/hmac-sha256.js"></script>
            <script type="text/javascript" src="lib/CryptoJS/rollups/sha256.js"></script>
            <script type="text/javascript" src="lib/CryptoJS/components/hmac.js"></script>
            <script type="text/javascript" src="lib/CryptoJS/components/enc-base64.js"></script>
            <script type="text/javascript" src="lib/url-template/url-template.js"></script>
            <script type="text/javascript" src="lib/apiGatewayCore/sigV4Client.js"></script>
            <script type="text/javascript" src="lib/apiGatewayCore/apiGatewayClient.js"></script>
            <script type="text/javascript" src="lib/apiGatewayCore/simpleHttpClient.js"></script>
            <script type="text/javascript" src="lib/apiGatewayCore/utils.js"></script>
            <script type="text/javascript" src="apigClient.js"></script>


            <script type="text/javascript">
              // Below are examples of how the javascript SDK methods
              // correspond to chalice @app.routes()
              var apigClient = apigClientFactory.newClient();

              // @app.route('/')
              apigClient.rootGet().then(result => {
                  document.getElementById('root-get').innerHTML = JSON.stringify(result.data);
              });

              // @app.route('/foo')
              apigClient.fooGet().then(result => {
                  document.getElementById('foo-get').innerHTML = JSON.stringify(result.data);
              });

              // @app.route('/hello/{name}')
              apigClient.helloNameGet({name: 'jimmy'}).then(result => {
                  document.getElementById('helloname-get').innerHTML = JSON.stringify(result.data);
              });

              // @app.route('/users/{user_id}', methods=['PUT'])
              apigClient.usersUserIdPut({user_id: '123'}, 'body content').then(result => {
                  document.getElementById('users-userid-put').innerHTML = JSON.stringify(result.data);
              });
            </script>
        </head>
        <body>
            <div><h5>result of rootGet()</h5><pre id="root-get"></pre></div>
            <div><h5>result of fooGet()</h5><pre id="foo-get"></pre></div>
            <div><h5>result of helloNameGet({name: 'jimmy'})</h5><pre id="helloname-get"></pre></div>
            <div><h5>result of usersUserIdPut({user_id: '123'})</h5><pre id="users-userid-put"></pre></div>
        </body>
    </html>


.. _API Gateway: https://docs.aws.amazon.com/apigateway/latest/developerguide/how-to-generate-sdk.html
