"""Import candidate domains from StoreProfiles' public CC BY 4.0 CSV.

The directory supplies discovery only. Scrapling must audit each store before outreach.
"""
import csv
import io
import json
import re
import pipeline as p

def main():
    url = 'https://storeprofiles.com/registry.csv'
    page = p.Crawler().fetch(url)
    raw = page.body.decode('utf-8-sig')
    reader = csv.DictReader(io.StringIO(raw))
    if 'domain' not in (reader.fieldnames or []):
        raise ValueError('Registry CSV does not have the documented domain column')
    db = p.connect()
    added = 0
    for row in reader:
        domain = row['domain'].strip().lower()
        if not re.fullmatch(r'[a-z0-9.-]+\.[a-z]{2,}', domain):
            continue
        source = f'StoreProfiles, CC BY 4.0, {url}, retrieved {p.now()[:10]}, slug={row.get("slug", "")}'
        added += db.execute('INSERT OR IGNORE INTO leads(domain,url,source) VALUES(?,?,?)',
                            (domain, 'https://' + domain + '/', source)).rowcount
    db.commit()
    print(json.dumps({'new_candidate_domains': added, 'source': url, 'license': 'CC BY 4.0'}))

if __name__ == '__main__':
    main()
