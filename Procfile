web: cd myproject && gunicorn myproject.wsgi:application --bind 0.0.0.0:$PORT --timeout 120 --workers 4 --threads 2 --worker-class gthread --max-requests 1000 --max-requests-jitter 100
