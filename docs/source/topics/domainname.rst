Custom Domain Name
==================

Custom domain names are simpler and more intuitive URLs
that you can provide to your API users.
With custom domain names, you can set up your API's hostname,
and choose a base path to map the alternative URL to your API.

AWS-managed certificate is required to configure custom domain name
for REST API or for Websocket. See `Get certificate in AWS Certificate Manager <https://docs.aws.amazon.com/apigateway/latest/developerguide/how-to-custom-domains-prerequisites.html>`__

Custom domain name can be configured per stage.


Configure custom domain name for REST API
-----------------------------------------

To create custom domain name for REST API only config.json should be modified.

If ``.chalice/config.json`` contains ``api_gateway_custom_domain`` field,
then while ``chalice deploy`` command is running, the custom domain
name will be created.

.. code-block:: json

    {
        "stages": {
            "dev": {
                "api_gateway_stage": "api",
                "api_gateway_custom_domain": {
                    "domain_name": "api.example.com",
                    "tls_version": "TLS_1_2|TLS_1_0",
                    "certificate_arn": "arn:aws:acm:example",
                    "url_prefix": "foo",
                    "tags": {
                        "key": "tag1",
                        "key1": "tag2"
                    }
                }
            }
        }
    }

Configure custom domain name for Websocket
------------------------------------------

To create custom domain name for REST API only config.json should be modified.

If ``.chalice/config.json`` contains the ``websocket_api_custom_domain`` field,
then while `chalice deploy` command is running, the custom domain name
will be created.

.. code-block:: json

    {
        "stages": {
            "dev": {
                "api_gateway_stage": "api",
                "websocket_api_custom_domain": {
                    "domain_name": "api.example.com",
                    "tls_version": "TLS_1_2|TLS_1_0",
                    "certificate_arn": "arn:aws:acm:example",
                    "url_prefix": "foo",
                    "tags": {
                        "key": "tag1",
                        "key1": "tag2"
                    }
                }
            }
        }
    }

Fields description
------------------

- domain_name:

    Custom domain name (api.example.com). Must match the domain registered
    with AWS Route53

- tls_version:

    The Transport Layer Security (TLS) version of the security policy for
    this domain name. The valid values are TLS_1_0 and TLS_1_2.

- certificate_arn:

    the arn of AWS-managed certificate for current domain name.

- url_prefix:

    (optional) A custom domain name plus a
    url_prefix (BasePathMapping) specification identifies a deployed
    RestApi in a given stage. With custom domain names, you can set up your
    API's hostname, and choose a base path (for example, `myservice`) to
    map the alternative URL to your API
    (for example ``https://api.example.com/myservice``).
    If you don't set any Api mapping keys under a custom domain name,
    the resulting API's base URL is the same as the custom domain
    (for example ``https://api.example.com``).
    In this case, the custom domain name can't support more than one API.
    Specify as `/` - the same as `(none)` -  means that callers haven't
    to specify a base path name after the domain name.
    If `/` won't be specified, it will be created by default.

- tags:

    (optional) a dictionary of tags associated with a domain name.
