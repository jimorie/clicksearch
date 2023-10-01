VENV_DIR = venv
VERSION := $(shell python3 -c 'from importlib.metadata import version; print(version("clicksearch"))')
SRC = clicksearch.py

dist:
	${VENV_DIR}/bin/pip wheel --no-deps --wheel-dir dist .

version:
	git add -u
	git commit -m'Version ${VERSION}'
	git tag v${VERSION}
	git push --tags origin master

clean:
	rm -rf build
	rm -rf dist
	rm -rf clicksearch.egg-info
	rm -rf __pycache__
	rm README.md.test

upload:
	${VENV_DIR}/bin/twine upload dist/*

release: clean README.md version dist upload

format:
	black ${SRC}

lint:
	ruff ${SRC}
	black --check ${SRC}
	mypy --check-untyped-defs ${SRC}

test:
	@# Automagically import everything
	@echo '>>> from clicksearch import *' > README.md.test
	@# Turn off standalone_mode so launching the command doesn't sys.exit
	@echo '>>> ModelBase._standalone_mode = False' >> README.md.test
	@# Copy the README.md content
	@echo '' >> README.md.test
	@cat README.md >> README.md.test
	@# Delete all lines between "[DOCTEST_BREAK]::" and "[DOCTEST_CONTINUE]::"
	@sed -i '' '/^\[DOCTEST_BREAK\]::$$/,/^\[DOCTEST_CONTINUE\]::$$/ d' README.md.test
	@# Replace empty lines in console code blocks with "<BLANKLINE>" (to match CLI output)
	@sed -i '' '/^```pycon$$/,/^```$$/ s/^\s*$$/<BLANKLINE>/g' README.md.test
	@# Remove empty lines in python code blocks (we don't expect output there)
	@sed -i '' '/^```python$$/,/^```$$/{/^$$/d;}' README.md.test
	@# Prepend lines in python code blocks with ">>>" or "..." (if indented)
	@sed -ri '' '/^```python$$/,/^```$$/{s/^([^` ])/>>> \1/g;s/^([ ])/\.\.\. \1/g;}' README.md.test
	@# Add an empty line at the end of code blocks for mark an end for doctest
	@sed -i '' 's/^```$$/\n```/g' README.md.test
	@# Run doctest!
	${VENV_DIR}/bin/python -m doctest -o NORMALIZE_WHITESPACE -o ELLIPSIS ${SRC} README.md.test

venv:
	python3 -m venv ${VENV_DIR}
	${VENV_DIR}/bin/pip install --upgrade .[dev]
