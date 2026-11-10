import base64
import http.client
import io
import json
import threading
import unittest
from unittest.mock import Mock, patch

from mimo_tts import client
from mimo_tts.preconnect import PreparedTransport


class Response(io.BytesIO):
    def __init__(self, body=b'', status=200):
        super().__init__(body)
        self.status = status
        self.headers = {}


class PreconnectTests(unittest.TestCase):
    def transport(self, connection, **kwargs):
        with patch('mimo_tts.preconnect.urllib.request.getproxies', return_value={}), \
             patch('mimo_tts.preconnect.http.client.HTTPSConnection', return_value=connection):
            result = PreparedTransport(**kwargs)
            self.assertTrue(result.ready.wait(2), 'speculative connection completes')
        self.addCleanup(result.close)
        return result

    def test_warms_only_tls_and_preserves_stream_samples(self):
        pcm = b'\x01\x02' * 200
        event = {'choices': [{'delta': {'audio': {'data': base64.b64encode(pcm).decode()}}, 'finish_reason': 'stop'}]}
        response = Response(('data: ' + json.dumps(event) + '\n\ndata: [DONE]\n\n').encode())
        connection = Mock()
        connection.getresponse.return_value = response
        with patch.object(client, 'credential', return_value=('offline-test-only', 'fixture')) as credentials, \
             patch.object(client, '_open') as cold:
            transport = self.transport(connection)
            connection.connect.assert_called_once()
            connection.request.assert_not_called()
            credentials.assert_not_called()
            chunks = []
            result, _ = client._pcm({'stream': True}, chunks.append, opener=transport.open)
            self.assertEqual(result, pcm)
            self.assertEqual(b''.join(chunks), pcm)
            cold.assert_not_called()
            arguments = connection.request.call_args
            self.assertEqual(arguments.args[:2], ('POST', '/v1/chat/completions'))
            self.assertEqual(json.loads(arguments.kwargs['body']), {'stream': True})
            connection.sock.settimeout.assert_called_once_with(120)

    def test_pending_warm_connection_never_blocks_real_request(self):
        gate = threading.Event()
        connection = Mock()
        connection.connect.side_effect = lambda: gate.wait(2)
        with patch('mimo_tts.preconnect.urllib.request.getproxies', return_value={}), \
             patch('mimo_tts.preconnect.http.client.HTTPSConnection', return_value=connection), \
             patch.object(client, '_open', return_value='cold-response') as cold:
            transport = PreparedTransport()
            try:
                self.assertFalse(transport.ready.is_set())
                self.assertEqual(transport.open({'stream': True}), 'cold-response')
                cold.assert_called_once()
            finally:
                transport.close()
                gate.set()
                self.assertTrue(transport.ready.wait(2))

    def test_proxy_is_not_bypassed(self):
        with patch('mimo_tts.preconnect.urllib.request.getproxies', return_value={'https': 'http://proxy.example:8080'}), \
             patch('mimo_tts.preconnect.urllib.request.proxy_bypass', return_value=False), \
             patch('mimo_tts.preconnect.http.client.HTTPSConnection') as connection, \
             patch.object(client, '_open', return_value='proxy-response') as cold:
            transport = PreparedTransport()
            self.assertTrue(transport.ready.is_set())
            self.assertEqual(transport.open({}), 'proxy-response')
            connection.assert_not_called()
            cold.assert_called_once()
            transport.close()

    def test_expired_or_failed_socket_falls_back_before_audio(self):
        for expire in (True, False):
            with self.subTest(expire=expire):
                connection = Mock()
                if not expire:
                    connection.getresponse.side_effect = http.client.RemoteDisconnected('fixture')
                transport = self.transport(connection)
                if expire:
                    transport._at -= 31
                with patch.object(client, 'credential', return_value=('offline-test-only', 'fixture')), \
                     patch.object(client, '_open', return_value='fresh-response') as cold:
                    self.assertEqual(transport.open({}), 'fresh-response')
                    cold.assert_called_once()
                    connection.close.assert_called()

    def test_client_errors_never_retry_or_log_body(self):
        connection = Mock()
        connection.getresponse.return_value = Response(b'private fixture body', status=401)
        transport = self.transport(connection)
        with patch.object(client, 'credential', return_value=('offline-test-only', 'fixture')), \
             patch.object(client, '_open') as cold:
            with self.assertRaises(client.MimoError) as error:
                transport.open({})
            self.assertNotIn('private fixture body', str(error.exception))
            self.assertNotIn('offline-test-only', str(error.exception))
            cold.assert_not_called()

    def test_partial_response_failure_never_restarts_synthesis(self):
        pcm = base64.b64encode(b'\0\1' * 50).decode()
        event = {'choices': [{'delta': {'audio': {'data': pcm}}, 'finish_reason': 'length'}]}
        connection = Mock()
        connection.getresponse.return_value = Response(('data: ' + json.dumps(event) + '\n\ndata: [DONE]\n\n').encode())
        transport = self.transport(connection)
        with patch.object(client, 'credential', return_value=('offline-test-only', 'fixture')), \
             patch.object(client, '_open') as cold:
            chunks = []
            with self.assertRaises(client.MimoError):
                client._pcm({'stream': True}, chunks.append, opener=transport.open)
            self.assertTrue(chunks)
            self.assertEqual(connection.request.call_count, 1)
            cold.assert_not_called()


if __name__ == '__main__':
    unittest.main()
