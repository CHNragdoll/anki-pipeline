"""Read-only identity reconciliation for the accepted two RedBook packages.

Match the complete word/category/lesson/position joint key. Preserve actual
note GUIDs, model IDs and card rows; 2027 web deck IDs are presentation aliases.
"""
from __future__ import annotations
from collections import defaultdict
import html
import json
import re
import genanki

FIELD_NAMES=('Word','Phonetic','Definition','SimpleDefinition','Level','WordForms','Audio','Examples','Meta','Note')
PROFILES={
 'redbook':{'source_root':'2026考研英语词汇红宝书考研英语（必考词+基础词+超纲词）真题例句版',
     'catalog_roots':['2026考研英语词汇红宝书考研英语（必考词+基础词+超纲词）真题例句版'],
     'vocab_models':[1552983369],'guide_model':193620261},
 'redbook2027':{'source_root':'2027考研英语红宝书（必考词+基础词+超纲词）真题例句版',
     'catalog_roots':['2027考研英语红宝书','2027考研英语红宝书（必考词+基础词+超纲词）真题例句版'],
     'vocab_models':[267202710,267202712],'guide_model':267202711},
}
_CATEGORIES={'01 必考词':'必考词','02 基础词':'基础词','03 超纲词':'超纲词',
    '必考词':'必考词','基础词':'基础词','超纲词':'超纲词'}


def require(condition,message):
    if not condition:raise ValueError(message)


def _rows(connection,sql):
    cursor=connection.execute(sql);names=[v[0] for v in cursor.description]
    return [(dict(zip(names,row)),tuple(row)) for row in cursor]


def _lesson(value):
    require(isinstance(value,str) and value and value==value.strip(), 'exact nonempty lesson required')
    # The shipped 2026 Meta uses Unit 1 while its deck uses Unit 01. Only
    # numeric zero-padding changes; all suffix wording and punctuation stay.
    return re.sub(r'^Unit (0*[1-9][0-9]*)',lambda m:'Unit '+str(int(m[1])),value)


def _deck(value,book,*,source):
    require(isinstance(value,str), 'deck name required')
    parts=value.split('::');profile=PROFILES[book]
    require(len(parts)==3 and parts[0] in ([profile['source_root']] if source else profile['catalog_roots']), 'source/catalog book deck differs')
    require(parts[1] in _CATEGORIES, 'unrecognized exact deck category')
    return _CATEGORIES[parts[1]],_lesson(parts[2])


def _catalog_key(entry,book):
    require(all(isinstance(entry.get(k),str) and entry[k] for k in ('id','word','unit','lesson','position','deckId','deckName')), 'complete catalog identity required')
    require(re.fullmatch(r'[a-f0-9]{64}',entry['id']) is not None, 'exact source CardID required')
    category,lesson=_deck(entry['deckName'],book,source=False)
    require(entry['unit'] in _CATEGORIES and _CATEGORIES[entry['unit']]==category and _lesson(entry['lesson'])==lesson, 'catalog metadata/deck identity differs')
    return category,lesson,entry['position'],entry['word']


def _meta_key(meta,word,deck_key,book):
    meta=html.unescape(meta);parts=meta.rsplit(' ➫ ',1)
    require(len(parts)==2 and re.fullmatch(r'[1-9][0-9]*',parts[1]) is not None, 'exact source Meta position required')
    head,position=parts;category,lesson=deck_key
    actual_category=next((c for c in ('必考词','基础词','超纲词') if head.startswith(c+' ')),None)
    if actual_category:
        actual_lesson=head[len(actual_category)+1:]
        require(actual_category==category, 'source Meta category differs from deck')
    else:
        require(book=='redbook' and category=='基础词' and head.startswith('Unit 31 简单基础词'), 'unrecognized category-free source Meta')
        actual_lesson=head
    require(_lesson(actual_lesson)==lesson, 'source Meta lesson differs from deck')
    return category,lesson,position,word


class IdentityMap(dict):
    """CardID -> original note descriptor, plus separately declared new entries."""
    def __init__(self,book):
        super().__init__();self.book_id=book
        self.supplemental_catalog_entries=[];self.supplemental_destinations={};self.source_guide_notes=[]
        self.deck_aliases={};self.summary={}


