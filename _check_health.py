import urllib.request, sys
try:
    urllib.request.urlopen("http://localhost:8000/health", timeout=1)
    sys.exit(0)
except Exception:
    sys.exit(1)
