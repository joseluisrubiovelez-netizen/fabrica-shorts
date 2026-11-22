# En Windows sin make, usa:  .\make.ps1 setup | run | test | generar | estado
PY ?= .venv/bin/python
ifeq ($(OS),Windows_NT)
PY = .venv/Scripts/python.exe
endif

.PHONY: setup run test generar dry-run estado informe verificar

setup:
	python -m venv .venv
	$(PY) -m pip install --upgrade pip
	$(PY) -m pip install -r requirements.txt
	$(PY) -m piper.download_voices --download-dir models es_ES-davefx-medium
	@test -f .env || cp .env.example .env
	$(PY) -m fabrica verificar

run:
	$(PY) -m fabrica ciclo

dry-run:
	$(PY) -m fabrica --modo dry-run generar --n 1

generar:
	$(PY) -m fabrica generar --n 1

test:
	$(PY) -m pytest -q tests

estado:
	$(PY) -m fabrica estado

informe:
	$(PY) -m fabrica informe

verificar:
	$(PY) -m fabrica verificar
