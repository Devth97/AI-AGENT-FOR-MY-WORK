"""Bounded Scrapling prospect discovery, evidence collection, drafts and outreach."""
import argparse
import csv
import imaplib
import ipaddress
import json
import logging
import os
from pathlib import Path
import re
import smtplib
import socket
import sqlite3
import ssl
import time
from datetime import datetime, timezone
from email import message_from_bytes
from email.message import EmailMessage
from email.utils import parseaddr, formataddr, make_msgid
from urllib.parse import urljoin, urlsplit, urlencode, urldefrag, parse_qsl, urlunsplit
from urllib.request import Request, urlopen
from urllib.robotparser import RobotFileParser

ROOT = Path(__file__).resolve().parent
UA = 'WebsiteOpportunityResearch/1.0'
EMAIL = re.compile(r'^[A-Z0-9.!#$%&\x27*+/=?^_`{|}~-]+@[A-Z0-9.-]+\.[A-Z]{2,}$', re.I)
MARKETPLACES = ('freelancer.com', 'upwork.com', 'fiverr.com', 'peopleperhour.com', 'guru.com')

def now():
    return datetime.now(timezone.utc).isoformat()

def host(url):
    return (urlsplit(url).hostname or '').lower().removeprefix('www.')

def public_url(url):
    p = urlsplit(url)
    if p.scheme not in ('https', 'http') or not p.hostname or p.username or p.password:
        raise ValueError('A public HTTP(S) URL is required')
    if p.port not in (None, 80, 443):
        raise ValueError('Nonstandard port')
    addresses = socket.getaddrinfo(p.hostname, p.port or 443)
    if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
        raise ValueError('Nonpublic address')
    return url

class Crawler:
    def __init__(self):
        self.robots = {}
        self.last = {}

    def raw(self, url):
        from scrapling.fetchers import Fetcher
        public_url(url)
        domain = host(url)
        time.sleep(max(0, 2 - (time.monotonic() - self.last.get(domain, 0))))
        self.last[domain] = time.monotonic()
        # Redirects are handled explicitly so robots rules are checked at each destination.
        return Fetcher.get(url, headers={'User-Agent': UA}, stealthy_headers=False,
                           follow_redirects=False, timeout=25, retries=0)

    def fetch(self, url, hops=0):
        if hops > 5:
            raise ValueError('Redirect limit')
        public_url(url)
        p = urlsplit(url)
        origin = f'{p.scheme}://{p.netloc}'
        if origin not in self.robots:
            r = self.raw(origin + '/robots.txt')
            rules = RobotFileParser()
            if r.status == 404:
                rules.parse([])
            elif r.status == 200:
                rules.parse(r.body.decode('utf-8', errors='replace').splitlines())
            else:
                raise ValueError(f'robots.txt unavailable: HTTP {r.status}')
            self.robots[origin] = rules
        rules = self.robots[origin]
        if not rules.can_fetch(UA, url):
            raise ValueError('robots.txt disallows this page')
        delay = rules.crawl_delay(UA) or 2
        time.sleep(max(0, delay - (time.monotonic() - self.last.get(host(url), 0))))
        page = self.raw(url)
        if page.status in (301, 302, 303, 307, 308):
            return self.fetch(urljoin(url, page.headers.get('location', page.headers.get('Location', ''))), hops + 1)
        if page.status != 200:
            raise ValueError(f'HTTP {page.status}')
        return page

def connect(path=None):
    (ROOT / 'data').mkdir(exist_ok=True)
    db = sqlite3.connect(path or ROOT / 'data' / 'outreach.sqlite')
    db.row_factory = sqlite3.Row
    db.executescript('''
    CREATE TABLE IF NOT EXISTS leads (
      domain TEXT PRIMARY KEY, url TEXT NOT NULL, source TEXT NOT NULL,
      state TEXT NOT NULL DEFAULT 'new', email TEXT, evidence TEXT, subject TEXT, body TEXT,
      checked TEXT, sent_at TEXT, message_id TEXT, error TEXT);
    CREATE TABLE IF NOT EXISTS suppressed (email TEXT PRIMARY KEY, reason TEXT, created TEXT);
    CREATE TABLE IF NOT EXISTS listings (url TEXT PRIMARY KEY, title TEXT, source TEXT,
      seen TEXT, draft TEXT, status TEXT DEFAULT 'verify_open_on_platform');
    CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
    ''')
    db.commit()
    return db

