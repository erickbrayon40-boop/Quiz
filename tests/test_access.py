import tempfile, unittest
from pathlib import Path
from unittest.mock import patch
import app

class AccessTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.previous=app.DATA
        app.DATA=Path(self.tmp.name)/'attempts.json'
        app._rate_buckets.clear()
        self.client=app.app.test_client()
    def tearDown(self):
        app.DATA=self.previous
        app._rate_buckets.clear()
        self.tmp.cleanup()
    def test_names_are_validated_without_claiming_identity(self):
        for name in ['Ana', '123 456', 'Ana Silva123', 'Ana <script>', 'Ana -- Silva', '   ']:
            self.assertEqual(self.client.post('/api/rooms',json={'name':name}).status_code,400, name)
        for name in ['Jo\u00e3o da Silva', "Ana D'\u00c1vila", 'Maria-Clara Souza', 'Jose\u0301 da Silva']:
            response=self.client.post('/api/rooms',json={'name':name})
            self.assertEqual(response.status_code,200,name)
        self.assertEqual(response.json['state']['name'], 'Jos\u00e9 da Silva')
    def test_creation_limit_expires_and_does_not_affect_other_addresses(self):
        with patch('app.time.monotonic',return_value=1000):
            for _ in range(12):
                self.assertEqual(self.client.post('/api/rooms',json={'name':'Ana Silva'}).status_code,200)
            blocked=self.client.post('/api/rooms',json={'name':'Ana Silva'})
            self.assertEqual(blocked.status_code,429)
            self.assertEqual(blocked.headers['Retry-After'],'60')
            self.assertEqual(self.client.post('/api/rooms',json={'name':'Ana Silva'},environ_base={'REMOTE_ADDR':'192.0.2.10'}).status_code,200)
        with patch('app.time.monotonic',return_value=1061):
            self.assertEqual(self.client.post('/api/rooms',json={'name':'Ana Silva'}).status_code,200)
    def test_join_limit_does_not_limit_members(self):
        leader=self.client.post('/api/rooms',json={'name':'Ana Silva'}).json
        code=leader['room']['code']
        for _ in range(60):
            self.assertEqual(self.client.post('/api/rooms/join',json={'name':'Maria Souza','code':code}).status_code,200)
        self.assertEqual(self.client.post('/api/rooms/join',json={'name':'Maria Souza','code':code}).status_code,429)
        self.assertEqual(self.client.post('/api/rooms/join',json={'name':'Maria Souza','code':code},environ_base={'REMOTE_ADDR':'192.0.2.11'}).status_code,200)

if __name__=='__main__': unittest.main()
