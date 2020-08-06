Custom Domain Names
===================

Custom domain names are simpler and more intuitive URLs
that you can provide to your API users.
With custom domain names, you can set up your API's hostname,
and choose a base path to map the alternative URL to your API.

You must have an AWS managed certificate created or imported through
AWS Certificate Manager (ACM) in order to configure a custom domain name
for REST and WebSocket APIs.
See `Get certificate in AWS Certificate Manager <https://docs.aws.amazon.com/apigateway/latest/developerguide/how-to-custom-domains-prerequisites.html>`__
for more information.

Custom domain name can be configured per Chalice stage.

.. note::
    This document describes the configuration option and process
    needed to configure a custom domain with your Chalice application.
    If you'd like a step-by-step example that walks you through configuring
    a custom domain for a Chalice app using Amazon Route53 and ACM, see
    the :doc:`../tutorials/customdomain` tutorial.

There are two steps to configuring a custom domain name.  First you must
configure your Chalice app such that it creates the necessary resources
and configuration when provisioning your REST or WebSocket APIs.  This
is explained in the next two sections below.
Then you must configure your DNS configuration to point your custom domain
name to the domain name created by API Gateway.  This is explained in the
:ref:`dns-last-config` section below.

Configure custom domain name for REST API
-----------------------------------------

To create custom domain name for REST API, add the
``api_gateway_custom_domain`` configuration option to your
``.chalice/config.json`` file.  You must specify the ``certificate_arn``,
which is the ARN of your ACM certificate associated with your domain as
well as your ``domain_name``.  The remaining fields are optional and
may be omitted.  By default TLS 1.2 is used for your endpoint unless
otherwise specified.

Below is an example of all the configuration options you can specify
when configuring a custom domain.  They are explained in the
:ref:`custom-domain-config-options` section of the :doc:`configfile`
documentation.

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

Configure custom domain name for WebSocket
------------------------------------------

To create custom domain name for WebSocket API, add the
``websocket_api_custom_domain`` configuration option to your
``.chalice/config.json`` file.

Below is an example of all the configuration options you can specify when
configuring a custom domain for a WebSocket API.  They are explained in the
:ref:`custom-domain-ws-config-options` section of the :doc:`configfile`
documentation.

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


.. _dns-last-config:

DNS Configuration
-----------------

Chalice only configures your API Gateway API with the necessary resources
and configuration so a custom domain can be used.  It does not alter any
existing DNS records you have associated with your domain name.  After you've
deployed your Chalice app with the configuration options described above,
you'll need to modify your DNS records to point to your API Gateway API
using the web interface or API of your domain registrar associated with
your domain name.  When you run ``chalice deploy`` with a custom domain
configured, there will be two new fields in the output::

    $ chalice deploy
    Creating deployment package.
    Updating policy for IAM role: customdomain-dev
    Updating lambda function: customdomain-dev
    Updating rest API
    Creating custom domain name: api.chalice-demo-app.com
    Creating api mapping: /
    Resources deployed:
      - Lambda ARN: arn:aws:lambda:us-west-2:0123456789:function:customdomain-dev
      - Rest API URL: https://qxea58abcd.execute-api.us-west-2.amazonaws.com/api/
      - Custom domain name:
          HostedZoneId: Z1UJRXOUMOOFQ8
          AliasDomainName: d-6vj4cynstd.execute-api.us-west-2.amazonaws.com

If you're using Route53 to manage your hosted zone, you'll need to create
an Alias record using the ``HostedZoneId`` and ``AliasDomainName`` specified
in the output of ``chalice deploy``.  If you're using a third party domain
registrar, you'll need to create a CNAME record to the ``AliasDomainName``.
If you'd like a step-by-step example of how to do this with Route53, see
the :doc:`../tutorials/customdomain` tutorial.
