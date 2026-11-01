"""One-time native deck moves using exact note GUIDs and existing deck names.

The optional desktop helper is deliberately separate from package generation:
Anki preserves deck placement for existing cards when importing an APKG update.
"""
from collections import defaultdict


def plan_moves(col, mapping):
    if not mapping:
        raise ValueError('empty native unit mapping')
    rows=col.db.all('SELECT c.id,c.did,c.odid,n.guid FROM cards c JOIN notes n ON n.id=c.nid WHERE n.guid IN ('+','.join('?' for _ in mapping)+')',*mapping)
    found=defaultdict(list)
    for cid,did,odid,guid in rows:found[guid].append((cid,did,odid))
    moves=defaultdict(list);skipped=[];already=0
    for guid,entry in mapping.items():
        values=found.get(guid,[])
        if len(values)!=1:
            skipped.append(guid);continue
        cid,did,odid=values[0];current=col.decks.name(did)
        if current==entry['to']:already+=1;continue
        if odid or current!=entry['from']:
            skipped.append(guid);continue
        target=col.decks.by_name(entry['to'])
        if target is None:
            raise ValueError('Import the new APKG before organizing existing cards')
        moves[target['id']].append(cid)
    return {'moves':dict(moves),'already':already,'skipped':skipped}


def apply_moves(col, plan):
    """One user-undoable action. Only reviewed, explicitly planned cards move."""
    if not plan['moves']:return 0
    label='按题型整理真题子牌组'
    undo=col.add_custom_undo_entry(label);moved=0
    try:
        for did,cards in plan['moves'].items():
            col.set_deck(cards,did);col.merge_undo_entries(undo);moved+=len(cards)
    except Exception:
        if col.undo_status().undo==label:col.undo()
        raise
    return moved
