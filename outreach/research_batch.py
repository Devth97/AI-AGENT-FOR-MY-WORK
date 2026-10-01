"""Research-only batch runner; never sends email."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import logging
import os
import time
from urllib.parse import urlsplit
import pipeline as p

NICHES = (
    'handmade candles', 'artisan soap', 'natural skincare', 'handmade jewellery',
    'ceramics pottery', 'specialty coffee beans', 'loose leaf tea', 'pet accessories',
    'linen clothing', 'home decor', 'leather bags', 'organic spices',
    'bedding textiles', 'wooden toys', 'handmade stationery', 'vegan chocolate',
    'yoga accessories', 'sustainable fashion', 'gourmet sauces', 'handmade furniture',
    'embroidery supplies', 'art prints', 'garden gifts', 'bath body products'
)
REGIONS = (('India', 'in-en'), ('United States', 'us-en'), ('United Kingdom', 'uk-en'),
           ('Australia', 'au-en'), ('New Zealand', 'nz-en'), ('South Africa', 'za-en'))
EXCLUDE = ('amazon.com','amazon.in','amazon.co.uk','etsy.com','ebay.com','facebook.com',
           'instagram.com','pinterest.com','youtube.com','tiktok.com','wikipedia.org',
           'reddit.com','linkedin.com','alibaba.com','indiamart.com','justdial.com') + p.MARKETPLACES

def research_one(row, cfg):
    # Each worker audits exactly one lead in its own temporary database.
    db = p.connect(':memory:')
    try:
        db.execute('INSERT INTO leads(domain,url,source) VALUES(?,?,?)',
                   (row['domain'], row['url'], row['source']))
        db.commit()
        p.audit(db, dict(cfg, max_audits_per_run=1), p.Crawler())
        return dict(db.execute('SELECT * FROM leads').fetchone())
    finally:
        db.close()

def discover_batch(db, searches):
    from ddgs import DDGS
    row = db.execute("SELECT value FROM settings WHERE key='batch_search_cursor'").fetchone()
    cursor = int(row[0]) if row else 0
    combinations = [(niche, country, region) for country, region in REGIONS for niche in NICHES]
    added = 0
    for offset in range(searches):
        niche, country, region = combinations[(cursor + offset) % len(combinations)]
        query = f'{niche} online shop {country} "contact"'
        page = 1 + ((cursor + offset) // len(combinations)) % 3
        try:
            results = DDGS(timeout=15).text(query, region=region, page=page,
                                          max_results=30, backend='duckduckgo,brave,bing')
            for item in results:
                url = item.get('href', '')
                domain = p.host(url)
                if not domain or urlsplit(url).scheme not in ('http', 'https'):
                    continue
                if any(domain == d or domain.endswith('.' + d) for d in EXCLUDE):
                    continue
                # Start at the store root so contact-page results still get commerce checks.
                origin = f'{urlsplit(url).scheme}://{urlsplit(url).netloc}/'
                result = db.execute('INSERT OR IGNORE INTO leads(domain,url,source) VALUES(?,?,?)',
                                    (domain, origin, query + ' | ' + url))
                added += result.rowcount
            db.execute("INSERT OR REPLACE INTO settings VALUES('batch_search_cursor',?)",
                       (str(cursor + offset + 1),))
            db.commit()
            print(json.dumps({'query': query, 'added_so_far': added}), flush=True)
        except Exception as exc:
            print(json.dumps({'query': query, 'error': type(exc).__name__}), flush=True)
        time.sleep(3)
    return added

def audit_batch(db, cfg, limit, workers):
    rows = [dict(r) for r in db.execute("SELECT domain,url,source FROM leads WHERE state='new' LIMIT ?", (limit,))]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        pending = {pool.submit(research_one, row, cfg): row['domain'] for row in rows}
        for future in as_completed(pending):
            domain = pending[future]
            try:
                row = future.result()
                fields = ('state','email','evidence','subject','body','checked','error')
                # Never overwrite a send reservation or a lead changed during this run.
                db.execute('UPDATE leads SET ' + ','.join(k+'=?' for k in fields) +
                           " WHERE domain=? AND state='new'", tuple(row[k] for k in fields)+(domain,))
                db.commit()
                print(json.dumps({'domain': domain, 'state': row['state']}), flush=True)
            except Exception as exc:
                print(json.dumps({'domain': domain, 'error': str(exc)}), flush=True)
    p.export(db)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--searches', type=int, default=24)
    parser.add_argument('--max-sites', type=int, default=300)
    parser.add_argument('--workers', type=int, choices=range(1,9), default=6)
    args = parser.parse_args()
    if args.searches < 0 or args.max_sites < 0:
        parser.error('Counts must be nonnegative')
    cfg = json.loads((p.ROOT / 'config.json').read_text(encoding='utf-8-sig'))
    logging.basicConfig(level=logging.ERROR)
    logging.getLogger('scrapling').setLevel(logging.ERROR)
    db = p.connect()
    # Research has its own lock so a long audit cannot block the send schedule.
    lock = (p.ROOT / 'data' / 'research.lock').open('a+b')
    try:
        if os.name == 'nt':
            import msvcrt
            lock.seek(0)
            if not lock.read(1):
                lock.write(b'0')
                lock.flush()
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if args.searches:
            discover_batch(db, args.searches)
        audit_batch(db, cfg, args.max_sites, args.workers)
        print(json.dumps({r['state']:r['n'] for r in db.execute('SELECT state,COUNT(*) n FROM leads GROUP BY state')}))
    finally:
        db.close()
        lock.close()

if __name__ == '__main__':
    main()