def map_existing_notes(connection,catalog):
    """SELECT only. Reject partial coverage, collisions and guessed identities.

Each value includes nid/guid/mid/flds and exact original note_row/card_rows.
The return value is a dict; supplemental_catalog_entries, their bound original
supplemental_destinations, source_guide_notes and summary are attributes.
"""
    require(isinstance(catalog,dict) and isinstance(catalog.get('cards'),list) and catalog['cards'], 'complete nonempty catalog required')
    roots={e.get('deckName','').split('::')[0] for e in catalog['cards']}
    choices=[book for book,p in PROFILES.items() if roots and roots<=set(p['catalog_roots'])]
    require(len(choices)==1, 'exact single catalog book required')
    book=choices[0];profile=PROFILES[book];result=IdentityMap(book)
    col=connection.execute('SELECT models,decks FROM col').fetchall();require(len(col)==1, 'unique source collection required')
    models,decks=map(json.loads,col[0]);card_rows=defaultdict(list)
    for card,raw in _rows(connection,'SELECT * FROM cards ORDER BY id'):
        card_rows[card['nid']].append((card,raw))
    notes=_rows(connection,'SELECT * FROM notes ORDER BY id');source={};seen_guids=set();source_ids=set()
    for note,raw in notes:
        require(note['guid'] not in seen_guids, 'duplicate source GUID');seen_guids.add(note['guid'])
        require(str(note['mid']) in models, 'source model missing')
        names=[f['name'] for f in models[str(note['mid'])]['flds']]
        fields=note['flds'].split('\x1f');require(len(fields)==len(names), 'source field arity differs')
        descriptor={**note,'nid':note['id'],'note_row':raw,'note_columns':tuple(note),
            'card_rows':[r for _,r in card_rows[note['id']]],'model_fields':names}
        if names==['Title','Overview','Guide']:
            require(note['mid']==profile['guide_model'], 'guide source model differs from book')
            result.source_guide_notes.append(descriptor);continue
        require(note['mid'] in profile['vocab_models'] and tuple(names[:10])==FIELD_NAMES
            and names[10:] in ([],['SenseReport']), 'vocabulary source model/schema differs from book')
        require(len(card_rows[note['id']])==1 and card_rows[note['id']][0][0]['ord']==0, 'source vocabulary needs its single original card')
        card=card_rows[note['id']][0][0];did=str(card['did']);require(did in decks, 'source card deck missing')
        word=html.unescape(fields[0]);require(html.unescape(str(note['sfld']))==word, 'source Word/sort field differs')
        deck_key=_deck(decks[did]['name'],book,source=True)
        key=_meta_key(fields[8],word,deck_key,book)
        require(key not in source, 'duplicate source metadata/deck/word identity')
        descriptor.update(source_deck_id=did,source_deck_name=decks[did]['name'],identity_key=key,word=word)
        source[key]=descriptor;source_ids.add(note['id'])
    entries={};seen_keys=set();seen_nids=set()
    for entry in catalog['cards']:
        key=_catalog_key(entry,book);cid=entry['id']
        require(cid not in entries and key not in seen_keys, 'duplicate catalog identity');entries[cid]=entry;seen_keys.add(key)
        if entry.get('supplemental_lexeme') is True:
            require(entry.get('original_learning_card_created') is False and key not in source, 'supplement cannot overwrite an existing note')
            result.supplemental_catalog_entries.append(entry);continue
        require(key in source, 'catalog has no exact source identity: '+entry['word'])
        note=source[key];require(note['nid'] not in seen_nids, 'two catalog cards map to one source note')
        if book=='redbook':
            require(entry['deckId']==note['source_deck_id'], '2026 exact deck ID differs')
            require(note['guid']==genanki.guid_for('anki-rebuild-card-v1',cid), '2026 actual GUID differs from original CardID')
        else:
            require(note['nid']==1962027000000+int(entry['position']), '2027 original positional note identity differs')
        result[cid]=note;seen_nids.add(note['nid'])
        alias=result.deck_aliases.setdefault(entry['deckId'],note['source_deck_id'])
        require(alias==note['source_deck_id'], 'catalog deck alias resolves to multiple source decks')
    require(seen_nids==source_ids, 'catalog does not cover every existing source vocabulary note')
    for entry in result.supplemental_catalog_entries:
        association=entry.get('supplemental_book_unit_association',{})
        origin=entries.get(association.get('source_card_id'))
        require(origin is not None and origin['id'] in result and association.get('book_id')==book
            and association.get('association_kind')=='source-confirmation-supplement; not an original wordbook membership assertion', 'supplement original source lineage absent')
        require(association.get('source_word')==origin['word'] and association.get('original_position')==origin['position']
            and entry['position']==origin['position']+'-校勘' and association.get('original_lesson')==origin['lesson']
            and association.get('original_deck_id')==origin['deckId']==entry['deckId']
            and association.get('original_deck_name')==origin['deckName']==entry['deckName']
            and _catalog_key(entry,book)[:2]==_catalog_key(origin,book)[:2], 'supplement original metadata/deck/word differs')
        result.supplemental_destinations[entry['id']]=result[origin['id']]
    result.summary={'book_id':book,'mapped':len(result),'supplemental':len(result.supplemental_catalog_entries),
        'source_guides':len(result.source_guide_notes),'source_notes':len(notes),'source_vocabulary':len(source),
        'all_existing_note_id_guid_mid_preserved':True,'database_writes':0}
    return result
