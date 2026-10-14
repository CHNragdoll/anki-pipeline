"""Export the complete accepted presentation into identity-preserving APKGs.

Mother packages, the semantic database and sealed web artifacts are read-only.
Only the new private package collection and its media map are written.
"""
from __future__ import annotations

import argparse
import copy
from datetime import datetime
import hashlib
import html
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import sqlite3
import time
from urllib.parse import urljoin, urlsplit
import zipfile

import genanki
from anki_pipeline.final_apkg_content import extract_fields, scoped_projection
from anki_pipeline.final_apkg_history import HistoryMaterializer
from scripts.final_apkg_identity import map_existing_notes, FIELD_NAMES
from scripts.prepare_sense_frequency_records import class_aliases

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / 'output'
FINAL = WEB / 'eleven-resolution-20261014/preview-own/final-v2'
OWN = WEB / 'final-anki-20261015'
PROJECTION = WEB / 'exam-usage-policy-20261012/derived-chunk-display-projection/merge-own/candidate-v1/projection.json'
BANK = WEB / 'exam-usage-policy-20261012/shared-reading-bank-v5-own/shared-reading-bank-v5.json'
PINS = {PROJECTION:'de893f8518063d999c033854f33d1bde59ff2f6c20615ea61b89a753745af2c8',
    BANK:'af3e69641213564226f92b44c0192afc1e3bbf3cd30ac4d101885d06f6fefab5'}
SOURCE_SHA = {'2026':'a2461fc562cdc8870b13c94ab4338a1c7f1a7f10d75df1ea8eb400d60a7f746d',
    '2027':'a687a998d037c3c7b5f213c0f70378a4d8dfbe43b152e873bf00a7bada0a4512'}
ATTR = re.compile(r'''([^\s=/<>]+)(?:\s*=\s*("[^"]*"|'[^']*'|[^\s>]+))?''')


def runtime_inputs():
    return [Path(__file__), ROOT/'anki_pipeline/final_apkg_content.py',
        ROOT/'anki_pipeline/native_example_usage.py', ROOT/'scripts/prepare_sense_frequency_records.py',
        ROOT/'scripts/final_apkg_identity.py', ROOT/'anki_pipeline/final_apkg_history.py',
        FINAL/'assets/library-preview.js', ROOT/'anki_pipeline/templates/sense-frequency.css',
        ROOT/'anki_pipeline/templates/sense-frequency.js', ROOT/'scripts/lan_sha256.js',
        PROJECTION, BANK, FINAL/'preview-manifest.json',
        WEB/'library-startup-20261014/overlay-receipt-v2.json']


def capture_inputs(paths):
    return {str(path.resolve()):file_sha(path) for path in paths}


def verify_inputs(pins):
    for path,pin in pins.items():
        if file_sha(path)!=pin:raise ValueError('generation input changed: '+path)


def embedded_json(value):
    return json.dumps(value,ensure_ascii=False,separators=(',',':')).replace('<','\\u003c')


def sha(value):
    return hashlib.sha256(value).hexdigest()


def file_sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def safe_page(url):
    path = (WEB / urlsplit(html.unescape(url)).path.lstrip('/')).resolve()
    if not path.is_relative_to(WEB.resolve()) or not path.is_file():
        raise ValueError('accepted source path is absent or outside the web root: ' + str(path))
    return path


