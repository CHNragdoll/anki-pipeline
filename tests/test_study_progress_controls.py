from tests.test_study_progress import BackendTests, catalog, Clock, backend
from datetime import timedelta
import copy
import sqlite3
from contextlib import closing
from pathlib import Path
import tempfile
import unittest

class ControlsTests(unittest.TestCase):
    setUp=BackendTests.setUp
    session=BackendTests.session
    answer=BackendTests.answer
    settings=BackendTests.settings
    backup=BackendTests.backup
    restore=BackendTests.restore
    stats=BackendTests.stats
    assert_error=BackendTests.assert_error
    def action(self, action, value=None, card=None, request='tool-1', deck='all'):
        card=card or self.session()['card']
        body={'book':'redbook','deck':deck,'cardId':card['id'],'revision':card['revision'],'action':action,'requestId':request}
        if value is not None: body['value']=value
        return self.store.dispatch('POST','/api/study/card-action',{},body),body

    def test_bury_expiry_and_suspend_manual_restore_preserve_scheduler(self):
        first=self.session()['card']
        r,_=self.action('bury')
        self.assertNotEqual(r['session']['card']['id'],first['id'])
        self.assertEqual(r['card']['controls']['buriedUntil'],'2026-10-05')
        self.clock.advance(days=1)
        self.assertEqual(self.session()['card']['id'],first['id'])
        r,_=self.action('suspend',request='pause')
        self.clock.advance(days=8)
        self.assertNotEqual(self.session()['card']['id'],first['id'])
        self.action('unsuspend',card=r['card'],request='resume')
        self.assertEqual(self.session()['card']['id'],first['id'])
        self.assertEqual(self.backup()['books'][1]['cards'][0]['scheduler'],None)

    def test_action_retry_and_stale_score_do_not_double_mutate(self):
        stale=self.session()['card'];result,body=self.action('flag',4)
        revision=result['card']['revision']
        again=self.store.dispatch('POST','/api/study/card-action',{},body)
        self.assertEqual(again['card']['revision'],revision)
        self.assert_error(409,lambda:self.answer(card=stale))
        self.assert_error(409,lambda:self.action('flag',3,card=stale,request='tool-2'))
        self.assert_error(409,lambda:self.store.dispatch('POST','/api/study/card-action',{},dict(body,value=2)))

    def test_browse_original_order_filters_notes_and_scope(self):
        r,_=self.action('note','<script>plain notes</script>')
        r,_=self.action('flag',6,card=r['card'],request='flag')
        base={'book':'redbook','deck':'all'}
        data=self.store.dispatch('GET','/api/study/browse',dict(base,filter='notes',search='plain'),None)
        self.assertEqual([c['id'] for c in data['cards']],['redbook-1'])
        self.assertEqual(data['cards'][0]['controls']['note'],'<script>plain notes</script>')
        scoped=self.store.dispatch('GET','/api/study/browse',dict(base,deck='u2',filter='flagged'),None)
        self.assertEqual(scoped['total'],0)
        all_cards=self.store.dispatch('GET','/api/study/browse',base,None)
        self.assertEqual([c['id'] for c in all_cards['cards']],list(self.store._cards['redbook']))

    def test_full_backup_controls_preferences_roundtrip_and_legacy(self):
        self.answer();r,_=self.action('note','Saved note',request='note');self.action('suspend',card=r['card'],request='pause')
        prefs=dict(backend.DEFAULT_PREFERENCES,theme='dark',fontSize=24,lookup='oxford')
        self.store.dispatch('POST','/api/study/preferences',{}, {'preferences':prefs})
        value=self.backup();self.assertEqual(value['schemaVersion'],2)
        self.restore(value);restored=self.backup()
        self.assertEqual(restored['preferences'],prefs)
        self.assertEqual([c['controls'] for c in value['books'][1]['cards']],[c['controls'] for c in restored['books'][1]['cards']])
        legacy=copy.deepcopy(value);legacy.pop('preferences');legacy['schemaVersion']=1
        for b in legacy['books']:
            for c in b['cards']:c.pop('controls')
        self.restore(legacy)
        self.assertEqual(self.backup()['preferences'],backend.DEFAULT_PREFERENCES)
        self.assertEqual(self.stats()['summary']['totalReviews'],1)
        self.assertEqual(self.stats()['distribution']['suspended'],0)

    def test_rejected_preferences_and_controls_leave_db_unchanged(self):
        before=self.backup()
        self.assert_error(400,lambda:self.action('flag',8))
        self.assert_error(400,lambda:self.action('note','x'*10001))
        self.assert_error(400,lambda:self.store.dispatch('POST','/api/study/preferences',{}, {'preferences':dict(backend.DEFAULT_PREFERENCES,selectionLookup='true')}))
        bad=copy.deepcopy(before);bad['books'][0]['cards'][0]['controls']['buriedUntil']='2026-50-100'
        self.assert_error(400,lambda:self.restore(bad));self.assertEqual(self.backup(),before)

    def test_stats_time_undo_and_excluded_forecast(self):
        self.answer();self.assertEqual(self.stats()['summary']['todayTimeMs'],1234)
        self.assertEqual(self.stats()['summary']['averageTimeMs'],1234)
        self.store.dispatch('POST','/api/study/undo',{}, {'book':'redbook'})
        self.assertEqual(self.stats()['summary']['todayTimeMs'],0)
        self.answer(4);info=self.store.dispatch('GET','/api/study/card',{'book':'redbook','cardId':'redbook-1'},None)
        self.action('suspend',card=info,request='pause')
        self.assertEqual(sum(d['count'] for d in self.stats()['forecast']),0)
        self.assertEqual(self.stats()['distribution']['suspended'],1)

    def test_upgrade_automatically_backs_up_and_preserves_every_old_row(self):
        self.answer()
        with closing(sqlite3.connect(self.db)) as con, con:
            tables=['cards','reviews','settings','metadata','undo','requests']
            before={t:con.execute('SELECT * FROM '+t+' ORDER BY rowid').fetchall() for t in tables}
            con.execute('DROP TABLE card_controls');con.execute('DROP TABLE card_actions');con.execute('DROP TABLE preferences')
        backend.StudyStore(self.db,self.books,now=self.clock)
        with closing(sqlite3.connect(self.db)) as con, con:
            after={t:con.execute('SELECT * FROM '+t+' ORDER BY rowid').fetchall() for t in tables}
        self.assertEqual(before,after)
        backups=list((self.db.parent/'backups').glob('progress-before-upgrade-*'))
        self.assertEqual(len(backups),1)
        with closing(sqlite3.connect(backups[0])) as con, con:
            self.assertEqual(con.execute('SELECT COUNT(*) FROM reviews').fetchone()[0],1)

del BackendTests
if __name__=='__main__':unittest.main()
