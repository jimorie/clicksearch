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

upload:
	${VENV_DIR}/bin/twine upload dist/*

release: clean version dist upload

format:
	black ${SRC}

lint:
	ruff ${SRC}
	black --check ${SRC}

venv:
	python3 -m venv ${VENV_DIR}
	${VENV_DIR}/bin/pip install --upgrade .[dev]
