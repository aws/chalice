# Eventually I'll add:
# py.test --cov chalice --cov-report term-missing --cov-fail-under 95 tests/
# which will fail if tests are under 95%
TESTS=tests/unit tests/functional

check:
	###### FLAKE8 #####
	# No unused imports, no undefined vars,
	flake8 --ignore=E731,W503 --exclude chalice/__init__.py --max-complexity 10 chalice/
	#
	#
	# Basic error checking in test code
	pyflakes tests/unit/ tests/functional/
	##### DOC8 ######
	# Correct rst formatting for documentation
	#
	##
	doc8 docs/source --ignore-path docs/source/topics/multifile.rst
	#
	#
	#
	# Proper docstring conventions according to pep257
	#
	#
	pydocstyle --add-ignore=D100,D101,D102,D103,D104,D105,D204 chalice/
	#
	#
	#
	###### PYLINT ERRORS ONLY ######
	#
	#
	#
	pylint --rcfile .pylintrc -E chalice

pylint:
	###### PYLINT ######
	# Python linter.  This will generally not have clean output.
	# So you'll need to manually verify this output.
	#
	#
	pylint --rcfile .pylintrc chalice

test:
	py.test -v $(TESTS)

typecheck:
	mypy --py2 --silent-import -p chalice --disallow-untyped-defs --strict-optional

coverage:
	py.test --cov chalice --cov-report term-missing $(TESTS)

coverage-unit:
	py.test --cov chalice --cov-report term-missing tests/unit

htmlcov:
	py.test --cov chalice --cov-report html $(TESTS)
	rm -rf /tmp/htmlcov && mv htmlcov /tmp/
	open /tmp/htmlcov/index.html

prcheck: check typecheck test
