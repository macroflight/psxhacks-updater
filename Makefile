# Note: needs e.g apt-get install python3-venv

osname=$(shell uname -s)-$(shell uname -r)

VENVDIR = $${HOME}/.venv-test-psxhacks-updater/$(osname)

test: venv
	$(info * TEST: Running unit tests)
	. $(VENVDIR)/bin/activate; python3 -m unittest discover -v tests

venv: $(VENVDIR)/bin/activate

# Re-run pip whenever requirements.txt changes.
$(VENVDIR)/bin/activate: requirements.txt
	$(info * TEST: Setting up a Python3 venv in $(VENVDIR))
	test -d $(VENVDIR) || python3 -m venv $(VENVDIR)
	. $(VENVDIR)/bin/activate; pip install -r requirements.txt
	touch $(VENVDIR)/bin/activate

clean:
	$(info * TEST: Removing venv)
	rm -rf $(VENVDIR)

.PHONY: test venv clean
