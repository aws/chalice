=========
CHANGELOG
=========

0.5.1
=====

* Add support for serializing decimals in ``chalice local``
  (`#187 <https://github.com/awslabs/chalice/pull/187>`__)
* Add stdout handler for root logger when using ``chalice local``
  (`#186 <https://github.com/awslabs/chalice/pull/186>`__)
* Map query string parameters when using ``chalice local``
  (`#184 <https://github.com/awslabs/chalice/pull/184>`__)
* Support Content-Type with a charset
  (`#180 <https://github.com/awslabs/chalice/issues/180>`__)
* Fix not all resources being retrieved due to pagination
  (`#188 <https://github.com/awslabs/chalice/pull/188>`__)
* Fix issue where root resource was not being correctly retrieved
  (`#205 <https://github.com/awslabs/chalice/pull/205>`__)
* Handle case where local policy does not exist
  (`29 <https://github.com/awslabs/chalice/issues/29>`__)


0.5.0
=====

* Add default application logger
  (`#149 <https://github.com/awslabs/chalice/issues/149>`__)
* Return 405 when method is not supported when running
  ``chalice local``
  (`#159 <https://github.com/awslabs/chalice/issues/159>`__)
* Add path params as requestParameters so they can be used
  in generated SDKs as well as cache keys
  (`#163 <https://github.com/awslabs/chalice/issues/163>`__)
* Map cognito user pool claims as part of request context
  (`#165 <https://github.com/awslabs/chalice/issues/165>`__)
* Add ``chalice url`` command to print the deployed URL
  (`#169 <https://github.com/awslabs/chalice/pull/169>`__)
* Bump up retry limit on initial function creation to 30 seconds
  (`#172 <https://github.com/awslabs/chalice/pull/172>`__)
* Add support for ``DELETE`` and ``PATCH`` in ``chalice local``
  (`#167 <https://github.com/awslabs/chalice/issues/167>`__)
* Add ``chalice generate-sdk`` command
  (`#178 <https://github.com/awslabs/chalice/pull/178>`__)


0.4.0
=====

* Fix issue where role name to arn lookup was failing due to lack of pagination
  (`#139 <https://github.com/awslabs/chalice/issues/139>`__)
* Raise errors when unknown kwargs are provided to ``app.route(...)``
  (`#144 <https://github.com/awslabs/chalice/pull/144>`__)
* Raise validation error when configuring CORS and an OPTIONS method
  (`#142 <https://github.com/awslabs/chalice/issues/142>`__)
* Add support for multi-file applications
  (`#21 <https://github.com/awslabs/chalice/issues/21>`__)
* Add support for ``chalice local``, which runs a local HTTP server for testing
  (`#22 <https://github.com/awslabs/chalice/issues/22>`__)


0.3.0
=====

* Fix bug with case insensitive headers
  (`#129 <https://github.com/awslabs/chalice/issues/129>`__)
* Add initial support for CORS
  (`#133 <https://github.com/awslabs/chalice/pull/133>`__)
* Only add API gateway permissions if needed
  (`#48 <https://github.com/awslabs/chalice/issues/48>`__)
* Fix error when dict comprehension is encountered during policy generation
  (`#131 <https://github.com/awslabs/chalice/issues/131>`__)
* Add ``--version`` and ``--debug`` options to the chalice CLI


0.2.0
=====

* Add support for input content types besides ``application/json``
  (`#96 <https://github.com/awslabs/chalice/issues/96>`__)
* Allow ``ChaliceViewErrors`` to propagate, so that API Gateway
  can properly map HTTP status codes in non debug mode
  (`#113 <https://github.com/awslabs/chalice/issues/113>`__)
* Add windows compatibility
  (`#31 <https://github.com/awslabs/chalice/issues/31>`__,
   `#124 <https://github.com/awslabs/chalice/pull/124>`__,
   `#103 <https://github.com/awslabs/chalice/issues/103>`__)


0.1.0
=====

* Require ``virtualenv`` as a package dependency.
  (`#33 <https://github.com/awslabs/chalice/issues/33>`__)
* Add ``--profile`` option when creating a new project
  (`#28 <https://github.com/awslabs/chalice/issues/28>`__)
* Add support for more error codes exceptions
  (`#34 <https://github.com/awslabs/chalice/issues/34>`__)
* Improve error validation when routes containing a
  trailing ``/`` char
  (`#65 <https://github.com/awslabs/chalice/issues/65>`__)
* Validate duplicate route entries
  (`#79 <https://github.com/awslabs/chalice/issues/79>`__)
* Ignore lambda expressions in policy analyzer
  (`#74 <https://github.com/awslabs/chalice/issues/74>`__)
* Print original error traceback in debug mode
  (`#50 <https://github.com/awslabs/chalice/issues/50>`__)
* Add support for authenticate routes
  (`#14 <https://github.com/awslabs/chalice/issues/14>`__)
* Add ability to disable IAM role management
  (`#61 <https://github.com/awslabs/chalice/issues/61>`__)
