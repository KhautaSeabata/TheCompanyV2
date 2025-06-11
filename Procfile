# Procfile (create this file in your root directory)
web: gunicorn app:app --bind 0.0.0.0:$PORT --workers 1 --timeout 120

# render.yaml (optional - for easier deployment)
services:
  - type: web
    name: volatility-ticks-app
    env: python
    buildCommand: pip install -r requirements.txt
    startCommand: gunicorn app:app --bind 0.0.0.0:$PORT --workers 1 --timeout 120
    envVars:
      - key: PYTHON_VERSION
        value: 3.9.16
