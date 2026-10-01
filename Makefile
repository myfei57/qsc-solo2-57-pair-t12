test:
	PYTHONPATH=. python -m pytest -q

run:
	PYTHONPATH=. python -m heatnet --config config/heatnet.json serve --host 127.0.0.1 --port 8080

demo:
	PYTHONPATH=. python -m heatnet --config config/heatnet.json demo --fast

deadcode:
	PYTHONPATH=. python tools/deadcode.py heatnet
