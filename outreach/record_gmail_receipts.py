"""Import confirmed Gmail connector sends into the local deduplication ledger.

Input is a JSON array of Gmail full-message objects, saved under ignored data/.
This command records already-sent mail; it does not send anything.
"""
import argparse
from datetime import datetime, timezone
from email.utils import parseaddr
import json
from pathlib import Path
import pipeline


def record(db, messages, sender):
    changes = 0
    with db:
        for msg in messages:
            if 'SENT' not in msg.get('label_ids', []):
                raise ValueError('Only confirmed SENT messages can be imported')
            payload = msg['payload']
            headers = {h['name'].lower(): h['value'] for h in payload['headers']}
            if parseaddr(headers.get('from', ''))[1].lower() != sender.lower():
                raise ValueError('Receipt sender does not match campaign sender')
            address = parseaddr(headers.get('to', ''))[1].lower()
            rows = db.execute('SELECT domain,state,message_id FROM leads WHERE email=?', (address,)).fetchall()
            if len(rows) != 1:
                raise ValueError('Receipt must match exactly one researched lead')
            row = rows[0]
            message_id = headers['message-id']
            if row['state'] == 'sent' and row['message_id'] not in (message_id, 'gmail:' + msg['id']):
                raise ValueError('Lead already has a different sent message; reconcile manually')
            body = payload.get('body', {}).get('content')
            if payload.get('mime_type') != 'text/plain' or not isinstance(body, str):
                raise ValueError('Expected a plain-text outreach receipt')
            sent_at = datetime.fromtimestamp(int(msg['internal_date']) / 1000, timezone.utc).isoformat()
            db.execute('UPDATE leads SET state=?,sent_at=?,message_id=?,subject=?,body=? WHERE domain=?',
                       ('sent', sent_at, message_id, headers['subject'], body, row['domain']))
            changes += 1
    return changes


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('receipt_file', type=Path)
    args = parser.parse_args()
    cfg = json.loads((pipeline.ROOT / 'config.json').read_text(encoding='utf-8-sig'))
    messages = json.loads(args.receipt_file.read_text(encoding='utf-8-sig'))
    db = pipeline.connect()
    print(f"Recorded {record(db, messages, cfg['sender_email'])} confirmed Gmail sends")
    pipeline.export(db)