def discover(db, cfg, crawler):
    urls = [(u, 'configured seed') for u in cfg['seed_urls']]
    key = os.getenv('BRAVE_SEARCH_API_KEY')
    if cfg.get('search_provider') == 'ddgs':
        from ddgs import DDGS
        cursor = db.execute("SELECT value FROM settings WHERE key='search_cursor'").fetchone()
        cursor = int(cursor[0]) if cursor else 0
        regions = cfg.get('search_regions', ['us-en'])
        combinations = [(query, region) for region in regions for query in cfg['queries']]
        batch_size = min(cfg.get('queries_per_run', 4), len(combinations))
        for offset in range(batch_size):
            query, region = combinations[(cursor + offset) % len(combinations)]
            search_page = 1 + ((cursor + offset) // len(combinations)) % 3
            try:
                results = DDGS(timeout=20).text(query, max_results=20, region=region, page=search_page,
                                              backend='duckduckgo,brave,bing')
                urls.extend((x['href'], query) for x in results)
            except Exception as exc:
                logging.warning('Free search failed for %s: %s', query, type(exc).__name__)
            time.sleep(3)
        db.execute("INSERT OR REPLACE INTO settings VALUES('search_cursor',?)", (str(cursor + batch_size),))
        db.commit()
    elif cfg['queries'] and not key:
        logging.warning('Search discovery skipped: BRAVE_SEARCH_API_KEY is missing')
    for query in cfg['queries'] if key and cfg.get('search_provider') == 'brave' else []:
        endpoint = 'https://api.search.brave.com/res/v1/web/search?' + urlencode({'q': query, 'count': 20})
        req = Request(endpoint, headers={'X-Subscription-Token': key, 'Accept': 'application/json'})
        try:
            with urlopen(req, timeout=30) as r:
                result = json.load(r)
            urls.extend((x['url'], query) for x in result.get('web', {}).get('results', []))
        except Exception as exc:
            logging.warning('Search failed: %s', type(exc).__name__)
        time.sleep(1.1)
    for url, source in urls:
        domain = host(url)
        if domain and not any(domain == m or domain.endswith('.' + m) for m in MARKETPLACES):
            db.execute('INSERT OR IGNORE INTO leads(domain,url,source) VALUES(?,?,?)', (domain, url, source))
    db.commit()
    for source in cfg['listing_sources']:
        try:
            page = crawler.fetch(source['url'])
            links = page.css(source['selector'])
            if not links:
                logging.warning('No listing links at %s; check source selector', source['url'])
            for node in links[:30]:
                url = urljoin(source['url'], node.attrib.get('href', ''))
                title = node.get_all_text().strip()[:240]
                if not title or host(url) != host(source['url']):
                    continue
                if host(url) == 'peopleperhour.com' and not re.search(r'-\d{5,}(?:[/?#]|$)', url):
                    continue
                draft = (f'Hi,\n\nI saw your project, "{title}". '
                         'Can you share your priorities, target date and any existing site? '
                         'That would help me outline the work and give you an estimate.\n\n'
                         f"{cfg['sender_name'] or '[Sender name]'}\n{cfg['portfolio_url'] or '[Portfolio URL]'}")
                db.execute('INSERT INTO listings(url,title,source,seen,draft) VALUES(?,?,?,?,?) '
                           'ON CONFLICT(url) DO UPDATE SET seen=excluded.seen,title=excluded.title,draft=excluded.draft',
                           (url, title, source['url'], now(), draft))
            db.commit()
        except Exception as exc:
            logging.warning('Listing source %s: %s', source['url'], exc)

def inspect_page(page, url):
    """Only observations of fetched HTML, not a ranking or whole-site verdict."""
    findings = []
    checks = [
        ('title', 'No title element was found in the fetched HTML'),
        ('meta[name="description"]::attr(content)', 'No meta description content was found in the fetched HTML'),
        ('h1', 'No H1 heading was found in the fetched HTML'),
        ('meta[name="viewport"]', 'No viewport meta tag was found in the fetched HTML'),
        ('link[rel="canonical"]::attr(href)', 'No canonical link was found in the fetched HTML')]
    for selector, observation in checks:
        if not page.css(selector):
            findings.append({'url': url, 'observation': observation})
    images = page.css('img')
    missing = sum('alt' not in x.attrib for x in images)
    if missing:
        findings.append({'url': url, 'observation': f'{missing} image elements have no alt attribute in the fetched HTML'})
    return findings

def answer_readiness(pages):
    """Observable signals only. Absence is an opportunity to review, not a defect."""
    signals = []
    for url, page in pages:
        headings = [x.get_all_text().strip() for x in page.css('h1,h2,h3')]
        schemas = []
        invalid_json = 0
        def walk(value):
            if isinstance(value, dict):
                kind = value.get('@type', [])
                schemas.extend(kind if isinstance(kind, list) else [kind])
                for child in value.values():
                    walk(child)
            elif isinstance(value, list):
                for child in value:
                    walk(child)
        for raw in page.css('script[type="application/ld+json"]::text').getall():
            try:
                walk(json.loads(raw))
            except (ValueError, TypeError):
                invalid_json += 1
        signals.append({'url': url, 'question_headings': [h for h in headings if '?' in h],
                        'structured_data_types': sorted(set(x for x in schemas if isinstance(x, str))),
                        'invalid_json_ld_blocks': invalid_json,
                        'interpretation': 'Signals for manual AEO/GEO review, not a ranking score. Other structured-data formats and rendered content are not assessed.'})
    return signals

def plain_observation(observation):
    """Humanizer-edited wording for known findings; preserve facts and HTML scope."""
    images = re.fullmatch(r'(\d+) image elements have no alt attribute in the fetched HTML', observation)
    if images:
        count = int(images.group(1))
        noun = 'image' if count == 1 else 'images'
        return f'The HTML I fetched includes {count} {noun} without alt attributes.'
    wording = {
        'No title element was found in the fetched HTML': "I couldn't find a title element in the HTML I fetched.",
        'No meta description content was found in the fetched HTML': "I couldn't find meta description content in the HTML I fetched.",
        'No H1 heading was found in the fetched HTML': "I couldn't find an H1 heading in the HTML I fetched.",
        'No viewport meta tag was found in the fetched HTML': "I couldn't find a viewport meta tag in the HTML I fetched.",
        'No canonical link was found in the fetched HTML': "I couldn't find a canonical link in the HTML I fetched."
    }
    return wording.get(observation, observation.rstrip('. ') + '.')


def compose(cfg, domain, evidence):
    if not evidence:
        return '', ''
    first = evidence[0]
    page_path = urlsplit(first['url']).path or '/'
    subject = f'Website improvements for {domain}'
    body = (f"Hi {domain} team,\n\nI checked {domain}{page_path}. {plain_observation(first['observation'])} "
            "I'd check the page in a browser before recommending a fix.\n\n"
            f"At {cfg['business_name']}, we work on {cfg['offer']}. "
            'Can I send you a free audit with suggested fixes?\n\n'
            f"{cfg['sender_name'] or '[Sender name]'}\n{cfg['business_name'] or '[Business name]'}\n"
            f"{cfg['portfolio_url'] or '[Portfolio URL]'}\n{cfg['postal_address'] or '[Business postal address]'}\n\n"
            'Business service offer. Reply "no thanks" to stop further outreach.')
    return subject, body

def full_page_url(url):
    parts = urlsplit(url)
    query = [(key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True)
             if key.lower() not in ('view', 'section_id', 'sections')]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ''))


