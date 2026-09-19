"""Local demo API. Fixture evidence is never eligible for a real release approval."""
from contextlib import contextmanager
import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

DB = Path(os.getenv('DATABASE_PATH', 'data/cognition.db'))
app = FastAPI(title='Cognition Evidence API', version='0.1.0')
SHA = '8f3a21c7d9e04b6a1f28563c9a0d7e4b2c681f95'
CHECKS = [
    dict(id='services', title='Superset services', detail='Web server, worker, Redis and Postgres', status='passed', duration='42s', kind='logs', content='[DEMO FIXTURE]\nweb: healthy\nworker: ready\nredis: PONG\npostgres: accepting connections'),
    dict(id='database', title='Database integrity', detail='Migrations, metadata and read/write checks', status='passed', duration='18s', kind='logs', content='[DEMO FIXTURE]\nMigration at head\nDataset metadata: consistent\nTransaction rollback: successful'),
    dict(id='browser', title='Critical browser journeys', detail='Sign in → query → chart → dashboard', status='passed', duration='3m 12s', kind='screenshot', content='Illustrative chart preview only. No Superset browser was executed. Real captures must include candidate SHA, validator session and timestamp.'),
    dict(id='tests', title='Regression suite', detail='20 scenario checks across changed modules', status='passed', duration='2m 46s', kind='tests', content='[DEMO FIXTURE]\n20 passed, 0 failed\nChart filter: 8\nDataset metadata: 6\nSQL Lab: 6'),
    dict(id='review', title='Independent evidence review', detail='Human review of the integrated revision', status='pending', duration='—', kind='review', content='Inspect the evidence before recording a demo decision. Demo decisions never merge or approve a real release.'),
]
WORKFLOWS = [
    dict(id='WF-041', issue=142, title='Preserve dashboard filter state', area='Dashboard', status='integrated', run='DV-081', minutes=18),
    dict(id='WF-042', issue=143, title='Handle empty query results', area='SQL Lab', status='integrated', run='DV-082', minutes=24),
    dict(id='WF-043', issue=144, title='Repair dataset metadata refresh', area='Datasets', status='integrated', run='DV-083', minutes=16),
    dict(id='WF-044', issue=145, title='Align chart tooltip formatting', area='Charts', status='integrated', run='DV-084', minutes=21),
    dict(id='WF-045', issue=146, title='Update dependency compatibility', area='Dependencies', status='integrated', run='DV-085', minutes=31),
]

@contextmanager
def connect():
    DB.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    con.execute('CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY, delivery TEXT UNIQUE, kind TEXT, payload TEXT, created TEXT)')
    con.commit()
    try:
        with con:
            yield con
    finally:
        con.close()

class Decision(BaseModel):
    sha: str
    decision: str = Field(pattern='^(approved|changes_requested)$')
    note: str = Field(min_length=3, max_length=2000)

class Event(BaseModel):
    delivery_id: str = Field(min_length=1, max_length=100)
    title: str = Field(min_length=3, max_length=200)

@app.get('/api/health')
def health():
    with connect() as con:
        con.execute('SELECT 1')
    return {'status': 'ok', 'mode': 'demo'}

@app.get('/api/dashboard')
def dashboard():
    with connect() as con:
        events = [dict(r) for r in con.execute('SELECT * FROM events ORDER BY id DESC LIMIT 50')]
    for event in events:
        event['payload'] = json.loads(event['payload'])
    latest = next((e['payload']['decision'] for e in events if e['kind'] == 'demo_decision' and e['payload']['sha'] == SHA), None)
    return dict(mode='demo', repository='apache/superset', candidate=dict(id='RC-014', sha=SHA, branch='integration/rc-014', validator='DV-086', status='demo_' + latest if latest else 'needs_review'), checks=CHECKS, workflows=WORKFLOWS, events=events)

@app.post('/api/demo/decisions')
def decide(body: Decision):
    if body.sha != SHA:
        raise HTTPException(409, 'Candidate changed. Refresh and review the current SHA.')
    now = datetime.now(timezone.utc).isoformat()
    with connect() as con:
        con.execute('INSERT INTO events (kind,payload,created) VALUES (?,?,?)', ('demo_decision', body.model_dump_json(), now))
    return {'status': 'recorded', 'mode': 'demo', 'merged': False}

@app.post('/api/demo/events')
def event(body: Event):
    now = datetime.now(timezone.utc).isoformat()
    with connect() as con:
        cursor = con.execute('INSERT OR IGNORE INTO events (delivery,kind,payload,created) VALUES (?,?,?,?)', (body.delivery_id, 'issue_received', body.model_dump_json(), now))
        created = cursor.rowcount == 1
    return {'status': 'queued' if created else 'duplicate', 'mode': 'demo', 'devin_started': False}

@app.post('/api/releases/approve')
def approve():
    raise HTTPException(409, 'Demo evidence cannot approve a real release. Live validation is not connected.')

# A single container serves the built frontend and API. Registered after API routes.
from fastapi.staticfiles import StaticFiles
if Path('static').is_dir():
    app.mount('/', StaticFiles(directory='static', html=True), name='frontend')
