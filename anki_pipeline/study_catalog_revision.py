"""Atomic reviewed-fact revisions and their shared Anki/web presentation.

Original fields, exact bilingual chunks and complete per-sentence audit markup
are retained. Only the current sense containers and the changed reason move.
Queries and both hosts bind the compiled fields to the same active record seal.
"""
from __future__ import annotations

from copy import deepcopy
import html
import json

from . import study_catalog as c
from . import sense_frequency as sf
from .final_apkg_content import _text
from .native_example_usage import _Offsets
from .sense_groups import display_report

KEY='semantic.projections.v1'
HISTORY={'sf-ownership-history','sf-original-history-panel','sf-ownership-authority',
         'sf-pending-note','sf-ownership-pending-note','sf-archived-example',
         'sf-archived-native-example','sf-final-history','sf-inline-history',
         'sf-source-confirmation-history','sf-semantic-resolution-history','sf-catalog-revision'}


def registry(db):
    row=db.execute('select value from metadata where key=%s',(KEY,)).fetchone()
    return json.loads(row[0]) if row else {}


def analysis_ref(book,source_id):
    return book['manifest'].get('analysis_references',{}).get(source_id,
        {'book_id':book['id'],'source_card_id':source_id})


def _projection(db,book,source_id):
    ref=analysis_ref(book,source_id)
    entries=book['semantic_projections'] if 'semantic_projections' in book else registry(db)
    return entries.get(c.identity(ref['book_id'],ref['source_card_id'])),ref


def project_fields(db,book,source_id,names,fields):
    projection,ref=_projection(db,book,source_id)
    if projection is None:return fields
    active=db.execute('select record_id from analyses where book_id=%s and source_card_id=%s',
                      (ref['book_id'],ref['source_card_id'])).fetchone()
    if active is None or active[0]!=projection['record_id']:
        raise ValueError('semantic presentation and active facts have different revisions')
    result=list(fields)
    for name,object_id in projection['fields'].items():
        if name not in names:raise ValueError('semantic projection references absent note field')
        result[names.index(name)]=c.get_object(db,object_id).decode()
    return result


def project_display_fields(db,book,source_id,names,fields):
    """Both hosts group native rows; revision writers retain original proofs."""
    projection,_=_projection(db,book,source_id)
    if projection is None or 'Examples' not in projection['fields']:return fields
    record=c.get_json(db,projection['record_id'])
    origin_id=projection.get('native_grouping_origin_record_id')
    if origin_id is not None:
        from .study_catalog_ownership import validate_grouping_origin
        validate_grouping_origin(db,c.get_json(db,origin_id),record)
    elif not reviewed_ownership_origin(record):return fields
    from .study_catalog_native_groups import group_native_examples
    result=list(fields);index=names.index('Examples')
    result[index]=group_native_examples(result[index],record,projection.get('native_aliases'))
    return result


def reviewed_ownership_origin(record):
    """Follow verified source-revision ancestry to a real ownership transfer.

    Source revisions intentionally move the former transfer into one flat
    chain base instead of duplicating it on every current row. A marker alone
    cannot authorize a display rewrite; every bridge and owner is checked.
    """
    from . import sense_display as sd
    owner_keys=('book_id','card_id','word')
    for current in record['occurrences']:
        context=record;row=current;seen=set()
        while True:
            marker=(context.get('snapshot_id'),row.get('occurrence_id'))
            if marker in seen:raise ValueError('cyclic ownership display ancestry')
            seen.add(marker)
            review=row.get('semantic_review') or {}
            if not isinstance(review,dict):raise ValueError('ownership display evidence must be an object')
            display=row.get('display')
            chain=review.get('catalog_source_revision_chain')
            if isinstance(chain,dict) and all(chain.get(key)==context.get(key) for key in owner_keys):
                if not sd._source_revision_chain(display,row,context,0):
                    raise ValueError('ownership display source chain was not verified')
                context=chain['base_record']
                matches=[entry for entry in context['occurrences']
                         if entry['occurrence_id']==chain['base_occurrence_id']]
                if len(matches)!=1:raise ValueError('ownership display chain has no exact base occurrence')
                row=matches[0];continue
            prior=review.get('catalog_source_revisions')
            if isinstance(prior,list) and prior and isinstance(prior[-1],dict) and all(
                    prior[-1].get(key)==context.get(key) for key in owner_keys):
                if not sd._revised_display_source(display,row,context['definition_provenance'],context,0):
                    raise ValueError('ownership display source revision was not verified')
                context=prior[-1]['before_record'];row=prior[-1]['before_row'];continue
            if review.get('catalog_ownership_transfers'):
                # Older prototypes did not store an immutable origin binding.
                # Without an approved display bridge keep their exact former
                # presentation; new writes validate the complete origin below.
                if not isinstance(display,dict):break
                sd._transferred_display_source(display,row,context['definition_provenance'],context,0)
                return True
            break
    return False


