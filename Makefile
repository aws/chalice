# Eventually I'll add:
# py.test --cov chalice --cov-report term-missing --cov-fail-under 95 tests/
# which will fail if tests are under 95%

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
	pep257 --add-ignore=D100,D101,D102,D103,D104,D105,D204 chalice/
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
	py.test -v tests/unit/ tests/functional/

coverage:
	py.test --cov chalice --cov-report term-missing tests/

htmlcov:
	py.test --cov chalice --cov-report html tests/
	rm -rf /tmp/htmlcov && mv htmlcov /tmp/
	open /tmp/htmlcov/index.html