class Media:
    def __init__(self, archive, folder):
        self.original = json.loads(archive.read('media'))
        self.mapping = dict(self.original)
        self.next_media_id = max(map(int,self.mapping),default=-1)+1
        self.names = set(self.original.values())
        self.additions = {}
        self.folder = folder
        self.sources = {}
        self.evidence_assets = {}
        self.histories = HistoryMaterializer(self.read_history,evidence_renderer=self.history_evidence)

    def read_history(self,url):
        path=safe_page(url);raw=path.read_bytes();self.sources[str(path)]=sha(raw)
        return raw

    def add(self, data, suffix):
        name = '_af_' + sha(data)[:24] + suffix
        if name not in self.names:
            self.names.add(name)
            self.mapping[str(self.next_media_id)] = name
            self.next_media_id+=1
            path = self.folder / name
            path.write_bytes(data)
            self.additions[name] = path
        return name

    def history_evidence(self, original_html):
        pin=sha(original_html.encode())
        if pin in self.evidence_assets:return self.evidence_assets[pin]
        data=('window.AnkiFinalHistoryEvidence=window.AnkiFinalHistoryEvidence||{};'
            'window.AnkiFinalHistoryEvidence['+json.dumps(pin)+']='+embedded_json(original_html)+';').encode()
        name=self.add(data,'.js')
        result=('<pre data-native-history-media="'+name+'" data-native-history-sha="'+pin+'">展开后载入完整原 HTML 证据</pre>')
        self.evidence_assets[pin]=result
        return result

    def histories_inline(self, text, base_url):
        return self.histories.materialize(text,base_url=base_url)

    def references(self, text, base):
        # The accepted web viewer delayed srcdoc. Native Anki needs its actual
        # original srcdoc, which refers to the already packaged flat assets.
        def attr(match):
            key, quoted = match.groups();key=key.lower()
            if quoted[0] not in ('"',"'"):quoted='"'+html.escape(html.unescape(quoted),quote=True)+'"'
            value = html.unescape(quoted[1:-1])
            if key in ('srcdoc','data-web-etymology-srcdoc'):
                value = self.references(value,base)
                return 'srcdoc=' + quoted[0] + html.escape(value,quote=True) + quoted[0]
            url = urlsplit(value)
            if url.scheme in ('data','eudic','anki','mailto') or not value:
                return match[0]
            if key != 'src' and Path(url.path).suffix.lower() not in ('.css','.js','.png','.svg','.gif','.jpg','.woff','.woff2','.ttf'):
                if value.startswith('/'):
                    value = 'http://192.168.3.5:8771' + value
                value = re.sub(r'^http://(?:localhost|127\.0\.0\.1):(8765|8771)(?=/)',r'http://192.168.3.5:\1',value)
                return key + '=' + quoted[0] + html.escape(value,quote=True) + quoted[0]
            bare = Path(url.path).name
            if bare in self.names:
                value = bare + ('#' + url.fragment if url.fragment else '')
            elif url.scheme in ('http','https') and url.hostname not in ('localhost','127.0.0.1','192.168.3.5'):
                raise ValueError('card attempts to load external rendering media: ' + value)
            else:
                path = safe_page(urljoin(base,value)); raw = path.read_bytes()
                self.sources[str(path)] = sha(raw)
                if path.suffix.lower() in ('.html','.htm'):
                    raise ValueError('unexpected external frame instead of preserved srcdoc: ' + str(path))
                value = self.add(raw,path.suffix)
            return key + '=' + quoted[0] + html.escape(value,quote=True) + quoted[0]
        # Match only actual start-tag attributes, never apparent href/src text
        # in JavaScript, JSON evidence, comments or dictionary prose.
        edits=[]
        offsets=[0]
        offsets.extend(match.end() for match in re.finditer('\n',text))
        class References(HTMLParser):
            def handle_starttag(parser,tag,attributes):
                raw=parser.get_starttag_text();names={name for name,_ in attributes}
                allowed={'href','src','srcdoc','data-web-etymology-srcdoc','data-latex-url','data-full-paper-url'}&names
                if not allowed:return
                def actual(match):
                    return attr(match) if match[1].lower() in allowed and match[2] is not None else match[0]
                opening=re.match(r'<\s*[^\s/>]+',raw).end()
                revised=raw[:opening]+ATTR.sub(actual,raw[opening:])
                if revised!=raw:
                    line,column=parser.getpos();start=offsets[line-1]+column
                    edits.append((start,start+len(raw),revised))
            handle_startendtag=handle_starttag
        References(convert_charrefs=True).feed(text)
        pieces=[];last=0
        for start,end,revised in edits:
            pieces.extend((text[last:start],revised));last=end
        pieces.append(text[last:])
        return ''.join(pieces)


