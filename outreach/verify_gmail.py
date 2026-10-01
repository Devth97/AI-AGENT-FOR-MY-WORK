"""Authenticate only; do not send a message or change the mailbox."""
import imaplib
import json
import os
from pathlib import Path
import smtplib
import ssl
import sys

cfg = json.loads((Path(__file__).parent / 'config.json').read_text(encoding='utf-8-sig'))
if os.environ['SMTP_USER'].lower() != cfg['sender_email'].lower():
    raise ValueError('Credential account must match the configured sender')
try:
    with smtplib.SMTP('smtp.gmail.com', 587, timeout=30) as smtp:
        smtp.ehlo()
        smtp.starttls(context=ssl.create_default_context())
        smtp.ehlo()
        smtp.login(os.environ['SMTP_USER'], os.environ['SMTP_PASSWORD'])
    with imaplib.IMAP4_SSL('imap.gmail.com') as mailbox:
        mailbox.login(os.environ['SMTP_USER'], os.environ['SMTP_PASSWORD'])
        status, _ = mailbox.select('INBOX', readonly=True)
        if status != 'OK':
            raise RuntimeError('Cannot access reply inbox')
except (smtplib.SMTPAuthenticationError, imaplib.IMAP4.error):
    print('Gmail rejected the local credential. Create a new 16-character Google app password, enter it without spaces in connect-gmail.ps1, then run activate-sending.ps1 again. Do not share the password in chat.', file=sys.stderr)
    sys.exit(1)
print('Gmail SMTP and IMAP authentication verified. No message sent.')
