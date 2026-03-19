"""
Lightweight dashboard server for the underdog bot P&L chart.
Serves dashboard.html + data/ directory on port 8888.

Usage:
    python -m trade_underdog.dashboard_server
    Then open http://localhost:8888
"""

import os
import http.server
import functools

PORT = 8888
DIR = os.path.dirname(os.path.abspath(__file__))


def main():
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=DIR)
    with http.server.HTTPServer(("", PORT), handler) as httpd:
        print(f"\n  Underdog Dashboard: http://localhost:{PORT}")
        print(f"  Serving from: {DIR}")
        print(f"  Press Ctrl+C to stop\n")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n  Dashboard stopped.")


if __name__ == "__main__":
    main()