def make_runtime(models, media, projection_pin):
    composed = (FINAL / 'assets/library-preview.js').read_text()
    boundary = "(function () {\n  'use strict';\n\n  var ALL_DECKS"
    if composed.count(boundary) != 1:
        raise ValueError('accepted helper boundary changed')
    helpers = composed[:composed.index(boundary)]
    vocab = next(m for m in models.values() if [f['name'] for f in m['flds']] == list(FIELD_NAMES))
    source = vocab['tmpls'][0]['afmt']
    if 'var config=' not in source:
        # 2027 uses a different note type. The shipped 2026 decoder is the
        # common verified compact-source codec; note identities are untouched.
        with zipfile.ZipFile('/Users/apple/Downloads/2026红宝书完整版-手机词根与跳转交互修复-20261010.apkg') as z:
            db=sqlite3.connect(':memory:');db.deserialize(z.read('collection.anki2'))
            source=json.loads(db.execute('select models from col').fetchone()[0])['1552983369']['tmpls'][0]['afmt'];db.close()
    start=source.index('<script>(function()')+len('<script>')
    end=source.index('})();',source.index('var config=',start))+len('})();')
    decoder=source[start:end].replace('http://localhost:8765','http://192.168.3.5:8765')
    codec=json.JSONDecoder().raw_decode(source[source.index('var config=',start)+len('var config='):])[0]
    bank_raw=BANK.read_text()
    bank_js='if(!window.AnkiFinalReadingMetadata)window.AnkiFinalReadingMetadata=JSON.parse('+json.dumps(bank_raw)+');\n'
    bootstrap=r'''
window.AnkiFinalApkgDispose=function(){
  window.__ankiFinalApkgGeneration=(window.__ankiFinalApkgGeneration||0)+1;
  var handles=window.__ankiFinalApkgHandles||[];window.__ankiFinalApkgHandles=[];
  handles.reverse().forEach(function(h){h.dispose();});
};
window.AnkiFinalApkgHydrate=async function(){
  window.AnkiFinalApkgDispose();
  var version=window.__ankiFinalApkgGeneration;
  var payload=document.querySelector('script.anki-final-reviewed-data');if(!payload)return;
  var alive=function(){return version===window.__ankiFinalApkgGeneration&&document.contains(payload);};
  var keep=function(h){window.__ankiFinalApkgHandles.push(h);return h;};
  document.querySelectorAll('.vocab-card').forEach(function(el){el.classList.add('rb-compact-note');});
  var status=document.createElement('div');status.className='anki-final-status';status.setAttribute('role','status');
  payload.before(status);status.textContent='正在核验本卡细块…';
  try{
    var data=JSON.parse(payload.textContent);
    var onHistory=async function(event){
      var detail=event.target;if(!detail.matches||!detail.matches('details[open]'))return;
      var pre=detail.querySelector(':scope>pre[data-native-history-media]');
      if(!pre||pre.dataset.nativeHistoryLoading)return;
      pre.dataset.nativeHistoryLoading='true';
      try{
        var name=pre.dataset.nativeHistoryMedia,pin=pre.dataset.nativeHistorySha;
        if(!/^_af_[0-9a-f]{24}\.js$/.test(name)||!/^[0-9a-f]{64}$/.test(pin))throw Error('证据媒体标识无效');
        if(!(window.AnkiFinalHistoryEvidence||{})[pin])await new Promise(function(resolve,reject){
          var script=document.createElement('script');script.src=name;
          script.onload=function(){script.remove();resolve();};script.onerror=function(){script.remove();reject(Error('本地证据媒体无法载入'));};document.head.append(script);
        });
        var raw=(window.AnkiFinalHistoryEvidence||{})[pin];if(typeof raw!=='string')throw Error('证据内容缺失');
        var bytes=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(raw));
        var actual=Array.from(new Uint8Array(bytes),function(b){return b.toString(16).padStart(2,'0');}).join('');
        if(actual!==pin)throw Error('完整证据校验失败');if(alive()&&document.contains(pre))pre.textContent=raw;
      }catch(error){if(alive()&&document.contains(pre)){pre.textContent='证据载入失败：'+String(error.message||error);delete pre.dataset.nativeHistoryLoading;}}
    };
    document.addEventListener('toggle',onHistory,true);
    keep({dispose:function(){document.removeEventListener('toggle',onHistory,true);}});
    keep(window.AnkiFineChunkRuntime.install(document));
    var token=await window.AnkiReviewedChunkProjection.prepare(data);if(!alive())return;
    var projected=keep(window.AnkiReviewedChunkProjection.install(document,token,{isCurrent:alive}));
    if(projected.stats().errors.length)throw Error('本卡细块核验失败');
    var bank=keep(window.AnkiSharedReadingBankRuntime.install(document,window.AnkiFinalReadingMetadata));
    await bank.ready;if(!alive())return;
    keep(window.AnkiSameSenseGroupRuntime.install(document));
    keep(window.AnkiResidualReviewedChunkRuntime.install(document));
    status.remove();payload.setAttribute('data-native-state','ready');
  }catch(error){if(alive()){status.textContent='本卡细块核验失败：'+String(error.message||error);payload.setAttribute('data-native-state','failed');}}
};
'''
    fallback=(ROOT/'scripts/lan_sha256.js').read_text()
    js=decoder+'\n'+fallback+'\n'+bank_js+helpers+'\n'+(ROOT/'anki_pipeline/templates/sense-frequency.js').read_text()+'\n'+bootstrap
    name=media.add(js.encode(),'.js')
    css=(ROOT/'anki_pipeline/templates/sense-frequency.css').read_text()+'''\n
.anki-final-status{font-size:12px;color:#63718a;padding:.4rem 0}
.sf-inline-history{margin:.7rem 0;overflow-wrap:anywhere}.sf-inline-history pre{white-space:pre-wrap;overflow-wrap:anywhere}
.sf-report .sf-example,.sf-report .sf-panel{min-width:0;max-width:100%}
'''
    css_name=media.add(css.encode(),'.css')
    for model in models.values():
        if [f['name'] for f in model['flds']] != list(FIELD_NAMES):continue
        model['mod']=max(model['mod']+1,int(time.time()))
        # The accepted field extractor expands the compact class names. Keep
        # the original CSS for legacy front fields and add equivalent rules for
        # the exact canonical class map shipped in the original source codec.
        canonical_css=re.sub(r'\.(_r\d+)\b',lambda m:'.'+codec['classes'].get(m[1],m[1]),model['css'])
        model['css']+='\n'+canonical_css+'\n'+css
        for template in model['tmpls']:
            template['qfmt']+='<script>if(window.AnkiFinalApkgDispose)window.AnkiFinalApkgDispose();</script>'
            template['afmt']+='\n<script src="'+name+'"></script><script>window.AnkiFinalApkgHydrate();</script>'
    return {'js':name,'css':css_name,'js_sha256':sha(js.encode()),'css_sha256':sha(css.encode()),
        'helper_source_sha256':sha(composed.encode()),'projection_sha256':projection_pin}


