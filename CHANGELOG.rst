=========
CHANGELOG
=========

1.26.1
======

* enhancement:Dependencies:Bump pip dependency to latest released version (#1817)
* enhancement:Tests:Don't include tests package in .whl file (#1814)


1.26.0
======

* feature:Websockets:Add support for setting the Websocket protocol from the connect handler (#1768)
* feature:SQS:Added MaximumBatchingWindowInSeconds to SQS event handler (#1778)


1.25.0
======

* feature:Python:Add support for Python 3.9 (#1787)


1.24.2
======

* enhancement:Dependencies:Bump attrs dependency to latest version (#1786)
* bugfix:Auth:Fix ARN parsing when generating a builtin AuthResponse (#1775)
* enhancement:CLI:Upgrade Click dependency to support v8.0.0 (#1729)


1.24.1
======

* bugfix:GovCloud:Fix partition error when updating API Gateway in GovCloud region (#1770)


1.24.0
======

* feature:Python2.7:Remove support for Python 2.7 (#1766)
* enhancement:Terraform:Update Terraform packaging to support version 1.0 (#1757)
* enhancement:Typing:Add missing WebsocketEvent type information (#1746)
* enhancement:S3 events:Add source account to Lambda permissions when configuring S3 events (#1635)
* enhancement:Packaging:Add support for Terraform v0.15 (#1725)


1.23.0
======

* enhancement:Deploy:Wait for function state to be active when deploying
* feature:SQS:Add queue_arn parameter to enable CDK integration with SQS event handler (#1681)


1.22.4
======

* enhancement:Types:Add missing types to app.pyi stub file (#1701)
* bugfix:Custom Domain:Fix custom domain generation when using the CDK (#1640)
* bugfix:Packaging:Special cases pyrsistent packaging (#1696)


1.22.3
======

* enhancement:Terraform:Bump Terraform version to include 0.14
* bugfix:Typing:Fix type definitions in app.pyi (#1676)
* bugfix:Terraform:Use references instead of function names in Terraform packaging (#1558)


1.22.2
======

* enhancement:Blueprint:Add log property to blueprint
* bugfix:Pipeline:Fix build command in pipeline generation (#1653)
* enhancement:Dependencies:Change enum-compat dependency to enum34 with version restrictions (#1667)


1.22.1
======

* enhancement:Pip:Bump pip version range to latest version 21.x (#1630)
* enhancement:IAM:Improve client call collection when generation policies (#692)


1.22.0
======

* feature:CDK:Add built-in support for the AWS CDK (#1622)


1.21.9
======

* enhancement:Dependencies:Bump attr version constraint (#1620)


1.21.8
======

* enhancement:Authorizers:Add support for custom headers in built-in authorizers (#1613)


1.21.7
======

* enhancement:Terraform:Map custom domain outputs in Terraform packaging (#1601)


1.21.6
======

* enhancement:Packaging:Increase upper bound for AWS provider in Terraform to 3.x (#1596)
* enhancement:Packaging:Add support for manylinux2014 wheels (#1551)


1.21.5
======

* bugfix:Config:Fix config validation for env vars on py27 (#1573)
* bugfix:Pip:Bump pip version contraint (#1590)
* bugfix:REST:Add Allow header with list of allowed methods when returning 405 error (#1583)


1.21.4
======

* enhancement:Local:Allow custom Chalice class in local mode (#1502)
* bugfix:Layers:Ensure single reference to managed layer (#1563)


1.21.3
======

* enhancement:Test:Add test client methods for generating sample kinesis events
* enhancement:Config:Validate env var values are strings (#1543)


1.21.2
======

* bugfix:Terraform:Fix issue with wildcard partition names in s3 event handlers (#1508)
* bugfix:Auth:Fix special case processing for root URL auth (#1271)
* enhancement:Middleware:Add support for HTTP middleware catching exceptions (#1541)


1.21.1
======

* bugfix:Websockets:Fix custom domain name configuration for websockets (#1531)
* bugfix:Local:Add support for multiple actions in builtin auth in local mode (#1527)
* bugfix:Websocket:Fix websocket client configuration when using a custom domain (#1503)
* bugfix:Local:Fix CORs handling in local mode (#761)


1.21.0
======

* bugfix:Blueprints:Fix regression when invoking Lambda functions from blueprints (#1535)
* feature:Events:Add support for Kinesis and DynamoDB event handlers (#987)


1.20.1
======

* bugfix:Blueprints:Preserve docstring in blueprints (#1525)
* enhancement:Binary:Support returning native python types when using `*/*` for binary types (#1501)


1.20.0
======

* enhancement:Blueprints:Add `current_app` property to Blueprints (#1094)
* enhancement:CLI:Set `AWS_CHALICE_CLI_MODE` env var whenever a Chalice CLI command is run (#1200)
* feature:Middleware:Add support for middleware (#1509)
* feature:X-Ray:Add support for AWS X-Ray (#464)


1.19.0
======

* feature:Pipeline:Add a new v2 template for the deployment pipeline CloudFormation template (#1506)


1.18.1
======

* bugfix:Packaging:Add fallback to retrieve name/version from sdist (#1486)
* bugfix:Analyzer:Handle symbols with multiple (shadowed) namespaces (#1494)


1.18.0
======

* feature:Packaging:Add support for automatic layer creation (#1485, #1001)


1.17.0
======

* feature:Testing:Add Chalice test client (#1468)
* enhancement:regions:Add support for non `aws` partitions including aws-cn and aws-us-gov (#792).
* bugfix:dependencies:Fix error when using old versions of click by requiring >=7
* bugfix:local:Fix local mode builtin authorizer not stripping query string from URL (#1470)


1.16.0
======

* enhancement:local:Avoid error from cognito client credentials in local authorizer (#1447)
* bugfix:package:Traverse symlinks to directories when packaging the vendor directory (#583).
* feature:DomainName:Add support for custom domain names to REST/WebSocket APIs (#1194)
* feature:auth:Add support for oauth scopes on routes (#1444).


1.15.1
======

* bugfix:packaging:Fix setup.py dependencies where the wheel package was not being installed (#1435)


1.15.0
======

* feature:blueprints:Mark blueprints as an accepted API (#1250)
* feature:package:Add ability to generate and merge yaml CloudFormation templates (#1425)
* enhancement:terraform:Allow generated terraform template to be used as a terraform module (#1300)
* feature:logs:Add support for tailing logs (#4).


1.14.1
======

* enhancement:pip:Update pip version range to 20.1.


1.14.0
======

* bugfix:packaging:Fix pandas packaging regression (#1398)
* feature:CLI:Add ``dev plan/appgraph`` commands (#1396)
* enhancement:SQS:Validate queue name is used and not queue URL or ARN (#1388)


1.13.1
======

* enhancement:local:Add support for multiValueHeaders in local mode (#1381).
* bugfix:local:Make ``current_request`` thread safe in local mode (#759)
* enhancement:local:Add support for cognito in local mode (#1377).
* bugfix:packaging:Fix terraform generation when injecting custom domains (#1237)
* enhancement:packaging:Ensure repeatable zip file generation (#1114).
* bugfix:CORS:Fix CORS request when returning compressed binary types (#1336)


1.13.0
======

* bugfix:logs:Fix error for ``chalice logs`` when a Lambda function
  has not been invoked
  (`#1252 <https://github.com/aws/chalice/issues/1252>`__)
* feature:CORS:Add global CORS configuration
  (`#70 <https://github.com/aws/chalice/pull/70>`__)
* bugfix:packaging:Fix packaging simplejson
  (`#1304 <https://github.com/aws/chalice/pull/1304>`__)
* feature:python:Add support for Python 3.8
  (`#1315 <https://github.com/aws/chalice/pull/1315>`__)
* feature:authorizer:Add support for invocation role in custom authorizer
  (`#1303 <https://github.com/aws/chalice/pull/1303>`__)
* bugfix:packaging:Fix packaging on case-sensitive filesystems
  (`#1356 <https://github.com/aws/chalice/pull/1356>`__)


1.12.0
======

* feature:CLI:Add ``generate-models`` command
  (`#1245 <https://github.com/aws/chalice/pull/1245>`__)
* enhancement:websocket:Add ``close`` and ``info`` commands to websocket api
  (`#1259 <https://github.com/aws/chalice/pull/1259>`__)
* enhancement:dependencies:Bump upper bound on PIP to ``<19.4``
  (`#1273 <https://github.com/aws/chalice/pull/1273>`__)
  (`#1272 <https://github.com/aws/chalice/pull/1272>`__)


1.11.1
======

* bugfix:blueprint:Fix mouting blueprints with root routes
  (`#1230 <https://github.com/aws/chalice/pull/1230>`__)
* feature:rest-api:Add support for multi-value headers responses
  (`#1205 <https://github.com/aws/chalice/pull/1205>`__)


1.11.0
======

* feature:config:Add support for stage independent lambda configuration
  (`#1162 <https://github.com/aws/chalice/pull/1162>`__)
* feature:event-source:Add support for subscribing to CloudWatch Events
  (`#1126 <https://github.com/aws/chalice/pull/1126>`__)
* feature:event-source:Add a ``description`` argument to CloudWatch schedule events
  (`#1155 <https://github.com/aws/chalice/pull/1155>`__)
* bugfix:rest-api:Fix deployment of API Gateway resource policies
  (`#1220 <https://github.com/aws/chalice/pull/1220>`__)


1.10.0
======

* feature:websocket:Add experimental support for websockets
  (`#1017 <https://github.com/aws/chalice/issues/1017>`__)
* feature:rest-api:API Gateway Endpoint Type Configuration
  (`#1160 <https://github.com/aws/chalice/pull/1160>`__)
* feature:rest-api:API Gateway Resource Policy Configuration
  (`#1160 <https://github.com/aws/chalice/pull/1160>`__)
* feature:packaging:Add --merge-template option to package command
  (`#1195 <https://github.com/aws/chalice/pull/1195>`__)
* feature:packaging:Add support for packaging via terraform
  (`#1129 <https://github.com/aws/chalice/pull/1129>`__)


1.9.1
=====

* enhancement:rest-api:Make MultiDict mutable
  (`#1158 <https://github.com/aws/chalice/issues/1158>`__)


1.9.0
=====

* enhancement:dependencies:Update PIP to support up to 19.1.x
  (`#1104 <https://github.com/aws/chalice/issues/1104>`__)
* bugfix:rest-api:Fix handling of more complex Accept headers for binary
  content types
  (`#1078 <https://github.com/aws/chalice/issues/1078>`__)
* enhancement:rest-api:Raise TypeError when trying to serialize an unserializable
  type
  (`#1100 <https://github.com/aws/chalice/issues/1100>`__)
* enhancement:policy:Update ``policies.json`` file
  (`#1110 <https://github.com/aws/chalice/issues/1110>`__)
* feature:rest-api:Support repeating values in the query string
  (`#1131 <https://github.com/aws/chalice/issues/1131>`__)
* feature:packaging:Add layer support to chalice package
  (`#1130 <https://github.com/aws/chalice/issues/1130>`__)
* bugfix:rest-api:Fix bug with route ``name`` kwarg raising a ``TypeError``
  (`#1112 <https://github.com/aws/chalice/issues/1112>`__)
* enhancement:logging:Change exceptions to always be logged at the ERROR level
  (`#969 <https://github.com/aws/chalice/issues/969>`__)
* bugfix:CLI:Fix bug handling exceptions during ``chalice invoke`` on
  Python 3.7
  (`#1139 <https://github.com/aws/chalice/issues/1139>`__)
* bugfix:rest-api:Add support for API Gateway compression
  (`#672 <https://github.com/aws/chalice/issues/672>`__)
* enhancement:packaging:Add support for both relative and absolute paths for
  ``--package-dir``
  (`#940 <https://github.com/aws/chalice/issues/940>`__)


1.8.0
=====

* bugfix:packaging:Fall back to pure python version of yaml parser
  when unable to compile C bindings for PyYAML
  (`#1074 <https://github.com/aws/chalice/issues/1074>`__)
* feature:packaging:Add support for Lambda layers.
  (`#1001 <https://github.com/aws/chalice/issues/1001>`__)


1.7.0
=====

* bugfix:packaging:Fix packaging multiple local directories as dependencies
  (`#1047 <https://github.com/aws/chalice/pull/1047>`__)
* feature:event-source:Add support for passing SNS ARNs to ``on_sns_message``
  (`#1048 <https://github.com/aws/chalice/pull/1048>`__)
* feature:blueprint:Add support for Blueprints
  (`#1023 <https://github.com/aws/chalice/pull/1023>`__)
* feature:config:Add support for opting-in to experimental features
  (`#1053 <https://github.com/aws/chalice/pull/1053>`__)
* feature:event-source:Provide Lambda context in event object
  (`#856 <https://github.com/aws/chalice/issues/856>`__)


1.6.2
=====

* enhancement:dependencies:Add support for pip 18.2
  (`#991 <https://github.com/aws/chalice/pull/991>`__)
* enhancement:logging:Add more detailed debug logs to the packager.
  (`#934 <https://github.com/aws/chalice/pull/934>`__)
* feature:python:Add support for python3.7
  (`#992 <https://github.com/aws/chalice/pull/992>`__)
* feature:rest-api:Support bytes for the application/json binary type
  (`#988 <https://github.com/aws/chalice/issues/988>`__)
* enhancement:rest-api:Use more compact JSON representation by default for dicts
  (`#958 <https://github.com/aws/chalice/pull/958>`__)
* enhancement:logging:Log internal exceptions as errors
  (`#254 <https://github.com/aws/chalice/issues/254>`__)
* feature:rest-api:Generate swagger documentation from docstrings
  (`#574 <https://github.com/aws/chalice/issues/574>`__)


1.6.1
=====

* bugfix:local:Fix local mode issue with unicode responses and Content-Length
  (`#910 <https://github.com/aws/chalice/pull/910>`__)
* enhancement:dev:Fix issue with ``requirements-dev.txt`` not setting up a working
  dev environment
  (`#920 <https://github.com/aws/chalice/pull/920>`__)
* enhancement:dependencies:Add support for pip 18
  (`#910 <https://github.com/aws/chalice/pull/908>`__)


1.6.0
=====

* feature:CLI:Add ``chalice invoke`` command
  (`#900 <https://github.com/aws/chalice/issues/900>`__)


1.5.0
=====

* feature:policy:Add support for S3 upload_file/download_file in
  policy generator
  (`#889 <https://github.com/aws/chalice/pull/889>`__)


1.4.0
=====

* enhancement:CI-CD:Add support for generating python 3.6 pipelines
  (`#858 <https://github.com/aws/chalice/pull/858>`__)
* feature:event-source:Add support for connecting lambda functions to S3 events
  (`#855 <https://github.com/aws/chalice/issues/855>`__)
* feature:event-source:Add support for connecting lambda functions to SNS message
  (`#488 <https://github.com/aws/chalice/issues/488>`__)
* enhancement:local:Make ``watchdog`` an optional dependency and add a built in
  ``stat()`` based file poller
  (`#867 <https://github.com/aws/chalice/issues/867>`__)
* feature:event-source:Add support for connecting lambda functions to an SQS queue
  (`#884 <https://github.com/aws/chalice/issues/884>`__)


1.3.0
=====

* feature:config:Add support for Lambdas in a VPC
  (`#413 <https://github.com/aws/chalice/issues/413>`__,
  `#837 <https://github.com/aws/chalice/pull/837>`__,
  `#673 <https://github.com/aws/chalice/pull/673>`__)
* feature:packaging:Add support for packaging local directories
  (`#653 <https://github.com/aws/chalice/pull/653>`__)
* enhancement:local:Add support for automatically reloading the local
  dev server when files are modified
  (`#316 <https://github.com/aws/chalice/issues/316>`__,
  `#846 <https://github.com/aws/chalice/pull/846>`__,
  `#706 <https://github.com/aws/chalice/pull/706>`__)
* enhancement:logging:Add support for viewing cloudwatch logs of all
  lambda functions
  (`#841 <https://github.com/aws/chalice/issues/841>`__,
  `#849 <https://github.com/aws/chalice/pull/849>`__)


1.2.3
=====

* enhancement:dependency:Add support for pip 10
  (`#808 <https://github.com/aws/chalice/issues/808>`__)
* enhancement:policy:Update ``policies.json`` file
  (`#817 <https://github.com/aws/chalice/issues/817>`__)


1.2.2
=====

* bugfix:packaging:Fix package command not correctly setting environment variables
  (`#795 <https://github.com/aws/chalice/issues/795>`__)


1.2.1
=====

* enhancement:rest-api:Add CORS headers to error response
  (`#715 <https://github.com/aws/chalice/pull/715>`__)
* bugfix:local:Fix parsing empty query strings in local mode
  (`#767 <https://github.com/aws/chalice/pull/767>`__)
* bugfix:packaging:Fix regression in ``chalice package`` when using role arns
  (`#793 <https://github.com/aws/chalice/issues/793>`__)


1.2.0
=====


This release features a rewrite of the core deployment
code used in Chalice.  This is a backwards compatible change
for users, but you may see changes to the autogenerated
files Chalice creates.
Please read the `upgrade notes for 1.2.0
<http://chalice.readthedocs.io/en/latest/upgrading.html#v1-2-0>`__
for more detailed information about upgrading to this release.


* enhancement:rest-api:Print out full stack trace when an error occurs
  (`#711 <https://github.com/aws/chalice/issues/711>`__)
* enhancement:rest-api:Add ``image/jpeg`` as a default binary content type
  (`#707 <https://github.com/aws/chalice/pull/707>`__)
* feature:event-source:Add support for AWS Lambda only projects
  (`#162 <https://github.com/aws/chalice/issues/162>`__,
  `#640 <https://github.com/aws/chalice/issues/640>`__)
* bugfix:policy:Fix inconsistent IAM role generation with pure lambdas
  (`#685 <https://github.com/aws/chalice/issues/685>`__)
* enhancement:deployment:Rewrite Chalice deployer to more easily support additional AWS resources
  (`#604 <https://github.com/aws/chalice/issues/604>`__)
* feature:packaging:Update the ``chalice package`` command to support
  pure lambda functions and scheduled events.
  (`#772 <https://github.com/aws/chalice/issues/772>`__)
* bugfix:packaging:Fix packager edge case normalizing sdist names
  (`#778 <https://github.com/aws/chalice/issues/778>`__)
* bugfix:packaging:Fix SQLAlchemy packaging
  (`#778 <https://github.com/aws/chalice/issues/778>`__)
* bugfix:packaging:Fix packaging abi3, wheels this fixes cryptography 2.2.x packaging
  (`#764 <https://github.com/aws/chalice/issues/764>`__)


1.1.1
=====

* feature:CLI:Add ``--connection-timeout`` to the ``deploy`` command
  (`#344 <https://github.com/aws/chalice/issues/344>`__)
* bugfix:policy:Fix IAM role creation issue
  (`#565 <https://github.com/aws/chalice/issues/565>`__)
* bugfix:local:Fix `chalice local` handling of browser requests
  (`#565 <https://github.com/aws/chalice/issues/628>`__)
* enhancement:policy:Support async/await syntax in automatic policy generation
  (`#565 <https://github.com/aws/chalice/issues/646>`__)
* enhancement:packaging:Support additional PyPi package formats (.tar.bz2)
  (`#720 <https://github.com/aws/chalice/issues/720>`__)


1.1.0
=====

* enhancement:rest-api:Default to ``None`` in local mode when no query parameters
  are provided
  (`#593 <https://github.com/aws/chalice/issues/593>`__)
* enhancement:local:Add support for binding a custom address for local dev server
  (`#596 <https://github.com/aws/chalice/issues/596>`__)
* bugfix:rest-api:Fix local mode handling of routes with trailing slashes
  (`#582 <https://github.com/aws/chalice/issues/582>`__)
* bugfix:config:Scale ``lambda_timeout`` parameter correctly in local mode
  (`#579 <https://github.com/aws/chalice/pull/579>`__)
* feature:CI-CD:Add ``--codebuild-image`` to the ``generate-pipeline`` command
  (`#609 <https://github.com/aws/chalice/issues/609>`__)
* feature:CI-CD:Add ``--source`` and ``--buildspec-file`` to the
  ``generate-pipeline`` command
  (`#609 <https://github.com/aws/chalice/issues/619>`__)


1.0.4
=====

* bugfix:packaging:Fix issue deploying some packages in Windows with utf-8 characters
  (`#560 <https://github.com/aws/chalice/pull/560>`__)
* feature:packaging:Add support for custom authorizers with ``chalice package``
  (`#580 <https://github.com/aws/chalice/pull/580>`__)


1.0.3
=====

* bugfix:packaging:Fix issue with some packages with `-` or `.` in their distribution name
  (`#555 <https://github.com/aws/chalice/pull/555>`__)
* bugfix:rest-api:Fix issue where chalice local returned a 403 for successful OPTIONS requests
  (`#554 <https://github.com/aws/chalice/pull/554>`__)
* bugfix:local:Fix issue with chalice local mode causing http clients to hang on responses
  with no body
  (`#525 <https://github.com/aws/chalice/issues/525>`__)
* enhancement:local:Add ``--stage`` parameter to ``chalice local``
  (`#545 <https://github.com/aws/chalice/issues/545>`__)
* bugfix:policy:Fix issue with analyzer that followed recursive functions infinitely
  (`#531 <https://github.com/aws/chalice/issues/531>`__)


1.0.2
=====

* bugfix:rest-api:Fix issue where requestParameters were not being mapped
  correctly resulting in invalid generated javascript SDKs
  (`#498 <https://github.com/aws/chalice/issues/498>`__)
* bugfix:rest-api:Fix issue where ``api_gateway_stage`` was being
  ignored when set in the ``config.json`` file
  (`#495 <https://github.com/aws/chalice/issues/495>`__)
* bugfix:rest-api:Fix bug where ``raw_body`` would raise an exception if no HTTP
  body was provided
  (`#503 <https://github.com/aws/chalice/issues/503>`__)
* bugfix:CLI:Fix bug where exit codes were not properly being propagated during packaging
  (`#500 <https://github.com/aws/chalice/issues/500>`__)
* feature:local:Add support for Builtin Authorizers in local mode
  (`#404 <https://github.com/aws/chalice/issues/404>`__)
* bugfix:packaging:Fix environment variables being passed to subprocess while packaging
  (`#501 <https://github.com/aws/chalice/issues/501>`__)
* enhancement:rest-api:Allow view to require API keys as well as authorization
  (`#473 <https://github.com/aws/chalice/pull/473/>`__)


1.0.1
=====

* bugfix:packaging:Only use alphanumeric characters for event names in SAM template
  (`#450 <https://github.com/aws/chalice/issues/450>`__)
* enhancement:config:Print useful error message when config.json is invalid
  (`#458 <https://github.com/aws/chalice/pull/458>`__)
* bugfix:rest-api:Fix api gateway stage being set incorrectly in non-default chalice stage
  (`#$70 <https://github.com/aws/chalice/issues/470>`__)


1.0.0
=====

* enhancement:rest-api:Change default API Gateway stage name to ``api``
  (`#431 <https://github.com/awslabs/chalice/pull/431>`__)
* enhancement:local:Add support for ``CORSConfig`` in ``chalice local``
  (`#436 <https://github.com/awslabs/chalice/issues/436>`__)
* enhancement:logging:Propagate ``DEBUG`` log level when setting ``app.debug``
  (`#386 <https://github.com/awslabs/chalice/issues/386>`__)
* feature:rest-api:Add support for wildcard routes and HTTP methods in ``AuthResponse``
  (`#403 <https://github.com/awslabs/chalice/issues/403>`__)
* bugfix:policy:Fix bug when analyzing list comprehensions
  (`#412 <https://github.com/awslabs/chalice/issues/412>`__)
* enhancement:local:Update ``chalice local`` to use HTTP 1.1
  (`#448 <https://github.com/awslabs/chalice/pull/448>`__)


1.0.0b2
=======


Please read the `upgrade notes for 1.0.0b2
<http://chalice.readthedocs.io/en/latest/upgrading.html#v1-0-0b2>`__
for more detailed information about upgrading to this release.

Note: to install this beta version of chalice you must specify
``pip install 'chalice>=1.0.0b2,<2.0.0'`` or
use the ``--pre`` flag for pip: ``pip install --pre chalice``.

* enhancement:local:Set env vars from config in ``chalice local``
  (`#396 <https://github.com/awslabs/chalice/issues/396>`__)
* bugfix:packaging:Fix edge case when building packages with optional c extensions
  (`#421 <https://github.com/awslabs/chalice/pull/421>`__)
* enhancement:policy:Remove legacy ``policy.json`` file support. Policy files must
  use the stage name, e.g. ``policy-dev.json``
  (`#430 <https://github.com/awslabs/chalice/pull/540>`__)
* bugfix:deployment:Fix issue where IAM role policies were updated twice on redeploys
  (`#428 <https://github.com/awslabs/chalice/pull/428>`__)
* enhancement:rest-api:Validate route path is not an empty string
  (`#432 <https://github.com/awslabs/chalice/pull/432>`__)
* enhancement:rest-api:Change route code to invoke view function with kwargs instead of
  positional args
  (`#429 <https://github.com/awslabs/chalice/issues/429>`__)


1.0.0b1
=======


Please read the `upgrade notes for 1.0.0b1
<http://chalice.readthedocs.io/en/latest/upgrading.html#v1-0-0b1>`__
for more detailed information about upgrading to this release.

Note: to install this beta version of chalice you must specify
``pip install 'chalice>=1.0.0b1,<2.0.0'`` or
use the ``--pre`` flag for pip: ``pip install --pre chalice``.


* bugfix:rest-api:Fix unicode responses being quoted in python 2.7
  (`#262 <https://github.com/awslabs/chalice/issues/262>`__)
* feature:event-source:Add support for scheduled events
  (`#390 <https://github.com/awslabs/chalice/issues/390>`__)
* feature:event-source:Add support for pure lambda functions
  (`#390 <https://github.com/awslabs/chalice/issues/400>`__)
* feature:packaging:Add support for wheel packaging.
  (`#249 <https://github.com/awslabs/chalice/issues/249>`__)


0.10.1
======

* bugfix:deployment:Fix deployment issue for projects deployed with versions
  prior to 0.10.0
  (`#387 <https://github.com/awslabs/chalice/issues/387>`__)
* bugfix:policy:Fix crash in analyzer when encountering genexprs and listcomps
  (`#263 <https://github.com/awslabs/chalice/issues/263>`__)


0.10.0
======

* bugfix:deployment:Fix issue where provided ``iam_role_arn`` was not respected on
  redeployments of chalice applications and in the CloudFormation template
  generated by ``chalice package``
  (`#339 <https://github.com/awslabs/chalice/issues/339>`__)
* bugfix:config:Fix ``autogen_policy`` in config being ignored
  (`#367 <https://github.com/awslabs/chalice/pull/367>`__)
* feature:rest-api:Add support for view functions that share the same view url but
  differ by HTTP method
  (`#81 <https://github.com/awslabs/chalice/issues/81>`__)
* enhancement:deployment:Improve deployment error messages for deployment packages that are
  too large
  (`#246 <https://github.com/awslabs/chalice/issues/246>`__,
  `#330 <https://github.com/awslabs/chalice/issues/330>`__,
  `#380 <https://github.com/awslabs/chalice/pull/380>`__)
* feature:rest-api:Add support for built-in authorizers
  (`#356 <https://github.com/awslabs/chalice/issues/356>`__)


0.9.0
=====

* feature:rest-api:Add support for ``IAM`` authorizer
  (`#334 <https://github.com/awslabs/chalice/pull/334>`__)
* feature:config:Add support for configuring ``lambda_timeout``, ``lambda_memory_size``,
  and ``tags`` in your AWS Lambda function
  (`#347 <https://github.com/awslabs/chalice/issues/347>`__)
* bugfix:packaging:Fix vendor directory contents not being importable locally
  (`#350 <https://github.com/awslabs/chalice/pull/350>`__)
* feature:rest-api:Add support for binary payloads
  (`#348 <https://github.com/awslabs/chalice/issues/348>`__)


0.8.2
=====

* bugfix:CLI:Fix issue where ``--api-gateway-stage`` was being
  ignored (`#325 <https://github.com/awslabs/chalice/pull/325>`__)
* feature:CLI:Add ``chalice delete`` command
  (`#40 <https://github.com/awslabs/chalice/issues/40>`__)


0.8.1
=====

* enhancement:deployment:Alway overwrite existing API Gateway Rest API on updates
  (`#305 <https://github.com/awslabs/chalice/issues/305>`__)
* enhancement:CORS:Added more granular support for CORS
  (`#311 <https://github.com/awslabs/chalice/pull/311>`__)
* bugfix:local:Fix duplicate content type header in local model
  (`#311 <https://github.com/awslabs/chalice/issues/310>`__)
* bugfix:rest-api:Fix content type validation when charset is provided
  (`#306 <https://github.com/awslabs/chalice/issues/306>`__)
* enhancement:rest-api:Add back custom authorizer support
  (`#322 <https://github.com/awslabs/chalice/pull/322>`__)


0.8.0
=====

* feature:python:Add support for python3!
  (`#296 <https://github.com/awslabs/chalice/pull/296>`__)
* bugfix:packaging:Fix swagger generation when using ``api_key_required=True``
  (`#279 <https://github.com/awslabs/chalice/issues/279>`__)
* bugfix:CI-CD:Fix ``generate-pipeline`` to install requirements file before packaging
  (`#295 <https://github.com/awslabs/chalice/pull/295>`__)


0.7.0
=====

* feature:CLI:Add ``chalice package`` command.  This will
  create a SAM template and Lambda deployment package that
  can be subsequently deployed by AWS CloudFormation.
  (`#258 <https://github.com/awslabs/chalice/pull/258>`__)
* feature:CLI:Add a ``--stage-name`` argument for creating chalice stages.
  A chalice stage is a completely separate set of AWS resources.
  As a result, most configuration values can also be specified
  per chalice stage.
  (`#264 <https://github.com/awslabs/chalice/pull/264>`__,
  `#270 <https://github.com/awslabs/chalice/pull/270>`__)
* feature:policy:Add support for ``iam_role_file``, which allows you to
  specify the file location of an IAM policy to use for your app
  (`#272 <https://github.com/awslabs/chalice/pull/272>`__)
* feature:config:Add support for setting environment variables in your app
  (`#273 <https://github.com/awslabs/chalice/pull/273>`__)
* feature:CI-CD:Add a ``generate-pipeline`` command
  (`#277 <https://github.com/awslabs/chalice/pull/277>`__)


0.6.0
=====


Check out the `upgrade notes for 0.6.0
<http://chalice.readthedocs.io/en/latest/upgrading.html#v0-6-0>`__
for more detailed information about changes in this release.


* feature:local:Add port parameter to local command
  (`#220 <https://github.com/awslabs/chalice/pull/220>`__)
* feature:packaging:Add support for binary vendored packages
  (`#182 <https://github.com/awslabs/chalice/pull/182>`__,
  `#106 <https://github.com/awslabs/chalice/issues/106>`__,
  `#42 <https://github.com/awslabs/chalice/issues/42>`__)
* feature:rest-api:Add support for customizing the returned HTTP response
  (`#240 <https://github.com/awslabs/chalice/pull/240>`__,
  `#218 <https://github.com/awslabs/chalice/issues/218>`__,
  `#110 <https://github.com/awslabs/chalice/issues/110>`__,
  `#30 <https://github.com/awslabs/chalice/issues/30>`__,
  `#226 <https://github.com/awslabs/chalice/issues/226>`__)
* enhancement:packaging:Always inject latest runtime to allow for chalice upgrades
  (`#245 <https://github.com/awslabs/chalice/pull/245>`__)


0.5.1
=====

* enhancement:local:Add support for serializing decimals in ``chalice local``
  (`#187 <https://github.com/awslabs/chalice/pull/187>`__)
* enhancement:local:Add stdout handler for root logger when using ``chalice local``
  (`#186 <https://github.com/awslabs/chalice/pull/186>`__)
* enhancement:local:Map query string parameters when using ``chalice local``
  (`#184 <https://github.com/awslabs/chalice/pull/184>`__)
* enhancement:rest-api:Support Content-Type with a charset
  (`#180 <https://github.com/awslabs/chalice/issues/180>`__)
* bugfix:deployment:Fix not all resources being retrieved due to pagination
  (`#188 <https://github.com/awslabs/chalice/pull/188>`__)
* bugfix:deployment:Fix issue where root resource was not being correctly retrieved
  (`#205 <https://github.com/awslabs/chalice/pull/205>`__)
* bugfix:deployment:Handle case where local policy does not exist
  (`29 <https://github.com/awslabs/chalice/issues/29>`__)


0.5.0
=====

* enhancement:logging:Add default application logger
  (`#149 <https://github.com/awslabs/chalice/issues/149>`__)
* enhancement:local:Return 405 when method is not supported when running
  ``chalice local``
  (`#159 <https://github.com/awslabs/chalice/issues/159>`__)
* enhancement:SDK:Add path params as requestParameters so they can be used
  in generated SDKs as well as cache keys
  (`#163 <https://github.com/awslabs/chalice/issues/163>`__)
* enhancement:rest-api:Map cognito user pool claims as part of request context
  (`#165 <https://github.com/awslabs/chalice/issues/165>`__)
* feature:CLI:Add ``chalice url`` command to print the deployed URL
  (`#169 <https://github.com/awslabs/chalice/pull/169>`__)
* enhancement:deployment:Bump up retry limit on initial function creation to 30 seconds
  (`#172 <https://github.com/awslabs/chalice/pull/172>`__)
* feature:local:Add support for ``DELETE`` and ``PATCH`` in ``chalice local``
  (`#167 <https://github.com/awslabs/chalice/issues/167>`__)
* feature:CLI:Add ``chalice generate-sdk`` command
  (`#178 <https://github.com/awslabs/chalice/pull/178>`__)


0.4.0
=====

* bugfix:deployment:Fix issue where role name to arn lookup was failing due to lack of pagination
  (`#139 <https://github.com/awslabs/chalice/issues/139>`__)
* enhancement:rest-api:Raise errors when unknown kwargs are provided to ``app.route(...)``
  (`#144 <https://github.com/awslabs/chalice/pull/144>`__)
* enhancement:config:Raise validation error when configuring CORS and an OPTIONS method
  (`#142 <https://github.com/awslabs/chalice/issues/142>`__)
* feature:rest-api:Add support for multi-file applications
  (`#21 <https://github.com/awslabs/chalice/issues/21>`__)
* feature:local:Add support for ``chalice local``, which runs a local HTTP server for testing
  (`#22 <https://github.com/awslabs/chalice/issues/22>`__)


0.3.0
=====

* bugfix:rest-api:Fix bug with case insensitive headers
  (`#129 <https://github.com/awslabs/chalice/issues/129>`__)
* feature:CORS:Add initial support for CORS
  (`#133 <https://github.com/awslabs/chalice/pull/133>`__)
* enhancement:deployment:Only add API gateway permissions if needed
  (`#48 <https://github.com/awslabs/chalice/issues/48>`__)
* bugfix:policy:Fix error when dict comprehension is encountered during policy generation
  (`#131 <https://github.com/awslabs/chalice/issues/131>`__)
* enhancement:CLI:Add ``--version`` and ``--debug`` options to the chalice CLI


0.2.0
=====

* enhancement:rest-api:Add support for input content types besides ``application/json``
  (`#96 <https://github.com/awslabs/chalice/issues/96>`__)
* enhancement:rest-api:Allow ``ChaliceViewErrors`` to propagate, so that API Gateway
  can properly map HTTP status codes in non debug mode
  (`#113 <https://github.com/awslabs/chalice/issues/113>`__)
* enhancement:deployment:Add windows compatibility
  (`#31 <https://github.com/awslabs/chalice/issues/31>`__,
  `#124 <https://github.com/awslabs/chalice/pull/124>`__,
  `#103 <https://github.com/awslabs/chalice/issues/103>`__)


0.1.0
=====

* enhancement:packaging:Require ``virtualenv`` as a package dependency.
  (`#33 <https://github.com/awslabs/chalice/issues/33>`__)
* enhancement:CLI:Add ``--profile`` option when creating a new project
  (`#28 <https://github.com/awslabs/chalice/issues/28>`__)
* enhancement:rest-api:Add support for more error codes exceptions
  (`#34 <https://github.com/awslabs/chalice/issues/34>`__)
* enhancement:rest-api:Improve error validation when routes containing a
  trailing ``/`` char
  (`#65 <https://github.com/awslabs/chalice/issues/65>`__)
* enhancement:rest-api:Validate duplicate route entries
  (`#79 <https://github.com/awslabs/chalice/issues/79>`__)
* enhancement:policy:Ignore lambda expressions in policy analyzer
  (`#74 <https://github.com/awslabs/chalice/issues/74>`__)
* enhancement:rest-api:Print original error traceback in debug mode
  (`#50 <https://github.com/awslabs/chalice/issues/50>`__)
* feature:rest-api:Add support for authenticate routes
  (`#14 <https://github.com/awslabs/chalice/issues/14>`__)
* feature:policy:Add ability to disable IAM role management
  (`#61 <https://github.com/awslabs/chalice/issues/61>`__)