def audit(db, cfg, crawler):
    rows = db.execute("SELECT * FROM leads WHERE state='new' LIMIT ?", (cfg['max_audits_per_run'],)).fetchall()
    for row in rows:
        try:
            page = crawler.fetch(row['url'])
            text = page.get_all_text().lower()
            links = [urljoin(row['url'], h) for h in page.css('a::attr(href)').getall()]
            ecommerce = any(x in text for x in ('add to cart', 'add to bag', 'shopping cart', 'buy now')) or any('/products/' in x for x in links)
            if not ecommerce:
                db.execute("UPDATE leads SET state='not_confirmed_ecommerce', checked=? WHERE domain=?", (now(), row['domain']))
                db.commit()
                continue
            pages = [(row['url'], page)]
            candidates = [full_page_url(u) for u in links if host(u) == row['domain'] and any(x in u.lower() for x in ('/products/', '/contact', '/about', '/faq'))]
            candidates.sort(key=lambda u: (0 if 'contact' in u.lower() else 1 if 'about' in u.lower() else 2 if 'faq' in u.lower() else 3))
            for url in list(dict.fromkeys(candidates))[:4]:
                try:
                    pages.append((url, crawler.fetch(url)))
                except Exception as exc:
                    logging.info('Skipped %s: %s', url, exc)
            evidence, contacts = [], []
            for url, p in pages:
                evidence.extend(inspect_page(p, url))
                published = [v[7:].split('?')[0] for v in p.css('a[href^="mailto:"]::attr(href)').getall()]
                published += re.findall(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}', p.get_all_text())
                for value in published:
                    address = value.strip().lower()
                    local, _, domain = address.partition('@')
                    if EMAIL.fullmatch(address) and domain.removeprefix('www.') == row['domain'] and local in ('hello', 'info', 'contact', 'business', 'sales', 'partnerships', 'marketing', 'collaborations', 'enquiries', 'inquiries'):
                        contacts.append({'email': address, 'source_url': url})
            unique = list({x['observation']: x for x in evidence}.values())
            subject, body = compose(cfg, row['domain'], unique)
            state = 'ready' if contacts and len(unique) >= cfg['min_findings'] else 'researched'
            payload = {'observations': unique, 'contacts': contacts,
                       'scope': [u for u, p in pages],
                       'aeo_geo_signals': answer_readiness(pages),
                       'aeo_geo_review': 'Review answer clarity, factual specificity, entity consistency, citations and product information. No AI visibility score is inferred.'}
            db.execute('UPDATE leads SET state=?,email=?,evidence=?,subject=?,body=?,checked=?,error=NULL WHERE domain=?',
                       (state, contacts[0]['email'] if contacts else None, json.dumps(payload), subject, body, now(), row['domain']))
        except Exception as exc:
            db.execute("UPDATE leads SET state='research_error',error=?,checked=? WHERE domain=?", (str(exc), now(), row['domain']))
        db.commit()

