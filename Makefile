PYTHON ?= python3
VENV ?= venv
PIP := $(VENV)/bin/pip
PY := $(VENV)/bin/python
REQS := requirements.txt
INSTALL_STAMP := $(VENV)/.installed

.PHONY: help venv install test run-local demo-local send-ecowitt print-latest clean

help:
	@echo "Targets:"
	@echo "  make venv         Create virtualenv in $(VENV)/"
	@echo "  make install      Install Python deps"
	@echo "  make test         Run pytest"
	@echo "  make run-local    Run server locally (DATA_STORAGE_PATH=./.local-data)"
	@echo "  make send-ecowitt Send one sample Ecowitt payload to localhost"
	@echo "  make print-latest Print latest telemetry summary from local data dir"
	@echo "  make demo-local   Run an end-to-end local demo"

venv:
	@test -x "$(PY)" || $(PYTHON) -m venv "$(VENV)"

$(INSTALL_STAMP): $(REQS) | venv
	"$(PIP)" install -r "$(REQS)"
	@touch "$(INSTALL_STAMP)"

install: $(INSTALL_STAMP)

test: install
	"$(PY)" -m pytest -q

run-local: install
	@mkdir -p .local-data
	DATA_STORAGE_PATH=.local-data "$(PY)" src/server.py

send-ecowitt: install
	"$(PY)" scripts/dev_send_ecowitt.py http://localhost:8080/ecowitt

print-latest: install
	DATA_STORAGE_PATH=.local-data "$(PY)" scripts/dev_print_latest.py

demo-local: install
	@echo "1) Start server in another terminal: make run-local"
	@echo "2) Then run: make send-ecowitt && make print-latest"

clean:
	rm -rf "$(VENV)" .local-data
