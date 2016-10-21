# Eventually I'll add:
# py.test --cov chalice --cov-report term-missing --cov-fail-under 95 tests/
# which will fail if tests are under 95%
TESTS=tests/unit tests/functional

check:
	###### FLAKE8 #####
	# No unused imports, no undefined vars,
	# I'd eventually like to lower this down to < 10.
	flake8 --ignore=E731,W503 --exclude chalice/__init__.py --max-complexity 15 chalice/
	#
	#
	# Basic error checking in test code
	pyflakes tests/unit/ tests/functional/
	##### DOC8 ######
	# Correct rst formatting for docstrings
	#
	##
	doc8 docs/source
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
	mypy --py2 --silent-import -p chalice --strict-optional
	# Set of modules that will require type hints for all methods.
	# The eventual goal is to just --disallow-untyped-defs for
	# the entire chalice package, but for now as modules have complete
	# type definitions, the list below should be updated.
	mypy --py2 --silent-import -p chalice.deployer --disallow-untyped-defs --strict-optional
	mypy --py2 --silent-import -p chalice.policy --disallow-untyped-defs --strict-optional
	mypy --py2 --silent-import -p chalice.prompts --disallow-untyped-defs --strict-optional
	mypy --py2 --silent-import -p chalice.awsclient --disallow-untyped-defs --strict-optional
	mypy --py2 --silent-import -p chalice.prompts --disallow-untyped-defs --strict-optional
	mypy --py2 --silent-import -p chalice.logs --disallow-untyped-defs --strict-optional
	mypy --py2 --silent-import -p chalice.compat --disallow-untyped-defs --strict-optional

coverage:
	py.test --cov chalice --cov-report term-missing $(TESTS)

coverage-unit:
	py.test --cov chalice --cov-report term-missing tests/unit

htmlcov:
	py.test --cov chalice --cov-report html $(TESTS)
	rm -rf /tmp/htmlcov && mv htmlcov /tmp/
	open /tmp/htmlcov/index.html

prcheck: check typecheck test
