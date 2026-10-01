import json
import unittest
from unittest.mock import patch
import pipeline as p
import connected_campaign as campaign
import research_batch as research


class CampaignTests(unittest.TestCase):
    def setUp(self):
        self.db = p.connect(':memory:')
        self.cfg = json.loads((p.ROOT / 'config.json').read_text(encoding='utf-8-sig'))

    def tearDown(self):
        self.db.close()

    def lead(self, domain='shop.test'):
        self.db.execute('INSERT INTO leads(domain,url,source,state,email) VALUES(?,?,?,?,?)',
                        (domain, 'https://' + domain, 'fixture', 'ready', 'hello@' + domain))
        self.db.commit()
        return dict(domain=domain, to='hello@' + domain, subject='Audit', history_checked=True,
                    body=self.cfg['sender_name'] + '\n' + self.cfg['postal_address'] + '\nReply no thanks')

    def test_reservation_blocks_duplicate_attempt(self):
        msg = self.lead()
        campaign.reserve(self.db, [msg], 250)
        with self.assertRaises(ValueError):
            campaign.reserve(self.db, [msg], 250)
        self.assertEqual(self.db.execute('SELECT state FROM leads').fetchone()[0], 'delivery_unknown')

    def test_batch_rolls_back_if_any_recipient_is_suppressed(self):
        first, second = self.lead(), self.lead('other.test')
        p.suppress(self.db, second['to'], 'opt out')
        with self.assertRaises(ValueError):
            campaign.reserve(self.db, [first, second], 250)
        self.assertIsNone(self.db.execute('SELECT sent_at FROM leads WHERE domain=?', (first['domain'],)).fetchone()[0])

    def test_target_includes_uncertain_sends(self):
        first, second = self.lead(), self.lead('other.test')
        campaign.reserve(self.db, [first], 1)
        with self.assertRaises(ValueError):
            campaign.reserve(self.db, [second], 1)

    def test_daily_limit_blocks_additional_reservation(self):
        first, second = self.lead(), self.lead('other.test')
        campaign.reserve(self.db, [first], 750)
        for i in range(49):
            self.db.execute('INSERT INTO leads(domain,url,source,state,email,sent_at) VALUES(?,?,?,?,?,?)',
                            (f'past{i}.test', 'https://past.test', 'fixture', 'sent', f'past{i}@test.example', p.now()))
        self.db.commit()
        with self.assertRaisesRegex(ValueError, 'Daily send limit'):
            campaign.reserve(self.db, [second], 750)

    def test_history_check_required(self):
        msg = self.lead()
        msg['history_checked'] = False
        with self.assertRaises(ValueError):
            campaign.reserve(self.db, [msg], 250)

    def test_worker_only_audits_its_own_lead(self):
        row = dict(domain='only.test', url='https://only.test', source='fixture')
        def audit(db, cfg, crawler):
            self.assertEqual(cfg['max_audits_per_run'], 1)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM leads').fetchone()[0], 1)
            db.execute("UPDATE leads SET state='researched'")
        with patch.object(p, 'audit', side_effect=audit):
            result = research.research_one(row, self.cfg)
        self.assertEqual(result['domain'], row['domain'])
        self.assertEqual(result['state'], 'researched')
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM leads').fetchone()[0], 0)


if __name__ == '__main__':
    unittest.main()
