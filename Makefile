# Eventually I'll add:
# py.test --cov chalice --cov-report term-missing --cov-fail-under 95 tests/
# which will fail if tests are under 95%
TESTS=tests/unit tests/functional tests/integration

check:
	ruff check
	pylint --rcfile .pylintrc -E chalice
	#
	# Proper docstring conventions according to pep257
	#
	#
	pydocstyle --add-ignore=D100,D101,D102,D103,D104,D105,D107,D204,D301 --match='(?!(test_|regions)).*\.py' chalice/

test:
	py.test -v $(TESTS)

typecheck:
	mypy --ignore-missing-imports --follow-imports=skip -p chalice --disallow-untyped-defs --strict-optional --warn-no-return

coverage:
	py.test --cov chalice --cov-report term-missing $(TESTS)

coverage-unit:
	py.test --cov chalice --cov-report term-missing tests/unit

htmlcov:
	py.test --cov chalice --cov-report html $(TESTS)
	rm -rf /tmp/htmlcov && mv htmlcov /tmp/
	open /tmp/htmlcov/index.html

doccheck:
	##### DOC8 ######
	# Correct rst formatting for documentation
	#
	# TODO: Remove doc8
	##
	doc8 docs/source --ignore-path docs/source/topics/multifile.rst
	#
	#
	# Verify we have no broken external links
	# as well as no undefined internal references.
	$(MAKE) -C docs linkcheck
	# Verify we can build the docs.  The
	# treat warnings as errors flag is enabled
	# so any sphinx-build warnings will fail the build.
	$(MAKE) -C docs html

prcheck: check coverage doccheck typecheck

install-dev-deps:
	pip install -r requirements-dev.txt --upgrade --upgrade-strategy eager -e .
