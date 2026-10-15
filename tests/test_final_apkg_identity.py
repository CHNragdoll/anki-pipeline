"""Read-only package identities must match complete source metadata."""
import json
import sqlite3
import unittest
import genanki

from scripts.final_apkg_identity import map_existing_notes, FIELD_NAMES, PROFILES


def fixture(book='redbook'):
    profile=PROFILES[book];db=sqlite3.connect(':memory:')
    db.executescript('CREATE TABLE col(models TEXT,decks TEXT); CREATE TABLE notes(id INTEGER PRIMARY KEY,guid TEXT,mid INTEGER,flds TEXT,sfld TEXT); CREATE TABLE cards(id INTEGER PRIMARY KEY,nid INTEGER,did INTEGER,ord INTEGER,due INTEGER);')
    source_root=profile['source_root'];cat_root=profile['catalog_roots'][0]
    models={str(profile['vocab_models'][0]):{'flds':[{'name':v,'ord':n} for n,v in enumerate(FIELD_NAMES)]},
        str(profile['guide_model']):{'flds':[{'name':v,'ord':n} for n,v in enumerate(['Title','Overview','Guide'])]}}
    decks={'1':{'name':'Default'},'20':{'name':source_root+'::01 必考词::Unit 01'},'21':{'name':source_root+'::导读'}}
    db.execute('INSERT INTO col VALUES(?,?)',(json.dumps(models),json.dumps(decks)))
    cid='a'*64;nid=1 if book=='redbook' else 1962027000001
    guid=genanki.guid_for('anki-rebuild-card-v1',cid) if book=='redbook' else 'original-2027-guid'
    fields=['remote','','native','','','','audio','','必考词 Unit 1 ➫ 1','user note']
    db.execute('INSERT INTO notes VALUES(?,?,?,?,?)',(nid,guid,profile['vocab_models'][0],'\x1f'.join(fields),'remote'))
    db.execute('INSERT INTO cards VALUES(?,?,?,?,?)',(30,nid,20,0,10))
    db.execute('INSERT INTO notes VALUES(?,?,?,?,?)',(2,'guide-guid',profile['guide_model'],'title\x1foverview\x1fguide','title'))
    db.execute('INSERT INTO cards VALUES(?,?,?,?,?)',(31,2,21,0,11));db.commit()
    card={'id':cid,'word':'remote','unit':'01 必考词' if book=='redbook' else '必考词','lesson':'Unit 01',
        'position':'1','deckId':'20' if book=='redbook' else '999','deckName':cat_root+'::'+('01 必考词' if book=='redbook' else '必考词')+'::Unit 01'}
    return db,{'cards':[card]},card,nid,guid


class PackageIdentityTests(unittest.TestCase):
    def test_two_profiles_preserve_actual_guid_and_do_not_write(self):
        for book in PROFILES:
            with self.subTest(book=book):
                db,cat,card,nid,guid=fixture(book);self.addCleanup(db.close)
                changes=db.total_changes;before=list(db.execute('SELECT * FROM notes'));result=map_existing_notes(db,cat)
                self.assertEqual(result[card['id']]['nid'],nid);self.assertEqual(result[card['id']]['guid'],guid)
                self.assertEqual(result.summary['mapped'],1);self.assertEqual(len(result.source_guide_notes),1)
                self.assertEqual(db.total_changes,changes);self.assertEqual(list(db.execute('SELECT * FROM notes')),before)

    def test_same_word_with_wrong_meta_or_deck_rejected(self):
        for field,value in [('position','2'),('lesson','Unit 02'),('unit','02 基础词')]:
            db,cat,card,_,_=fixture();self.addCleanup(db.close);card[field]=value
            with self.assertRaises(ValueError):map_existing_notes(db,cat)

    def test_wrong_2026_guid_and_2027_nid_rejected(self):
        db,cat,card,nid,_=fixture();self.addCleanup(db.close);db.execute('UPDATE notes SET guid=? WHERE id=?',('wrong-guid',nid))
        with self.assertRaisesRegex(ValueError,'GUID'):map_existing_notes(db,cat)
        db,cat,card,nid,_=fixture('redbook2027');self.addCleanup(db.close)
        db.execute('UPDATE notes SET id=id+5 WHERE id=?',(nid,));db.execute('UPDATE cards SET nid=nid+5 WHERE nid=?',(nid,))
        with self.assertRaisesRegex(ValueError,'positional note identity'):map_existing_notes(db,cat)

    def test_unknown_missing_card_not_treated_as_supplement(self):
        db,cat,card,_,_=fixture();self.addCleanup(db.close);card['word']='new word'
        with self.assertRaisesRegex(ValueError,'exact source identity'):map_existing_notes(db,cat)

    def test_duplicate_catalog_or_source_key_rejected(self):
        db,cat,card,_,_=fixture();self.addCleanup(db.close);cat['cards'].append(dict(card))
        with self.assertRaisesRegex(ValueError,'duplicate catalog'):map_existing_notes(db,cat)
        db,cat,card,nid,_=fixture();self.addCleanup(db.close);row=db.execute('SELECT * FROM notes WHERE id=?',(nid,)).fetchone()
        db.execute('INSERT INTO notes VALUES(?,?,?,?,?)',(4,'other-guid',row[2],row[3],row[4]));db.execute('INSERT INTO cards VALUES(?,?,?,?,?)',(40,4,20,0,1))
        with self.assertRaisesRegex(ValueError,'duplicate source'):map_existing_notes(db,cat)

    def test_declared_supplement_binds_original_existing_note(self):
        db,cat,card,nid,_=fixture();self.addCleanup(db.close)
        new={**card,'id':'b'*64,'word':'teem','position':'1-校勘','supplemental_lexeme':True,'original_learning_card_created':False,
            'supplemental_book_unit_association':{'association_kind':'source-confirmation-supplement; not an original wordbook membership assertion',
                'book_id':'redbook','source_card_id':card['id'],'source_word':'remote','original_position':'1',
                'original_lesson':card['lesson'],'original_deck_id':card['deckId'],'original_deck_name':card['deckName']}}
        cat['cards'].append(new);result=map_existing_notes(db,cat)
        self.assertEqual(len(result.supplemental_catalog_entries),1)
        self.assertEqual(result.supplemental_destinations[new['id']]['nid'],nid)
        new['supplemental_book_unit_association']['source_word']='wrong'
        with self.assertRaisesRegex(ValueError,'supplement original'):map_existing_notes(db,cat)

    def test_unknown_source_vocab_or_cross_book_rejected(self):
        db,cat,card,_,_=fixture();self.addCleanup(db.close);cat['cards']=[]
        with self.assertRaises(ValueError):map_existing_notes(db,cat)
        db,cat,card,_,_=fixture();self.addCleanup(db.close)
        card['deckName']=PROFILES['redbook2027']['catalog_roots'][0]+'::必考词::Unit 01'
        with self.assertRaisesRegex(ValueError,'model'):map_existing_notes(db,cat)


if __name__=='__main__':unittest.main()
