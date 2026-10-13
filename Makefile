# Note: needs a python3.13 with venv/ensurepip support (e.g. apt-get
# install python3.13-venv). As in the main psxhacks repo's Makefile, a
# self-built Python under ~/pkg/python/latest is preferred when present.
export PATH := $(HOME)/pkg/python/latest/bin:$(PATH)

# Target Python 3.13, matching the CI build (.github/workflows/build.yml).
PYTHON ?= python3.13

osname=$(shell uname -s)-$(shell uname -r)

VENVDIR = $(HOME)/.venv-test-psxhacks-updater/$(osname)-$(PYTHON)

test: venv
	$(info * TEST: Running unit tests)
	. $(VENVDIR)/bin/activate; python3 -m unittest discover -v tests

venv: $(VENVDIR)/bin/activate

# Re-run pip whenever requirements.txt changes.
$(VENVDIR)/bin/activate: requirements.txt
	$(info * TEST: Setting up a Python3 venv in $(VENVDIR))
	test -d $(VENVDIR) || $(PYTHON) -m venv $(VENVDIR) || { rm -rf $(VENVDIR); exit 1; }
	. $(VENVDIR)/bin/activate; pip install -r requirements.txt
	touch $(VENVDIR)/bin/activate

clean:
	$(info * TEST: Removing venv)
	rm -rf $(HOME)/.venv-test-psxhacks-updater

.PHONY: test venv clean