def suppress(db, address, reason):
    db.execute('INSERT OR REPLACE INTO suppressed VALUES(?,?,?)', (address.lower(), reason, now()))
    db.commit()

def sync_replies(db):
    # Every reply from a contacted address stops automation, including positive replies.
    # Scan all mail on each run; this favors correctness over efficiency for small campaigns.
    with imaplib.IMAP4_SSL(os.environ['IMAP_HOST'], int(os.getenv('IMAP_PORT', '993'))) as mailbox:
        mailbox.login(os.environ['IMAP_USER'], os.environ['IMAP_PASSWORD'])
        status, _ = mailbox.select('INBOX', readonly=True)
        if status != 'OK':
            raise RuntimeError('Cannot read reply inbox; sending stopped')
        status, ids = mailbox.search(None, 'ALL')
        if status != 'OK':
            raise RuntimeError('Cannot search reply inbox; sending stopped')
        contacted = {r['email']: r['message_id'] for r in db.execute("SELECT email,message_id FROM leads WHERE sent_at IS NOT NULL")}
        for ident in ids[0].split():
            status, parts = mailbox.fetch(ident, '(BODY.PEEK[])')
            if status != 'OK':
                raise RuntimeError('Reply sync incomplete; sending stopped')
            for part in parts:
                if not isinstance(part, tuple):
                    continue
                msg = message_from_bytes(part[1])
                sender = parseaddr(msg.get('From', ''))[1].lower()
                if sender in contacted:
                    suppress(db, sender, 'Incoming reply: human follow-up required')
                # Catch delivery reports and forwarded opt-outs referencing an original message.
                raw = part[1].decode('utf-8', errors='replace')
                if msg.get_content_type() == 'multipart/report':
                    for address, mid in contacted.items():
                        if (mid and mid in raw) or address in raw:
                            suppress(db, address, 'Delivery report')