def preflight_display_projections(db,notes):
    """Exercise the final shared host projection before a writer commits."""
    from .study_catalog_export import project_book,project_note
    books={}
    for book,note_id in sorted(set(notes)):
        if book not in books:books[book]=project_book(db,book)
        project_note(db,books[book],note_id)


def _historical(node):
    while node:
        if node.classes&HISTORY or 'data-native-ownership-history' in node.attrs:return True
        node=node.parent
    return False


def _nodes(raw,kind):
    return [n for n in _Offsets(raw,{}).root.walk() if kind in n.classes and not _historical(n)]


def _edits(raw,edits):
    end=-1
    for left,right,_ in sorted(edits):
        if left<end or not 0<=left<=right<=len(raw):raise ValueError('semantic content edits overlap')
        end=right
    result=raw
    for left,right,replacement in sorted(edits,reverse=True):result=result[:left]+replacement+result[right:]
    return result


def compile_definition(raw,before,after):
    """Repartition existing complete articles; never rebuild authored chunks.

    This revision changes assignments/reasons, not dictionary definitions, source
    text, displays, physical membership or ownership. Those have other source
    revision contracts and cannot be smuggled into a decision amendment.
    """
    if before['senses']!=after['senses']:raise ValueError('dictionary changes require a definition revision')
    old={r['occurrence_id']:r for r in before['occurrences']};new={r['occurrence_id']:r for r in after['occurrences']}
    if set(old)!=set(new):raise ValueError('decision revision cannot change physical membership')
    reports=_nodes(raw,'sf-report');articles={}
    for node in _nodes(raw,'sf-example'):
        oid=node.attrs.get('data-sf-occurrence-id')
        if oid in old:
            if oid in articles:raise ValueError('duplicate live source article')
            article=raw[node.start:node.end]
            changes=[];prior_explanations=[]
            children=_Offsets(article,{}).root.children[0].children
            if old[oid].get('broad_match')!=new[oid].get('broad_match'):
                for child in children:
                    if 'sf-reason' in child.classes and _text(article[child.opened:child.closed]).startswith('上下文仅能确认广义：'):
                        prior_explanations.append(article[child.start:child.end]);changes.append((child.start,child.end,''))
            if old[oid]['sense_id']!=new[oid]['sense_id']:
                for child in children:
                    if 'sf-dictionary-explanation' in child.classes:
                        prior_explanations.append(article[child.start:child.end]);changes.append((child.start,child.end,''))
            if old[oid]['reason']!=new[oid]['reason']:
                reasons=[n for n in children
                         if 'sf-reason' in n.classes and _text(article[n.opened:n.closed]).startswith('义项依据：')]
                if len(reasons)!=1:raise ValueError('source article has no unique current reason')
                reason=reasons[0]
                if _text(article[reason.opened:reason.closed])!='义项依据：'+old[oid]['reason']:
                    raise ValueError('source article reason differs from reviewed facts')
                changes.append((reason.opened,reason.closed,'义项依据：'+html.escape(new[oid]['reason'])))
            article=_edits(article,changes)
            if old[oid]!=new[oid]:
                audit='<details class="sf-catalog-revision"><summary>本句修订记录</summary><pre style="white-space:pre-wrap">'+html.escape(c.canonical({
                    'before_snapshot':before['snapshot_id'],'after_snapshot':after['snapshot_id'],
                    'before':{k:old[oid].get(k) for k in ('status','sense_id','reason','method','broad_match')},
                    'after':{k:new[oid].get(k) for k in ('status','sense_id','reason','method','broad_match')}}))+'</pre>'+''.join(prior_explanations)+'</details>'
                closing=article.rfind('</article>');article=article[:closing]+audit+article[closing:]
            articles[oid]=article
    if set(articles)!=set(old):raise ValueError('source Definition lacks complete live physical articles')
    view=display_report(sf.report_from_record(after));groups=view['senses'];ordinal=0;edits=[]
    for index,node in enumerate(reports):
        if node.attrs.get('data-snapshot')!=before['snapshot_id']:raise ValueError('source report has a stale active snapshot')
        meanings=[_text(raw[n.opened:n.closed]) for n in node.walk() if 'sf-meaning' in n.classes and not _historical(n)]
        local=groups[ordinal:ordinal+len(meanings)]
        normalize=lambda t:' '.join(t.split())
        if list(map(normalize,meanings))!=[normalize(s['pos']+' '+s['text']) for s in local]:
            raise ValueError('source dictionary partitions differ from certified common senses')
        subset={**view,'senses':local,'pending':view['pending'] if index==0 else [],
                'pending_count':len(view['pending']) if index==0 else 0}
        # Only generate containers here. The exact original article (including
        # all nested audit documents) replaces each temporary generated body.
        subset=deepcopy(subset)
        for row in [r for sense in subset['senses'] for r in sense['occurrences']]+subset['pending']:
            row.pop('ownership_history',None)
        generated=sf.render_report(subset)
        replacements=[]
        for article in _nodes(generated,'sf-example'):
            oid=article.attrs.get('data-sf-occurrence-id')
            if oid not in articles:raise ValueError('generated article lacks its exact source body')
            replacements.append((article.start,article.end,articles[oid]))
        generated=_edits(generated,replacements)
        extras=[]
        for child in node.children:
            # Archived diagnostics are full source evidence, not active rows.
            ids={n.attrs.get('data-sf-occurrence-id') for n in child.walk() if 'sf-example' in n.classes}
            if 'sf-pending' in child.classes and ids-set(old):
                if ids&set(old):raise ValueError('mixed live/archived pending container needs an explicit source revision')
                extras.append(raw[child.start:child.end])
            elif not child.classes&{'sf-hint','sf-sense','sf-row','sf-pending'}:
                extras.append(raw[child.start:child.end])
        if extras:
            end=generated.rfind('</div>');generated=generated[:end]+''.join(extras)+generated[end:]
        edits.append((node.start,node.end,generated));ordinal+=len(meanings)
    if ordinal!=len(groups):raise ValueError('source reports do not cover every dictionary sense')
    return _edits(raw,edits)


