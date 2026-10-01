"""Import public Shopify store URLs as candidates; research still uses Scrapling."""
import csv
import io
import json
import re
from urllib.parse import urlsplit
import pipeline as p

DATASET_PAGE = 'https://huggingface.co/datasets/snncn/shopify-websites'
CSV_URL = DATASET_PAGE + '/resolve/main/shopify-website-list.csv'


def main():
    page = p.Crawler().fetch(CSV_URL)
    raw = page.body.decode('utf-8-sig')
    reader = csv.DictReader(io.StringIO(raw))
    if 'url' not in (reader.fieldnames or []):
        raise ValueError('Shopify dataset CSV lacks its documented url column')
    db = p.connect()
    added = 0
    for row in reader:
        address = (row.get('url') or '').strip()
        parts = urlsplit(address)
        domain = p.host(address)
        if parts.scheme not in ('http', 'https') or not re.fullmatch(r'[a-z0-9.-]+\.[a-z]{2,}', domain):
            continue
        if domain.endswith('.myshopify.com'):
            continue
        source = DATASET_PAGE + ' | Apache-2.0 | retrieved ' + p.now()[:10]
        added += db.execute('INSERT OR IGNORE INTO leads(domain,url,source) VALUES(?,?,?)',
                            (domain, parts.scheme + '://' + parts.netloc + '/', source)).rowcount
    db.commit()
    print(json.dumps({'new_candidate_domains': added, 'source': DATASET_PAGE, 'license': 'Apache-2.0'}))


if __name__ == '__main__':
    main()
