.PHONY: test audit docker-build

test:
	python -m pytest

audit:
	python -m pip_audit -r requirements.txt

docker-build:
	docker build .
