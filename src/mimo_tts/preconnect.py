"""One speculative TLS connection; no HTTP request, key or text before use."""
from __future__ import annotations

import http.client
import json
import threading
import time
import urllib.parse
import urllib.request

from . import client


class PreparedTransport:
    def __init__(self, ready=None):
        self.ready = threading.Event()
        self._lock = threading.Lock()
        self._connection = None
        self._active = None
        self._closed = False
        self._at = None
        self._url = urllib.parse.urlsplit(client.BASE_URL)
        # Respect urllib's configured HTTPS proxy route. Do not silently open a
        # direct socket when a proxy is required; keep the original transport.
        proxies = urllib.request.getproxies()
        if self._url.scheme != 'https' or (proxies.get('https') and not urllib.request.proxy_bypass(self._url.hostname)):
            self.ready.set()
            return
        self._thread = threading.Thread(target=self._prepare, args=(ready,), daemon=True)
        self._thread.start()

    def _prepare(self, notify):
        connection = None
        try:
            connection = http.client.HTTPSConnection(self._url.hostname, self._url.port, timeout=10)
            connection.connect()  # Default verified TLS; sends no API request.
            with self._lock:
                if not self._closed:
                    self._connection = connection
                    self._at = time.monotonic()
                    connection = None
            if notify and not self._closed:
                notify()
        except (OSError, http.client.HTTPException):
            pass  # Optional warming must not fail or delay a foreground request.
        finally:
            if connection:
                connection.close()
            self.ready.set()

    def open(self, payload):
        with self._lock:
            connection = self._connection
            self._connection = None
            self._active = connection
        # Never wait for a connection still warming. Long idle sockets may have
        # expired on the server; use the established urllib route in that case.
        if connection is None:
            return client._open(payload)
        if time.monotonic() - self._at > 30:
            connection.close()
            return client._open(payload)
        key, _ = client.credential()
        data = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        try:
            connection.sock.settimeout(120)
            connection.request('POST', self._url.path.rstrip('/') + '/chat/completions', body=data,
                headers={'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'})
            response = connection.getresponse()
        except (OSError, http.client.HTTPException):
            connection.close()
            # This fallback is only before any response/PCM has been delivered.
            return client._open(payload)
        if response.status >= 400:
            code = response.status
            retry = response.headers.get('Retry-After', '')
            response.close()
            connection.close()
            if code in (429, 500, 502, 503, 504):
                time.sleep(min(float(retry), 10) if retry.isdigit() else 1)
                return client._open(payload)
            raise client.MimoError(f'MiMo HTTP {code}; no response body or credential was logged.')
        return response

    def close(self):
        with self._lock:
            self._closed = True
            connections = (self._connection, self._active)
            self._connection = self._active = None
        for connection in connections:
            if connection:
                connection.close()
