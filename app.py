import os, json, secrets, hashlib, time, tempfile
import math, re, threading, unicodedata
from collections import deque
from functools import wraps
from pathlib import Path
from contextlib import contextmanager
from filelock import FileLock
from flask import Flask, request, jsonify, send_from_directory
from werkzeug.exceptions import HTTPException

ROOT = Path(__file__).resolve().parent
QUESTIONS = json.loads((ROOT / 'questions.json').read_text(encoding='utf-8'))
DATA = Path(os.environ.get('QUIZ_DATA_FILE', str(ROOT / 'data' / 'attempts.json'))).resolve()
app = Flask(__name__, static_folder='public', static_url_path='')

# Limites por endereço diretamente conectado, sem confiar em cabeçalhos de proxy.
_rate_lock = threading.Lock()
_rate_buckets = {}

def limit_requests(limit, window=60):
    def decorate(view):
        @wraps(view)
        def limited(*args, **kwargs):
            timestamp = time.monotonic()
            key = (view.__name__, request.remote_addr or 'unknown')
            with _rate_lock:
                for old_key, events in list(_rate_buckets.items()):
                    while events and events[0] <= timestamp - window:
                        events.popleft()
                    if not events:
                        del _rate_buckets[old_key]
                events = _rate_buckets.setdefault(key, deque())
                if len(events) >= limit:
                    wait = max(1, math.ceil(window - (timestamp - events[0])))
                    return jsonify(error='Muitas tentativas em pouco tempo. Aguarde um pouco e tente novamente.'), 429, {'Retry-After': str(wait)}
                events.append(timestamp)
            return view(*args, **kwargs)
        return limited
    return decorate

def digest(token): return hashlib.sha256(token.encode()).hexdigest()
def now(): return int(time.time()*1000)
@contextmanager
def database(write=False):
    DATA.parent.mkdir(parents=True, exist_ok=True)
    with FileLock(str(DATA) + '.lock', timeout=15):
        if DATA.exists():
            with DATA.open(encoding='utf-8') as f: records=json.load(f)
            if not isinstance(records, list): raise ValueError('Arquivo de dados inválido')
        else: records=[]
        yield records
        if write:
            fd, tmp = tempfile.mkstemp(dir=DATA.parent, prefix='.quiz-', suffix='.tmp')
            try:
                with os.fdopen(fd, 'w', encoding='utf-8') as f:
                    json.dump(records, f, ensure_ascii=False, separators=(',', ':'))
                    f.flush(); os.fsync(f.fileno())
                os.replace(tmp, DATA)
            finally:
                if os.path.exists(tmp): os.unlink(tmp)

def public_question(i):
    q=QUESTIONS[i]
    return {'question':q['question'], 'options':q['options']}
def display_answers(row):
    # The explanation is presentation text, not an immutable part of an answer.
    # Refresh it from the corrected question bank for older saved attempts too.
    return [dict(answer, explanation=QUESTIONS[i]['explanation'])
            for i, answer in enumerate(row['answers'])]

def state(row):
    answers=display_answers(row)
    return {'id':row['id'], 'name':row['name'], 'started':row['started_ms'], 'completed':row['completed_ms'], 'answers':answers, 'score':sum(a['correct'] for a in answers)*10, 'question':public_question(len(answers)) if len(answers)<15 else None}
def clean_name(data):
    raw_name = data.get('name', '') if isinstance(data, dict) else ''
    if not isinstance(raw_name, str): return ''
    name = unicodedata.normalize('NFC', ' '.join(raw_name.split()))
    words = name.split(' ')
    if len(name) > 30 or len(words) < 2: return ''
    if not all(re.fullmatch(r"[^\W\d_]+(?:[-'’][^\W\d_]+)*", word, flags=re.UNICODE) for word in words): return ''
    return name

def make_attempt(name, started_ms, room_code=None, room_role=None):
    token = secrets.token_urlsafe(32)
    row = {'id': secrets.token_hex(16), 'token_hash': digest(token),
           'name': name, 'started_ms': started_ms, 'completed_ms': None, 'answers': []}
    if room_code:
        row.update(room_code=room_code, room_role=room_role)
    return token, row

def room_info(rows, row):
    code = row.get('room_code')
    if not code: return None
    members = [item for item in rows if item.get('room_code') == code]
    leader = next((item for item in members if item.get('room_role') == 'leader'), None)
    if not leader: return None
    return {'code': code, 'status': 'started' if leader['started_ms'] is not None else 'waiting',
            'role': row['room_role'],
            'members': [{'name': member['name'], 'role': member['room_role']} for member in members]}

def auth(rows):
    token=request.headers.get('Authorization','').removeprefix('Bearer ')
    if len(token)<30: return None
    hashed=digest(token)
    return next((r for r in rows if secrets.compare_digest(r['token_hash'],hashed)),None)
@app.errorhandler(Exception)
def error(e):
    if isinstance(e, HTTPException): return e
    app.logger.exception('Erro na solicitação')
    return jsonify(error='Não foi possível acessar o servidor ou salvar os dados. Tente novamente.'),503
@app.get('/')
def index(): return send_from_directory('public','index.html')
@app.get('/api/health')
def health():
    with database() as rows: pass
    return jsonify(ok=True)
