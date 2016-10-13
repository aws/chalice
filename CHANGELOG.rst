=========
CHANGELOG
=========

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
