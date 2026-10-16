from tests.test_study_progress import BackendTests, backend
from fsrs import Card, State
from datetime import timedelta
import json
import sqlite3
from contextlib import closing
import copy
import unittest

class PreferenceTests(unittest.TestCase):
    setUp=BackendTests.setUp
    session=BackendTests.session
    answer=BackendTests.answer
    backup=BackendTests.backup
    restore=BackendTests.restore
    assert_error=BackendTests.assert_error
    def prefs(self, **changes):
        return self.store.dispatch('POST','/api/study/preferences',{}, {'preferences':dict(backend.DEFAULT_PREFERENCES,**changes)})
    def test_old_preferences_and_v2_backup_are_completed_without_losing_choices(self):
        old={k:backend.DEFAULT_PREFERENCES[k] for k in ['theme','fontSize','lineHeight','showIntervals','spaceAction','autoplay','ukSource','usSource','lookup','selectionLookup']}
        old['theme']='dark'
        with closing(sqlite3.connect(self.db)) as c, c:c.execute('INSERT INTO preferences VALUES (1,?)',(json.dumps(old),))
        current=self.session()['preferences']
        self.assertEqual(current['theme'],'dark');self.assertEqual(current['newOrder'],'original')
        b=self.backup();b['preferences']=old;self.restore(b)
        self.assertEqual(self.backup()['preferences'],current)
    def test_custom_steps_predict_and_save_the_same_due(self):
        self.prefs(learningSteps='2, 20',relearningSteps='5')
        first=self.session()['card'];self.assertEqual(first['intervals'][0]['seconds'],120)
        result,_=self.answer(1,card=first)
        state=self.backup()['books'][1]['cards'][0]['scheduler']
        saved=Card.from_dict(state)
        self.assertEqual(int((saved.due-self.clock()).total_seconds()),120)
    def test_new_word_order_is_stable_and_scope_is_preserved(self):
        self.store._cards['redbook']['redbook-1']['word']='zebra'
        self.store._cards['redbook']['redbook-2']['word']='apple'
        self.prefs(newOrder='alphabetical')
        self.assertEqual(self.session()['card']['id'],'redbook-2')
        self.assertIn(self.session(deck='u2')['card']['id'],['redbook-3','redbook-4'])
        self.prefs(newOrder='random')
        ids=[self.session()['card']['id'] for _ in range(4)]
        self.assertEqual(len(set(ids)),1)
        self.prefs(newOrder='original');self.assertEqual(self.session()['card']['id'],'redbook-1')
    def test_position_changes_review_new_order_without_bypassing_learning_or_limits(self):
        for i,stage in [(1,State.Review),(2,State.Learning)]:
            c=Card(card_id=i,state=stage,due=self.clock()-timedelta(minutes=1),stability=5,difficulty=5,last_review=self.clock()-timedelta(days=1))
            with closing(sqlite3.connect(self.db)) as con, con:con.execute('UPDATE cards SET scheduler_json=? WHERE book=? AND card_id=?',(json.dumps(c.to_dict()),'redbook',f'redbook-{i}'))
        self.prefs(newPosition='before')
        self.assertEqual(self.session()['card']['id'],'redbook-2')
        self.clock.advance(minutes=0)
        with closing(sqlite3.connect(self.db)) as c, c:c.execute('UPDATE cards SET scheduler_json=NULL WHERE book=? AND card_id=?',('redbook','redbook-2'))
        self.assertEqual(self.session()['card']['id'],'redbook-2')
        self.prefs(newPosition='after');self.assertEqual(self.session()['card']['id'],'redbook-1')
        self.prefs(newPosition='mixed');self.assertEqual(self.session()['card']['id'],'redbook-1')
        self.answer(3);self.assertEqual(self.session()['card']['phase'],'new')
    def test_other_tabs_cannot_grade_old_intervals_after_step_change(self):
        old=self.session()['card'];self.prefs(learningSteps='2,20')
        self.assert_error(409,lambda:self.answer(1,card=old))
        current=self.session()['card'];self.assertEqual(current['intervals'][0]['seconds'],120)
        self.assertEqual(self.backup()['books'][1]['cards'][0]['scheduler'],None)

    def test_multiple_learning_and_relearning_steps_survive_backup_and_shortening(self):
        self.prefs(learningSteps='1,10,30',relearningSteps='5,15,30')
        first=self.session()['card'];self.answer(3,card=first);self.clock.advance(minutes=10)
        self.answer(3);state=self.backup()['books'][1]['cards'][0]['scheduler']
        self.assertEqual(state['step'],2)
        self.restore(self.backup());self.assertEqual(self.backup()['books'][1]['cards'][0]['scheduler'],state)
        self.prefs(learningSteps='1',relearningSteps='5,15,30');self.restore(self.backup())
        self.clock.advance(minutes=30);self.answer(4)
        current=self.backup()['books'][1]['cards'][0]['scheduler'];self.clock.value=Card.from_dict(current).due
        self.answer(1);self.clock.advance(minutes=5);self.answer(3)
        current=self.backup()['books'][1]['cards'][0]['scheduler']
        self.assertEqual(current['state'],State.Relearning.value);self.assertEqual(current['step'],1)
        self.restore(self.backup());self.prefs(relearningSteps='5');self.restore(self.backup())
        self.assertEqual(self.backup()['books'][1]['cards'][0]['scheduler'],current)

    def test_invalid_extra_preferences_never_mutate_database(self):
        before=self.backup()
        for change in [{'learningSteps':'0,10'},{'learningSteps':'1,,10'},{'audioRate':9},{'showExamples':'false'},{'newOrder':'unexpected'},{'cardWidth':99999},{'unknown':True}]:
            self.assert_error(400,lambda:self.prefs(**change))
            self.assertEqual(self.backup(),before)

del BackendTests