def amend_decision(value,*,word,physical_id,sense_id,reason,expected,backups):
    """One reviewed choice updates every analysis using that physical word.

    expected maps each affected book/card key to the current record SHA. Scope
    must be complete; a missing dictionary mapping rejects the entire change.
    """
    if not isinstance(reason,str) or not reason.strip():raise ValueError('review reason is required')
    saved=c.backup(value,backups)
    with c.connect(value) as db,c.transaction(db):
        from .study_catalog_export import require_ready,project_book,project_note
        from .study_catalog_normalize import import_analysis
        c.write_lock(db);require_ready(db)
        db.execute('select pg_advisory_xact_lock(%s)',(int(c.identity(KEY)[:15],16),))
        rows=db.execute('select distinct a.book_id,a.source_card_id,a.record_id from analyses a '
            'join words w on w.id=a.word_id join analysis_occurrences x on x.book_id=a.book_id and x.source_card_id=a.source_card_id '
            'join tokens t on t.id=x.token_id where w.surface=%s and t.physical_id=%s order by a.book_id,a.source_card_id',
            (word,physical_id)).fetchall()
        if not rows:raise ValueError('reviewed physical word is absent')
        actual={book+'/'+card:record for book,card,record in rows}
        if actual!=expected:raise ValueError('stale or incomplete cross-book revision scope')
        changes=[];projections=registry(db);all_affected=[]
        for book,card,record_id in rows:
            locked=db.execute('select record_id from analyses where book_id=%s and source_card_id=%s for update',(book,card)).fetchone()
            if locked[0]!=record_id:raise ValueError('active analysis changed during amendment')
            before=c.get_json(db,record_id);draft=deepcopy(before)
            chosen=db.execute('select ordinal from analysis_senses where book_id=%s and source_card_id=%s and sense_id=%s',
                              (book,card,sense_id)).fetchall()
            if len(chosen)!=1:raise ValueError('reviewed dictionary sense is not unique in every affected book')
            for row in draft['occurrences']:
                row['sense_index']=next((s['ordinal'] for s in draft['senses'] if s['sense_id']==row['sense_id']),None)
                if row['occurrence_id']==physical_id:
                    previous_sense=row['sense_id']
                    row.update(status='reviewed',sense_index=chosen[0][0],reason=reason,method='shared-catalog-reviewed.v1')
                    row.pop('broad_match',None);row.pop('common_sense_match',None);row.pop('matching_proposal',None)
                    row.pop('pending_category',None)
                    if previous_sense!=draft['senses'][chosen[0][0]]['sense_id'] and 'semantic_review' in row:
                        row['semantic_review'].pop('dictionary_explanation',None)
                    row.update(sf.seal_reviewed_assignment(draft,row))
            # Reissue candidate seals as well as assignment seals. The exact
            # excluded rows remain historical authority across later decisions.
            from .study_catalog_content import _prepare
            after=_prepare(draft)
            notes=db.execute('select note_id from notes where book_id=%s and source_card_id=%s',(book,card)).fetchall()
            if len(notes)!=1:raise ValueError('active semantic record needs one exact source note')
            note=project_note(db,project_book(db,book),notes[0][0],apply_runtime=False);fields=dict(zip(note['field_names'],note['fields']))
            if 'Definition' not in fields:raise ValueError('semantic record has no vocabulary Definition')
            definition=compile_definition(fields['Definition'],before,after)
            # Normalized current links are replaced, while their immutable
            # objects/decisions and complete source archives remain preserved.
            db.execute('delete from analysis_occurrences where book_id=%s and source_card_id=%s',(book,card))
            db.execute('delete from analysis_senses where book_id=%s and source_card_id=%s',(book,card))
            db.execute('delete from analyses where book_id=%s and source_card_id=%s',(book,card))
            import_analysis(db,after)
            after_id=c.put_json(db,after)
            key=c.identity(book,card)
            # A decision amendment changes this field only. Previous reviewed
            # source/ownership edits may also override Examples; reverting those
            # while keeping the new facts would split the two output hosts.
            previous=projections.get(key,{})
            projections[key]={**previous,'record_id':after_id,'fields':{**previous.get('fields',{}),
                'Definition':c.put_object(db,definition.encode())}}
            changes.append({'book_id':book,'source_card_id':card,'before':record_id,'after':after_id})
            from .study_catalog_anki import bump_content_mods
            affected=[(book,note[0]) for note in notes]
            for mapped_book,manifest_id in db.execute("select b.book_id,s.manifest_id from book_sources b join sources s on s.id=b.source_id where s.kind='book-map'"):
                refs=c.get_json(db,manifest_id).get('analysis_references',{})
                for mapped_card,ref in refs.items():
                    if (ref['book_id'],ref['source_card_id'])==(book,card):
                        affected.extend((mapped_book,n[0]) for n in db.execute('select note_id from notes where book_id=%s and source_card_id=%s',(mapped_book,mapped_card)))
            bump_content_mods(db,affected)
            all_affected.extend(affected)
        db.execute('insert into metadata values(%s,%s) on conflict(key) do update set value=excluded.value',(KEY,c.canonical(projections)))
        preflight_display_projections(db,all_affected)
        c.event(db,'amend-shared-decision',{'word':word,'physical_id':physical_id,'sense_id':sense_id,'reason':reason,'changes':changes})
    return {'changes':changes,'backup':str(saved),'physical_frequency_changed':False}