def send_one(db, cfg):
    if not cfg['send_enabled']:
        return
    if cfg.get('market') in (None, '', 'pending'):
        raise ValueError('Configure the target market before sending')
    required = ['business_name', 'sender_name', 'sender_email', 'postal_address', 'portfolio_url']
    missing = [k for k in required if not cfg.get(k)]
    missing += [k for k in ('SMTP_HOST','SMTP_USER','SMTP_PASSWORD','IMAP_HOST','IMAP_USER','IMAP_PASSWORD') if not os.getenv(k)]
    if missing:
        raise ValueError('Sending needs: ' + ', '.join(missing))
    if not EMAIL.fullmatch(cfg['sender_email']):
        raise ValueError('Invalid sender email')
    sync_replies(db)
    # The outer process lock serializes runs. Persist a reservation BEFORE SMTP.
    # Unknown delivery outcomes are never automatically retried.
    today = now()[:10]
    count = db.execute('SELECT COUNT(*) FROM leads WHERE sent_at LIKE ?', (today+'%',)).fetchone()[0]
    last = db.execute('SELECT MAX(sent_at) FROM leads').fetchone()[0]
    if count >= cfg['daily_limit'] or (last and (datetime.now(timezone.utc) - datetime.fromisoformat(last)).total_seconds() < cfg['min_send_interval_seconds']):
        return
    row = db.execute("SELECT * FROM leads WHERE state='ready' AND email NOT IN (SELECT email FROM suppressed) AND email NOT IN (SELECT email FROM leads WHERE sent_at IS NOT NULL) ORDER BY checked LIMIT 1").fetchone()
    if not row:
        return
    if (datetime.now(timezone.utc) - datetime.fromisoformat(row['checked'])).days >= 7:
        db.execute("UPDATE leads SET state='new' WHERE domain=?", (row['domain'],))
        db.commit()
        return
    subject, body = compose(cfg, row['domain'], json.loads(row['evidence'])['observations'])
    msg = EmailMessage()
    msg['From'] = formataddr((cfg['sender_name'], cfg['sender_email']))
    msg['To'] = row['email']
    msg['Subject'] = subject
    msg['Message-ID'] = make_msgid(domain=cfg['sender_email'].split('@')[1])
    msg['List-Unsubscribe'] = f"<mailto:{cfg['sender_email']}?subject=Unsubscribe>"
    msg.set_content(body)
    db.execute("UPDATE leads SET state='delivery_unknown',sent_at=?,message_id=? WHERE domain=?", (now(), msg['Message-ID'], row['domain']))
    db.commit()
    try:
        with smtplib.SMTP(os.environ['SMTP_HOST'], int(os.getenv('SMTP_PORT', '587')), timeout=30) as smtp:
            smtp.ehlo()
            smtp.starttls(context=ssl.create_default_context())
            smtp.ehlo()
            smtp.login(os.environ['SMTP_USER'], os.environ['SMTP_PASSWORD'])
            smtp.send_message(msg)
        db.execute("UPDATE leads SET state='sent',subject=?,body=? WHERE domain=?", (subject, body, row['domain']))
        db.commit()
    except Exception:
        logging.error('Delivery outcome requires manual reconciliation; automatic retry disabled')
        raise

def export(db):
    for table in ('leads', 'listings'):
        rows = db.execute(f'SELECT * FROM {table}')
        with (ROOT / 'data' / f'{table}.csv').open('w', newline='', encoding='utf-8-sig') as f:
            writer = csv.writer(f)
            writer.writerow([d[0] for d in rows.description])
            # Prevent spreadsheet formula execution in scraped data.
            writer.writerows([["'"+v if isinstance(v, str) and v[:1] in ('=','+','-','@','\t','\r') else v for v in row] for row in rows])

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['run', 'research', 'send', 'export', 'suppress'])
    parser.add_argument('--email')
    args = parser.parse_args()
    cfg = json.loads((ROOT / 'config.json').read_text(encoding='utf-8-sig'))
    (ROOT / 'data').mkdir(exist_ok=True)
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s',
                        handlers=[logging.FileHandler(ROOT / 'data' / 'runs.log'), logging.StreamHandler()])
    # OS releases this lock even after a crash; works with Windows Task Scheduler.
    lock = (ROOT / 'data' / 'run.lock').open('a+b')
    try:
        if os.name == 'nt':
            import msvcrt
            lock.seek(0)
            lock.write(b'0')
            lock.flush()
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        db = connect()
        if args.command == 'suppress':
            if not args.email or not EMAIL.fullmatch(args.email):
                parser.error('--email requires a valid address')
            suppress(db, args.email, 'Manual suppression')
        if args.command in ('run', 'research'):
            crawler = Crawler()
            discover(db, cfg, crawler)
            audit(db, cfg, crawler)
        if args.command in ('run', 'send'):
            send_one(db, cfg)
        export(db)
        print(json.dumps({r['state']: r['n'] for r in db.execute('SELECT state,COUNT(*) n FROM leads GROUP BY state')}))
    finally:
        lock.close()

if __name__ == '__main__':
    main()