@app.post('/api/rooms')
@limit_requests(12)
def create_room():
    name = clean_name(request.get_json(silent=True) or {})
    if not name or len(name) > 30:
        return jsonify(error='Digite seu nome e sobrenome com letras, em at\u00e9 30 caracteres.'), 400
    with database(True) as rows:
        codes = {row.get('room_code') for row in rows if row.get('room_code')}
        code = str(secrets.randbelow(100000000)).zfill(8)
        while code in codes:
            code = str(secrets.randbelow(100000000)).zfill(8)
        token, row = make_attempt(name, None, code, 'leader')
        rows.append(row)
        room = room_info(rows, row)
    return jsonify(token=token, room=room, state=state(row))

@app.post('/api/rooms/join')
@limit_requests(60)
def join_room():
    data = request.get_json(silent=True) or {}
    name = clean_name(data)
    code = data.get('code')
    if not name or len(name) > 30:
        return jsonify(error='Digite seu nome e sobrenome com letras, em at\u00e9 30 caracteres.'), 400
    if not isinstance(code, str) or len(code) != 8 or not code.isascii() or not code.isdigit():
        return jsonify(error='Digite o c\u00f3digo num\u00e9rico de 8 d\u00edgitos da sala.'), 400
    with database(True) as rows:
        leader = next((item for item in rows if item.get('room_code') == code and item.get('room_role') == 'leader'), None)
        if not leader:
            return jsonify(error='Sala n\u00e3o encontrada. Confira o c\u00f3digo.'), 404
        if leader['started_ms'] is not None:
            return jsonify(error='Esta sala j\u00e1 iniciou o quiz.'), 409
        token, row = make_attempt(name, None, code, 'student')
        rows.append(row)
        room = room_info(rows, row)
    return jsonify(token=token, room=room, state=state(row))

@app.get('/api/rooms/current')
def current_room():
    with database() as rows:
        row = auth(rows)
        if not row: return jsonify(error='Tentativa n\u00e3o encontrada.'), 404
        room = room_info(rows, row)
        if not room: return jsonify(error='Esta tentativa n\u00e3o pertence a uma sala.'), 404
        result = state(row)
    return jsonify(room=room, state=result)

@app.post('/api/rooms/start')
def start_room():
    with database(True) as rows:
        row = auth(rows)
        if not row: return jsonify(error='Tentativa n\u00e3o encontrada.'), 404
        room = room_info(rows, row)
        if not room: return jsonify(error='Esta tentativa n\u00e3o pertence a uma sala.'), 404
        if row['room_role'] != 'leader':
            return jsonify(error='Somente o l\u00edder pode iniciar a sala.'), 403
        if row['started_ms'] is None:
            started = now()
            for item in rows:
                if item.get('room_code') == row['room_code']:
                    item['started_ms'] = started
        room, result = room_info(rows, row), state(row)
    return jsonify(room=room, state=result)

@app.get('/api/state')
def get_state():
    with database() as rows: row=auth(rows)
    if not row: return jsonify(error='Tentativa não encontrada.'),404
    return jsonify(state(row))
@app.post('/api/answer')
def answer():
    data=request.get_json(silent=True) or {}; idx=data.get('index'); choice=data.get('choice')
    if type(idx)!=int or type(choice)!=int or choice not in range(4): return jsonify(error='Resposta inválida.'),400
    with database(True) as rows:
        row=auth(rows)
        if not row: return jsonify(error='Tentativa não encontrada.'),404
        answers=row['answers']
        if row['started_ms'] is None: return jsonify(error='Aguarde o l\u00edder iniciar a sala.'), 409
        if row['completed_ms'] or idx!=len(answers) or idx>=15: return jsonify(error='Esta pergunta já foi respondida. Atualize a tentativa.'),409
        q=QUESTIONS[idx]; answers.append({'choice':choice,'correct':choice==q['correct'],'correctChoice':q['correct'],'explanation':q['explanation']})
        result=state(row)
    return jsonify(result)
@app.post('/api/finish')
def finish():
    with database(True) as rows:
        row=auth(rows)
        if not row: return jsonify(error='Tentativa não encontrada.'),404
        if len(row['answers'])!=15: return jsonify(error='Responda a todas as perguntas primeiro.'),400
        if not row['completed_ms']: row['completed_ms']=now()
        result=state(row)
    return jsonify(result)
@app.get('/api/review')
def review():
    with database() as rows:
        row=auth(rows)
        if not row or not row['completed_ms']: return jsonify(error='Finalize o quiz para revisar.'),403
        result=[dict(public_question(i),**a) for i,a in enumerate(display_answers(row))]
    return jsonify(result)
@app.get('/api/ranking')
def ranking():
    with database() as rows:
        finished=[r for r in rows if r['completed_ms'] is not None and not r.get('ranking_hidden', False)]
        finished.sort(key=lambda r:(-sum(a['correct'] for a in r['answers']),r['completed_ms']-r['started_ms'],r['completed_ms'],r['id']))
        result=[{'id':r['id'],'name':r['name'],'correct':sum(a['correct'] for a in r['answers']),'score':sum(a['correct'] for a in r['answers'])*10,'duration':r['completed_ms']-r['started_ms'],'completed':r['completed_ms'],'position':i+1} for i,r in enumerate(finished)]
    return jsonify(result)
if __name__=='__main__':
    from server import main
    main(app)
