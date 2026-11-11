import concurrent.futures, tempfile, unittest
from pathlib import Path
import app

class QuizTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); app.DATA=Path(self.tmp.name)/'attempts.json'; app.app.testing=True; app._rate_buckets.clear()
        self.client=app.app.test_client()
    def tearDown(self): self.tmp.cleanup()
    def start(self,name='Aluno Exemplo'):
        response=self.client.post('/api/rooms',json={'name':name})
        self.assertEqual(response.status_code,200)
        header = {'Authorization':'Bearer '+response.json['token']}
        self.assertEqual(self.client.post('/api/rooms/start',headers=header).status_code,200)
        return header
    def test_complete_flow_and_persistence(self):
        self.assertEqual(self.client.post('/api/rooms',json={'name':'   '}).status_code,400)
        h=self.start('  Ana   Silva ')
        self.assertEqual(self.client.get('/api/ranking').json,[])
        self.assertEqual(self.client.post('/api/finish',headers=h).status_code,400)
        for i,q in enumerate(app.QUESTIONS):
            response=self.client.post('/api/answer',headers=h,json={'index':i,'choice':q['correct']})
            self.assertEqual(response.status_code,200)
            self.assertEqual(response.json['score'],(i+1)*10)
        self.assertEqual(self.client.post('/api/answer',headers=h,json={'index':14,'choice':2}).status_code,409)
        done=self.client.post('/api/finish',headers=h).json
        self.assertEqual(done['score'],150)
        self.assertEqual(self.client.post('/api/finish',headers=h).json['completed'],done['completed'])
        self.assertEqual(len(self.client.get('/api/review',headers=h).json),15)
        with app.app.test_client() as other:
            self.assertEqual(other.get('/api/ranking').json[0]['name'],'Ana Silva')
            self.assertEqual(other.get('/api/state',headers=h).json['score'],150)
            self.assertEqual(other.get('/api/review').status_code,403)
        self.assertTrue(app.DATA.exists())
    def test_names_are_saved_as_utf8_at_start_and_same_names_are_independent(self):
        name = "  Jo\u00e3o   da  Silva "
        first = self.start(name)
        second = self.start(name)
        with app.DATA.open(encoding="utf-8") as f:
            import json
            rows = json.load(f)
        self.assertEqual([row["name"] for row in rows], ["Jo\u00e3o da Silva"] * 2)
        self.assertNotEqual(rows[0]["id"], rows[1]["id"])
        self.assertEqual(self.client.get('/api/state', headers=first).json['name'], "Jo\u00e3o da Silva")
        self.assertEqual(self.client.get('/api/state', headers=second).json['name'], "Jo\u00e3o da Silva")
        self.assertEqual(self.client.get('/api/ranking').json, [])
        self.assertEqual(self.client.post('/api/rooms', json={'name': None}).status_code, 400)

    def test_texts_and_old_saved_explanations_are_corrected(self):
        self.assertEqual(app.QUESTIONS[0]['explanation'], 'O adv\u00e9rbio modifica verbos, adjetivos ou outros adv\u00e9rbios.')
        self.assertEqual(app.QUESTIONS[6]['explanation'], '\u201cSim\u201d expressa afirma\u00e7\u00e3o.')
        self.assertTrue(all('?' not in q['explanation'] for q in app.QUESTIONS))
        h = self.start()
        self.client.post('/api/answer', headers=h, json={'index': 0, 'choice': 1})
        with app.database(True) as rows:
            rows[0]['answers'][0]['explanation'] = 'O adv?rbio'
        self.assertEqual(self.client.get('/api/state', headers=h).json['answers'][0]['explanation'], app.QUESTIONS[0]['explanation'])
        for i, q in enumerate(app.QUESTIONS[1:], 1):
            self.client.post('/api/answer', headers=h, json={'index': i, 'choice': q['correct']})
        self.client.post('/api/finish', headers=h)
        self.assertEqual(self.client.get('/api/review', headers=h).json[0]['explanation'], app.QUESTIONS[0]['explanation'])

    def test_concurrent_duplicate_answer(self):
        h=self.start()
        def send(_):
            with app.app.test_client() as client: return client.post('/api/answer',headers=h,json={'index':0,'choice':1}).status_code
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool: results=list(pool.map(send,range(8)))
        self.assertEqual(results.count(200),1)
        self.assertEqual(results.count(409),7)
        self.assertEqual(self.client.get('/api/state',headers=h).json['score'],10)
    def test_rooms_lobby_permissions_and_independent_answers(self):
        created = self.client.post('/api/rooms', json={'name': 'L\u00edder Silva'})
        self.assertEqual(created.status_code, 200)
        leader = created.json
        code = leader['room']['code']
        self.assertEqual(len(code), 8)
        self.assertTrue(code.isdigit())
        lh = {'Authorization': 'Bearer ' + leader['token']}
        self.assertEqual(leader['room']['role'], 'leader')
        self.assertIsNone(leader['state']['started'])
        self.assertEqual(self.client.post('/api/answer', headers=lh, json={'index': 0, 'choice': 1}).status_code, 409)
        joined = self.client.post('/api/rooms/join', json={'name': 'Jo\u00e3o Silva', 'code': code})
        self.assertEqual(joined.status_code, 200)
        student = joined.json
        sh = {'Authorization': 'Bearer ' + student['token']}
        self.assertEqual(student['room']['role'], 'student')
        self.assertEqual([p['name'] for p in student['room']['members']], ['L\u00edder Silva', 'Jo\u00e3o Silva'])
        self.assertEqual(self.client.post('/api/rooms/start', headers=sh).status_code, 403)
        self.assertEqual(self.client.get('/api/ranking').json, [])
        started = self.client.post('/api/rooms/start', headers=lh)
        self.assertEqual(started.status_code, 200)
        self.assertEqual(started.json['room']['status'], 'started')
        student_state = self.client.get('/api/rooms/current', headers=sh).json
        self.assertEqual(student_state['state']['started'], started.json['state']['started'])
        self.assertEqual(student_state['room']['members'][0]['role'], 'leader')
        self.assertEqual(self.client.post('/api/rooms/start', headers=lh).json['state']['started'], started.json['state']['started'])
        self.assertEqual(self.client.post('/api/rooms/join', json={'name': 'Outra Silva', 'code': code}).status_code, 409)
        self.assertEqual(self.client.post('/api/answer', headers=lh, json={'index': 0, 'choice': 1}).json['score'], 10)
        self.assertEqual(self.client.get('/api/state', headers=sh).json['score'], 0)
        self.assertEqual(self.client.get('/api/rooms/current').status_code, 404)

    def test_multiplayer_complete_appears_in_ranking(self):
        leader = self.client.post('/api/rooms', json={'name': 'Ana Silva'}).json
        student = self.client.post('/api/rooms/join', json={'name': 'Bia Silva', 'code': leader['room']['code']}).json
        lh = {'Authorization': 'Bearer ' + leader['token']}
        sh = {'Authorization': 'Bearer ' + student['token']}
        self.client.post('/api/rooms/start', headers=lh)
        for i, q in enumerate(app.QUESTIONS):
            for header in [lh, sh]:
                response = self.client.post('/api/answer', headers=header, json={'index': i, 'choice': q['correct']})
                self.assertEqual(response.status_code, 200)
        self.client.post('/api/finish', headers=lh)
        self.client.post('/api/finish', headers=sh)
        self.assertEqual({r['name'] for r in self.client.get('/api/ranking').json}, {'Ana Silva', 'Bia Silva'})
        self.assertIsNotNone(self.client.get('/api/rooms/current', headers=sh).json['state']['completed'])

    def test_solo_creation_endpoint_is_removed(self):
        self.assertEqual(self.client.post('/api/start', json={'name': 'Aluno'}).status_code, 405)

    def test_missing_asset_remains_http_404(self):
        self.assertEqual(self.client.get('/nao-existe.png').status_code, 404)

    def test_room_can_start_alone_and_reject_bad_codes(self):
        leader = self.client.post('/api/rooms', json={'name': 'Ana Silva'}).json
        header = {'Authorization': 'Bearer ' + leader['token']}
        self.assertEqual(self.client.post('/api/rooms/join', json={'name': 'Teste Silva', 'code': 123}).status_code, 400)
        self.assertEqual(self.client.post('/api/rooms/join', json={'name': 'Teste Silva', 'code': '1234567A'}).status_code, 400)
        self.assertEqual(self.client.post('/api/rooms/start', headers=header).json['room']['status'], 'started')
        self.assertEqual(len(self.client.get('/api/rooms/current', headers=header).json['room']['members']), 1)

    def test_simultaneous_room_joins_are_saved(self):
        leader = self.client.post('/api/rooms', json={'name': 'Ana Silva'}).json
        code = leader['room']['code']
        def join(i):
            with app.app.test_client() as client:
                return client.post('/api/rooms/join', json={'name': 'Aluno Exemplo', 'code': code}).status_code
        with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
            statuses = list(pool.map(join, range(20)))
        self.assertEqual(statuses, [200] * 20)
        header = {'Authorization': 'Bearer ' + leader['token']}
        self.assertEqual(len(self.client.get('/api/rooms/current', headers=header).json['room']['members']), 21)

    def test_hidden_results_are_not_in_ranking_but_remain_recoverable(self):
        completed = self.start('Ana Silva')
        unfinished = self.start('Bia Silva')
        for i, q in enumerate(app.QUESTIONS):
            self.client.post('/api/answer', headers=completed, json={'index': i, 'choice': q['correct']})
        self.client.post('/api/finish', headers=completed)
        self.assertEqual(len(self.client.get('/api/ranking').json), 1)
        with app.database(True) as rows:
            for row in rows:
                if row['completed_ms'] is not None:
                    row['ranking_hidden'] = True
        self.assertEqual(self.client.get('/api/ranking').json, [])
        self.assertEqual(self.client.get('/api/state', headers=completed).json['score'], 150)
        self.assertEqual(len(self.client.get('/api/review', headers=completed).json), 15)
        self.assertEqual(self.client.get('/api/state', headers=unfinished).json['name'], 'Bia Silva')
        for i, q in enumerate(app.QUESTIONS):
            self.client.post('/api/answer', headers=unfinished, json={'index': i, 'choice': q['correct']})
        self.client.post('/api/finish', headers=unfinished)
        self.assertEqual([r['name'] for r in self.client.get('/api/ranking').json], ['Bia Silva'])

    def test_ranking_orders_by_score(self):
        for name,choice in [('Ana Silva',0),('Bia Silva',1)]:
            h=self.start(name)
            for i,q in enumerate(app.QUESTIONS): self.client.post('/api/answer',headers=h,json={'index':i,'choice':q['correct'] if choice else (q['correct']+1)%4})
            self.client.post('/api/finish',headers=h)
        self.assertEqual([r['name'] for r in self.client.get('/api/ranking').json],['Bia Silva','Ana Silva'])

if __name__=='__main__': unittest.main()