def build(year):
    input_pins=capture_inputs(runtime_inputs())
    book='redbook' if year=='2026' else 'redbook2027'
    folder=OWN/year;folder.mkdir(parents=True,exist_ok=False)
    media_folder=folder/'new-media';media_folder.mkdir()
    source=Path('/Users/apple/Downloads')/f'{year}红宝书完整版-手机词根与跳转交互修复-20261010.apkg'
    if file_sha(source)!=SOURCE_SHA[year]:raise ValueError('mother package hash changed')
    catalog_raw=(FINAL/book/'catalog.json').read_bytes();catalog=json.loads(catalog_raw)
    for path,pin in PINS.items():
        if file_sha(path)!=pin:raise ValueError('accepted sidecar hash changed')
    projection=json.loads(PROJECTION.read_text())
    pages={};aliases={};proofs=[];now=int(time.time())
    before=sqlite3.connect(':memory:')
    with zipfile.ZipFile(source) as archive:
        before.deserialize(archive.read('collection.anki2'))
        identities=map_existing_notes(before,catalog)
        dbfile=folder/'collection.anki2';after=sqlite3.connect(dbfile);before.backup(after)
        models=json.loads(before.execute('select models from col').fetchone()[0]);media=Media(archive,media_folder)
        runtime=make_runtime(models,media,PINS[PROJECTION])
        for index,card in enumerate(catalog['cards']):
            path=safe_page(card['previewUrl']);raw=path.read_bytes();page=raw.decode();pages[str(path)]=sha(raw)
            base=re.search(r'<base\s+href="([^"]+)"',page)
            base_url=html.unescape(base[1]) if base else card['previewUrl']
            version=safe_page(base_url).parent.parent
            if version not in aliases:
                assets=list((version/'assets').glob('*.js'))
                media.sources.update(capture_inputs(assets))
                aliases[version]=class_aliases(version)
            fields=extract_fields(page,aliases[version])
            subset=scoped_projection(fields,projection)
            if card['id'] in identities:
                original=identities[card['id']];values=original['flds'].split('\x1f');nid=original['nid']
            else:
                original=identities.supplemental_destinations[card['id']]
                values=['']*len(FIELD_NAMES);values[0]=html.escape(card['word']);values[8]='校勘补充词条（非原书新增学习词，默认停学）'
                nid=2200000000000+int(sha((book+card['id']).encode())[:12],16)%10000000000
            for key,value in fields.items():
                values[FIELD_NAMES.index(key)]=media.references(media.histories_inline(value,base_url),base_url)
            data=embedded_json(subset)
            values[2]+='<script class="anki-final-reviewed-data" type="application/json">'+data+'</script>'
            flds='\x1f'.join(values)
            if card['id'] in identities:
                after.execute('update notes set flds=?,mod=?,usn=-1 where id=?',(flds,max(now,original['note_row'][3]+1),nid))
            else:
                guid=genanki.guid_for('anki-final-supplement-v1',book,card['id'])
                mid=original['mid'];did=original['source_deck_id']
                after.execute('insert into notes values(?,?,?,?,?,?,?,?,?,?,?)',(nid,guid,mid,now,-1,' 校勘补充 ',flds,card['word'],int(sha(card['word'].encode())[:8],16),0,''))
                after.execute('insert into cards values(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(nid+100000000000,nid,did,0,now,-1,0,-1,index+1,0,2500,0,0,0,0,0,0,''))
            proofs.append({'card_id':card['id'],'nid':nid,'word':card['word'],'page_sha256':sha(raw),'current_fields_sha256':sha(flds.encode()),'projection_records':len(subset['records'])})
            if (index+1)%250==0:print(json.dumps({'book':year,'stage':'fields','done':index+1,'total':len(catalog['cards']),'elapsed':round(time.time()-now)},ensure_ascii=False),flush=True)
        # Preserve the original guide and add the now-current policy and counts.
        for guide in identities.source_guide_notes:
            old=guide['flds'].split('\x1f')
            old[2]+='<section><h2>2026-10-15 最新版统计与校勘说明</h2><p>完形填空只统计填回正确答案后的正文；阅读保留全部选项，并区分正确答案与匹配来源。同段同义合并展示，实际出现次数分别统计。转归说明完整保留在对应句内。唯一来源结构异常 as 明确标记。新增 deep-rooted、teem 为校勘查阅词条，默认停学。</p></section>'
            after.execute('update notes set flds=?,mod=?,usn=-1 where id=?',('\x1f'.join(old),now+1,guide['nid']))
        after.execute('update col set models=?,mod=max(mod+1,?),usn=-1',(json.dumps(models,ensure_ascii=False),now*1000));after.commit()
        expected=len(catalog['cards'])+len(identities.source_guide_notes)
        assert after.execute('select count(*) from notes').fetchone()[0]==expected
        assert after.execute('select count(*) from cards').fetchone()[0]==expected
        assert after.execute('pragma integrity_check').fetchone()[0]=='ok'
        original_cards=before.execute('select * from cards order by id').fetchall()
        for row in original_cards:assert after.execute('select * from cards where id=?',(row[0],)).fetchone()==row
        for table in ('revlog','graves'):assert before.execute(f'select * from {table} order by 1').fetchall()==after.execute(f'select * from {table} order by 1').fetchall()
        for key,original in identities.items():
            assert after.execute('select guid,mid from notes where id=?',(original['nid'],)).fetchone()==(original['guid'],original['mid'])
        after.close()
        target=OWN/f'{year}红宝书完整版-最新释义校勘与chunk-20261015.apkg';staged=folder/'package.tmp.apkg'
        with zipfile.ZipFile(staged,'x',compression=zipfile.ZIP_DEFLATED,compresslevel=1) as package:
            package.write(dbfile,'collection.anki2')
            # Copy old members in bounded chunks, preserving their uncompressed
            # bytes and names. No recording is regenerated or transcoded.
            for info in archive.infolist():
                if info.filename in ('collection.anki2','media'):continue
                copied=copy.copy(info)
                with archive.open(info) as incoming,package.open(copied,'w') as outgoing:
                    while chunk:=incoming.read(1024*1024):outgoing.write(chunk)
            inverse={v:k for k,v in media.mapping.items()}
            for name,path in media.additions.items():package.write(path,inverse[name])
            package.writestr('media',json.dumps(media.mapping,ensure_ascii=False).encode())
        assert file_sha(source)==SOURCE_SHA[year]
        for path,pin in pages.items():assert file_sha(path)==pin
        for path,pin in media.sources.items():assert file_sha(path)==pin
        assert sha((FINAL/book/'catalog.json').read_bytes())==sha(catalog_raw)
        verify_inputs(input_pins)
        os.replace(staged,target)
        report={'schema':'final-full-apkg.v1','year':year,'output':str(target),'bytes':target.stat().st_size,'sha256':file_sha(target),'source':str(source),'source_sha256':SOURCE_SHA[year],
            'cards':expected,'vocabulary_cards':len(catalog['cards']),'guides':len(identities.source_guide_notes),'existing_identities_and_card_schedules_preserved':True,
            'original_media_items':len(media.original),'new_media_items':len(media.additions),'original_audio_reencoded':False,'runtime':runtime,
            'source_pages':len(pages),'source_catalog_sha256':sha(catalog_raw),'source_database_writes':False,'supplemental_cards_suspended':2,'native_import_verified':False,'phone_verified':False,'generation_input_pins':input_pins}
        (folder/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
        (folder/'card-proofs.jsonl').write_text(''.join(json.dumps(p,ensure_ascii=False)+'\n'for p in proofs))
        (folder/'source-pins.json').write_text(json.dumps({**pages,**media.sources},indent=2)+'\n')
        print(json.dumps(report,ensure_ascii=False),flush=True)
        return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--year',choices=['2026','2027'],required=True)
    build(parser.parse_args().year)
