import json
import unittest
from unittest.mock import patch, MagicMock
import pipeline as p
from scrapling.parser import Selector

class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.db = p.connect(':memory:')
        self.cfg = json.loads((p.ROOT / 'config.json').read_text())
        self.cfg.update(send_enabled=True, postal_address='Test address', market='Test')
        self.env = {k: 'test' for k in ('SMTP_HOST','SMTP_USER','SMTP_PASSWORD','IMAP_HOST','IMAP_USER','IMAP_PASSWORD')}
    def tearDown(self):
        self.db.close()
    def add(self, domain='shop.test', address='hello@shop.test'):
        self.db.execute('INSERT INTO leads(domain,url,source,state,email,evidence,checked) VALUES(?,?,?,?,?,?,?)',
                        (domain, 'https://'+domain, 'fixture', 'ready', address,
                         json.dumps({'observations':[{'url':'https://'+domain, 'observation':'Missing title in fetched HTML'}]}), p.now()))
        self.db.commit()
    def test_evidence_is_scoped(self):
        page = Selector('<html><head><title>Shop</title></head><body><h1>Shop</h1><img src="x"></body></html>')
        findings = p.inspect_page(page, 'https://shop.test/product')
        self.assertTrue(any('alt attribute' in x['observation'] for x in findings))
        self.assertFalse(any('No title' in x['observation'] for x in findings))
        self.assertTrue(all(x['url'].endswith('/product') for x in findings))
    def test_schema_graph(self):
        page = Selector('<script type="application/ld+json">{"@graph":[{"@type":"Product"}]}</script><h2>How does it work?</h2>')
        signals = p.answer_readiness([('https://shop.test',page)])
        self.assertEqual(signals[0]['structured_data_types'], ['Product'])
    def test_private_url_rejected(self):
        with self.assertRaises(ValueError):
            p.public_url('http://127.0.0.1/')
    def test_quick_view_links_audit_full_page_and_preserve_variant(self):
        self.assertEqual(p.full_page_url('https://shop.test/products/item?section_id=quick-view&variant=12#details'),
                         'https://shop.test/products/item?variant=12')
        self.assertEqual(p.full_page_url('https://shop.test/products/item?view=quick'),
                         'https://shop.test/products/item')
    def test_disabled_never_connects(self):
        self.cfg['send_enabled'] = False
        with patch.object(p, 'sync_replies') as sync:
            p.send_one(self.db, self.cfg)
            sync.assert_not_called()
    def test_suppression_prevents_send(self):
        self.add()
        p.suppress(self.db, 'hello@shop.test', 'unsubscribe')
        with patch.dict(p.os.environ, self.env), patch.object(p,'sync_replies'), patch.object(p.smtplib,'SMTP') as smtp:
            p.send_one(self.db, self.cfg)
            smtp.assert_not_called()
    def test_ambiguous_delivery_not_retried(self):
        self.add()
        with patch.dict(p.os.environ, self.env), patch.object(p,'sync_replies'), patch.object(p.smtplib,'SMTP',side_effect=TimeoutError):
            with self.assertRaises(TimeoutError):
                p.send_one(self.db, self.cfg)
        self.assertEqual(self.db.execute('SELECT state FROM leads').fetchone()[0], 'delivery_unknown')
        with patch.dict(p.os.environ, self.env), patch.object(p,'sync_replies'), patch.object(p.smtplib,'SMTP') as smtp:
            p.send_one(self.db, self.cfg)
            smtp.assert_not_called()
    def test_reply_sync_failure_blocks_send(self):
        self.add()
        with patch.dict(p.os.environ, self.env), patch.object(p,'sync_replies',side_effect=RuntimeError), patch.object(p.smtplib,'SMTP') as smtp:
            with self.assertRaises(RuntimeError):
                p.send_one(self.db, self.cfg)
            smtp.assert_not_called()
    def test_daily_limit(self):
        self.add()
        self.cfg['daily_limit'] = 0
        with patch.dict(p.os.environ, self.env), patch.object(p,'sync_replies'), patch.object(p.smtplib,'SMTP') as smtp:
            p.send_one(self.db, self.cfg)
            smtp.assert_not_called()
    def test_campaign_target_blocks_smtp(self):
        self.add()
        self.cfg['campaign_target_total'] = 0
        with patch.dict(p.os.environ, self.env), patch.object(p,'sync_replies'), patch.object(p.smtplib,'SMTP') as smtp:
            p.send_one(self.db, self.cfg)
            smtp.assert_not_called()
    def test_no_findings_no_outreach_draft(self):
        self.assertEqual(p.compose(self.cfg, 'shop.test', []), ('', ''))
    def test_humanizer_wording_preserves_evidence_and_footer(self):
        evidence = [{'url': 'https://shop.test/products/lamp',
                     'observation': '12 image elements have no alt attribute in the fetched HTML'}]
        _, body = p.compose(self.cfg, 'shop.test', evidence)
        self.assertIn('shop.test/products/lamp', body)
        self.assertIn('12 images without alt attributes', body)
        self.assertIn('HTML I fetched', body)
        self.assertIn('in a browser before recommending', body)
        self.assertIn(self.cfg['postal_address'], body)
        self.assertIn('Reply "no thanks"', body)
    def test_unknown_observation_keeps_case_and_numbers(self):
        self.assertEqual(p.plain_observation('HTTP 503 occurred on 2 pages'), 'HTTP 503 occurred on 2 pages.')
        self.assertIn('1 image without', p.plain_observation('1 image elements have no alt attribute in the fetched HTML'))
    def test_successful_send_persists_and_deduplicates(self):
        self.add()
        with patch.dict(p.os.environ, self.env), patch.object(p,'sync_replies'), patch.object(p.smtplib,'SMTP') as smtp:
            p.send_one(self.db, self.cfg)
            p.send_one(self.db, self.cfg)
            smtp.return_value.__enter__.return_value.send_message.assert_called_once()
        row = self.db.execute('SELECT * FROM leads').fetchone()
        self.assertEqual(row['state'], 'sent')
        self.assertIn('free audit', row['body'])

if __name__ == '__main__':
    unittest.main()
