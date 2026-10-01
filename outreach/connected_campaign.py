"""Reserve reviewed connector messages before Gmail sends them; never sends mail."""
import argparse
import json
from pathlib import Path
import pipeline as p

def reserve(db, messages, target):
    if target < 1 or not messages:
        raise ValueError('A positive target and reviewed messages are required')
    cfg = json.loads((p.ROOT / 'config.json').read_text(encoding='utf-8-sig'))
    db.execute('BEGIN IMMEDIATE')
    try:
        used = db.execute('SELECT COUNT(*) FROM leads WHERE sent_at IS NOT NULL').fetchone()[0]
        if used + len(messages) > min(target, cfg['campaign_target_total']):
            raise ValueError('Campaign target would be exceeded')
        for msg in messages:
            row = db.execute('SELECT * FROM leads WHERE domain=?', (msg['domain'],)).fetchone()
            if not row or row['state'] != 'ready' or row['sent_at'] or row['email'] != msg['to']:
                raise ValueError('Recipient is not an unsent qualified lead')
            if db.execute('SELECT 1 FROM suppressed WHERE email=?', (msg['to'],)).fetchone():
                raise ValueError('Recipient is suppressed')
            if db.execute('SELECT 1 FROM leads WHERE email=? AND sent_at IS NOT NULL', (msg['to'],)).fetchone():
                raise ValueError('Recipient was already contacted')
            if not msg.get('history_checked'):
                raise ValueError('Check Gmail history before reserving')
            if not all(value in msg['body'] for value in (cfg['sender_name'], cfg['postal_address'], 'no thanks')):
                raise ValueError('Required sender and opt-out details missing')
            db.execute('UPDATE leads SET state=?,sent_at=?,subject=?,body=? WHERE domain=?',
                       ('delivery_unknown', p.now(), msg['subject'], msg['body'], msg['domain']))
        db.commit()
    except Exception:
        db.rollback()
        raise
    return len(messages)

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('messages', type=Path)
    parser.add_argument('--target', type=int, default=250)
    args = parser.parse_args()
    messages = json.loads(args.messages.read_text(encoding='utf-8-sig'))
    db = p.connect()
    print(f'Reserved {reserve(db, messages, args.target)} reviewed messages')
