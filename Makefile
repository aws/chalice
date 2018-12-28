# Eventually I'll add:
# py.test --cov chalice --cov-report term-missing --cov-fail-under 95 tests/
# which will fail if tests are under 95%
TESTS=tests/unit tests/functional

check:
	###### FLAKE8 #####
	# No unused imports, no undefined vars,
	flake8 --ignore=E731,W503,W504 --exclude chalice/__init__.py,chalice/compat.py --max-complexity 10 chalice/
	flake8 --ignore=E731,W503,W504,F401 --max-complexity 10 chalice/compat.py
	flake8 tests/unit/ tests/functional/ tests/integration
	#
	# Proper docstring conventions according to pep257
	#
	#
	pydocstyle --add-ignore=D100,D101,D102,D103,D104,D105,D204,D301 chalice/

pylint:
	###### PYLINT ######
	pylint --rcfile .pylintrc chalice
	# Run our custom linter on test code.
	pylint --load-plugins tests.linter --disable=I,E,W,R,C,F --enable C9999,C9998 tests/

test:
	py.test -v $(TESTS)

typecheck:
	mypy --py2 --ignore-missing-imports --follow-imports=skip -p chalice --disallow-untyped-defs --strict-optional --warn-no-return

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
	doc8 docs/source --ignore-path docs/source/topics/multifile.rst --ignore-path docs/source/topics/websockets.rst
	#
	#
	# Verify we have no broken external links
	# as well as no undefined internal references.
	$(MAKE) -C docs linkcheck
	# Verify we can build the docs.  The
	# treat warnings as errors flag is enabled
	# so any sphinx-build warnings will fail the build.
	$(MAKE) -C docs html

prcheck-py2: check pylint coverage doccheck


prcheck: prcheck-py2 typecheck
