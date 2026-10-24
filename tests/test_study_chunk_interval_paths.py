"""Local representation ledgers against small, independently parsed HTML ASTs."""
import copy
import gzip
import hashlib
import json
from pathlib import Path
import subprocess
import shutil
import unittest

from anki_pipeline import study_chunk_intervals as intervals
from anki_pipeline import study_chunk_interval_paths as paths
from tests import test_study_chunk_intervals as compiler_tests
example,sha=compiler_tests.example,compiler_tests.sha


def packed(value):return json.dumps(value,ensure_ascii=False,separators=(',',':')).encode()


def tiny_source():
    return (b'<div class="examples-section"><ol><li class="example-card" data-study-compiled-key="r">'
      b'<span class="en">pre <span class="card-chunk" data-chunk-side="en" data-chunk-ids="0">A</span> '
      b'<em data-study-compiled-key="k">kept</em><a class="sentence-jump" href="https://source.invalid/" '
      b'data-latex-url="https://source.invalid/" data-reader="latex"></a></span>'
      b'<span class="zh">'+ '甲'.encode()+b'</span></li></ol></div>')


def tiny_profile(raw):
    region={'selector':'.examples-section','ordinal':0,'total':1,'rootPath':[0,0]}
    return {'schema':'study-compiled-card-interactions.v1','version':1,'filter_mode':'host-after-authored-filter',
      'residual_mode':'original-listener','bindings':{'derivedHTMLSha256':sha(raw)},
      'nodeBindings':[
       {'key':'r','rootKey':'r','tag':'LI','namespace':'http://www.w3.org/1999/xhtml','region':region,
        'relativePath':[],'requiredAttrs':[['class','example-card'],['data-study-compiled-key','r']],
        'logicalRoot':{'kind':'native-source','id':json.dumps([None,'https://source.invalid/',None],separators=(',',':'))},
        'roles':['logical-root'],'exactText':'pre A kept甲'},
       {'key':'k','rootKey':'r','tag':'EM','namespace':'http://www.w3.org/1999/xhtml','region':region,
        'relativePath':[0,3],'requiredAttrs':[['data-study-compiled-key','k']],
        'logicalRoot':{'kind':'native-source','id':json.dumps([None,'https://source.invalid/',None],separators=(',',':'))},
        'roles':['kept-node'],'exactText':'kept'}],
      'readerLinks':[{'rootKey':'r','relativePath':[0,4],
          'immutableAttrs':[['class','sentence-jump'],['data-latex-url','https://source.invalid/'],['data-reader','latex']],
          'baseline':{'href':'https://source.invalid/','title':None,'disabled':None}}],
      'panels':[],'groups':[],'bankRecords':[],'projectionWrappers':[],'residualWrappers':[]}


def tiny_compile(raw):
    binding=intervals.SentenceBinding('sentence',0,example('pre A kept','甲',[([4,5],[[0,1]])]),
                                    english_class='en',chinese_class='zh')
    return intervals.compile_html(raw,[binding],expected_source_sha256=sha(raw),css_sha256='f'*64,
                                  plain_chunks_are_interaction_only=True)


def forged_edits(raw, built, additions, *, remove=()):
    """Re-pin a reversible archive; this deliberately grants no edit authority."""
    profile=copy.deepcopy(built.profile);lexemes=profile['lexemes']
    rows=[(at,lexemes[before].encode(),lexemes[after].encode())
          for at,_,before,after in profile['edits']if at not in remove]
    rows.extend(additions);parts=[];cursor=delta=0;edits=[]
    def index(raw):
        text=raw.decode()
        if text not in lexemes:lexemes.append(text)
        return lexemes.index(text)
    for at,before,after in sorted(rows):
        assert at>=cursor and raw[at:at+len(before)]==before
        parts.extend((raw[cursor:at],after));edits.append([at,at+delta,index(before),index(after)])
        delta+=len(after)-len(before);cursor=at+len(before)
    parts.append(raw[cursor:]);compact=b''.join(parts)
    profile.update(edits=edits,compact_sha256=sha(compact),compact_bytes=len(compact))
    return intervals.CompiledIntervals(compact,profile)


ORACLE = r"""
import {parse} from 'parse5';
const chunks=[];for await(const chunk of process.stdin)chunks.push(chunk);const input=JSON.parse(Buffer.concat(chunks).toString('utf8'));
const KEY='data-study-compiled-key',attrs=n=>Object.fromEntries((n.attrs||[]).map(a=>[a.name,a.value]));
function walk(n,out=[]){out.push(n);for(const c of n.childNodes||[])walk(c,out);return out}
const text=n=>n.nodeName==='#text'?n.value:(n.childNodes||[]).map(text).join('');
function rel(root,node){const path=[];while(node!==root){if(!node?.parentNode)throw Error('outside AST root');path.unshift(node.parentNode.childNodes.indexOf(node));node=node.parentNode}return path}
function at(n,path){for(const i of path)n=n?.childNodes?.[i];return n}
function index(html){const doc=parse(html,{sourceCodeLocationInfo:true,scriptingEnabled:false}),nodes=walk(doc),byKey=new Map(),byStart=new Map(),regions={};for(const n of nodes){const a=attrs(n);if(a[KEY]){if(byKey.has(a[KEY]))throw Error('duplicate AST key');byKey.set(a[KEY],n)}if(n.sourceCodeLocation)byStart.set(n.sourceCodeLocation.startOffset,n);for(const cls of ['sf-report','examples-section'])if((a.class||'').split(/\s+/).includes(cls))(regions['.'+cls]||=[]).push(n)}return{nodes,byKey,byStart,regions}}
const old=index(input.source),neo=index(input.compact),newByte=pos=>{let delta=0;for(const[start,,b,a]of input.interval.edits){const before=Buffer.byteLength(input.interval.lexemes[b]),after=Buffer.byteLength(input.interval.lexemes[a]);if(start+before<=pos)delta+=after-before;else if(start<=pos)throw Error('removed source node')}return pos+delta};
const result={nodes:[],readers:[]};
for(const spec of input.profile.nodeBindings){const a=old.byKey.get(spec.key),b=neo.byKey.get(spec.key),ar=old.byKey.get(spec.rootKey),br=neo.byKey.get(spec.rootKey);if(at(ar,spec.relativePath)!==a||at(old.regions[spec.region.selector][spec.region.ordinal],spec.region.rootPath)!==ar)throw Error('original AST binding mismatch');result.nodes.push({key:spec.key,old:rel(ar,a),neo:rel(br,b),oldRegion:rel(old.regions[spec.region.selector][spec.region.ordinal],ar),newRegion:rel(neo.regions[spec.region.selector][spec.region.ordinal],br),oldText:text(a),newText:text(b),oldAttrs:attrs(a),newAttrs:attrs(b)})}
for(const[index,spec]of input.profile.readerLinks.entries()){const root=old.byKey.get(spec.rootKey),a=at(root,spec.relativePath);const sourceByte=Buffer.byteLength(input.source.slice(0,a.sourceCodeLocation.startOffset)),byte=newByte(sourceByte),char=Buffer.from(input.compact).subarray(0,byte).toString('utf8').length,b=neo.byStart.get(char);if(!b)throw Error('missing projected reader');result.readers.push({index,old:rel(root,a),neo:rel(neo.byKey.get(spec.rootKey),b),oldText:text(a),newText:text(b),oldAttrs:attrs(a),newAttrs:attrs(b)})}
process.stdout.write(JSON.stringify(result));
"""


class IntervalPathTests(unittest.TestCase):
    def ledger(self,raw=None,compiled=None,built=None):
        raw=tiny_source()if raw is None else raw
        built=tiny_compile(raw)if built is None else built
        old=packed(tiny_profile(raw)if compiled is None else compiled)
        plan=intervals.profile_bytes(built.profile)
        return paths.build_path_ledger(raw,built.compact_html,plan,old,
            expected_source_sha256=sha(raw),expected_compact_sha256=sha(built.compact_html),
            expected_interval_profile_sha256=sha(plan),expected_compiled_profile_sha256=sha(old))
    def test_adjacent_text_merge_changes_kept_and_reader_paths_and_only_allows_new_anchors(self):
        ledger=self.ledger()
        changed={r['key']:r for r in ledger['node_bindings']}
        self.assertEqual(changed['k']['old_relative_path'],[0,3])
        self.assertEqual(changed['k']['new_relative_path'],[0,1],'identity reuse keeps a stale childNodes path')
        self.assertEqual(ledger['reader_links'][0]['new_relative_path'],[0,2])
        self.assertEqual(changed['r']['required_attrs_additions'],[[intervals.ROOT_ATTRIBUTE,'sentence']])
        self.assertTrue(ledger['proposal_only'])
        self.assertFalse(any(row['path'][0]in {'panels','groups','bankRecords','projectionWrappers','bindings'}for row in ledger['proposed_changes']))

    def test_reversible_removal_of_mark_around_retained_key_is_not_authorized(self):
        raw=tiny_source().replace(b'<em data-study-compiled-key="k">',b'<mark><em data-study-compiled-key="k">').replace(b'</em>',b'</em></mark>')
        old=tiny_profile(raw);old['nodeBindings'][1]['relativePath']=[0,3,0]
        built=forged_edits(raw,tiny_compile(raw),[(raw.index(token),token,b'')for token in (b'<mark>',b'</mark>')])
        self.assertEqual(intervals.restore_html(built.compact_html,built.profile,
            expected_source_sha256=sha(raw),expected_profile_sha256=built.profile_sha256),raw)
        with self.assertRaisesRegex(ValueError,'unauthorized.*edit|unauthorized.*deletion'):
            self.ledger(raw,old,built)

    def test_only_compiler_removable_plain_span_pairs_are_authorized(self):
        chunk=b'<span class="card-chunk" data-chunk-side="en" data-chunk-ids="0">A</span>'
        cases={
          'style':chunk.replace(b'>A',b' style="color:red">A'),
          'aria':chunk.replace(b'>A',b' aria-label="meaning">A'),
          'keyboard':chunk.replace(b'>A',b' tabindex="0">A'),
          'unknown-attribute':chunk.replace(b'>A',b' data-other="x">A'),
          'default-emphasis-class':chunk.replace(b'class="card-chunk"',b'class="card-chunk sf-target-chunk"'),
          'tooltip':chunk.replace(b'>A',b' title="real tooltip">A'),
          'nested':chunk.replace(b'>A</span>',b'><b>A</b></span>'),
          'comment':chunk.replace(b'>A</span>',b'>A<!--audit--></span>'),
          'mark-ancestor':b'<mark>'+chunk+b'</mark>',
          'keyboard-ancestor':b'<span role="button">'+chunk+b'</span>',
          'target-ancestor':b'<span class="sf-target-chunk">'+chunk+b'</span>',
        }
        for reason,replacement in cases.items():
            raw=tiny_source().replace(chunk,replacement);built=tiny_compile(raw)
            start=raw.index(b'<span class="card-chunk');end=raw.index(b'>',start)+1
            close=raw.index(b'</span>',end)
            self.assertIn(raw[start:end],built.compact_html,reason)
            forged=forged_edits(raw,built,[(start,raw[start:end],b''),(close,b'</span>',b'')])
            with self.subTest(reason=reason),self.assertRaisesRegex(ValueError,'unauthorized.*deletion'):
                self.ledger(raw,tiny_profile(raw),forged)
        for tail in (chunk,b'<span></span>'):
            raw=tiny_source()+tail;built=tiny_compile(raw);start=len(raw)-len(tail)
            end=raw.index(b'>',start)+1;close=raw.index(b'</span>',end)
            forged=forged_edits(raw,built,[(start,raw[start:end],b''),(close,b'</span>',b'')])
            with self.subTest(unselected=tail),self.assertRaisesRegex(ValueError,'unauthorized.*deletion'):
                self.ledger(raw,tiny_profile(raw),forged)

    def test_deletion_must_be_exact_paired_tags_and_not_replacement_or_extra_attribute(self):
        raw=tiny_source();built=tiny_compile(raw)
        deletion_rows=[row for row in built.profile['edits']if built.profile['lexemes'][row[2]]]
        self.assertEqual(len(deletion_rows),2)
        for row in deletion_rows:
            forged=forged_edits(raw,built,[],remove=(row[0],))
            with self.subTest(single_tag=row[0]),self.assertRaisesRegex(ValueError,'unpaired.*deletion'):
                self.ledger(raw,tiny_profile(raw),forged)
        mark=raw.index(b'<em ')
        for addition in [(mark,b'<em',b'<strong'),(mark,b'',b'<!--inserted-->'),
                         (mark+len(b'<em'),b'',b' title="new"'),(mark,b'',b'')]:
            forged=forged_edits(raw,built,[addition])
            with self.subTest(edit=addition),self.assertRaisesRegex(ValueError,'unauthorized'):
                self.ledger(raw,tiny_profile(raw),forged)
        # A partial token cannot masquerade as a complete removable opening.
        start=deletion_rows[0][0]
        forged=forged_edits(raw,built,[(start,b'<span',b'')],remove=(start,))
        with self.assertRaisesRegex(ValueError,'unpaired.*deletion|unauthorized.*deletion'):
            self.ledger(raw,tiny_profile(raw),forged)


    def oracle(self,raw,built,old):
        if not shutil.which('node'):self.skipTest('Node/parse5 small AST reference unavailable')
        response=subprocess.run([shutil.which('node'),'--input-type=module','-e',ORACLE],
            input=packed({'source':raw.decode(),'compact':built.compact_html.decode(),'interval':built.profile,'profile':old}),
            stdout=subprocess.PIPE,stderr=subprocess.PIPE,cwd=Path(__file__).resolve().parents[1])
        if response.returncode and b"Cannot find package 'parse5'"in response.stderr:self.skipTest('parse5 small AST reference unavailable')
        self.assertEqual(response.returncode,0,response.stderr.decode())
        return json.loads(response.stdout)
    def check_oracle(self,raw,built,old,ledger):
        reference=self.oracle(raw,built,old)
        changes={r['key']:r for r in ledger['node_bindings']}
        for row in reference['nodes']:
            spec=next(n for n in old['nodeBindings']if n['key']==row['key'])
            proposal=changes.get(row['key'])
            self.assertEqual(row['oldText'],row['newText'])
            self.assertEqual((proposal or {}).get('new_relative_path',spec['relativePath']),row['neo'])
            self.assertEqual((proposal or {}).get('new_region_root_path',spec['region']['rootPath']),row['newRegion'])
            additions=dict((proposal or {}).get('required_attrs_additions',[]))
            self.assertEqual({**row['oldAttrs'],**additions},row['newAttrs'])
        links={r['index']:r for r in ledger['reader_links']}
        for row in reference['readers']:
            self.assertEqual(links.get(row['index'],{}).get('new_relative_path',old['readerLinks'][row['index']]['relativePath']),row['neo'])
            self.assertEqual(row['oldAttrs'],row['newAttrs']);self.assertEqual(row['oldText'],row['newText'])
    def test_small_parse5_differential_covers_entities_crlf_comments_and_adjacent_text(self):
        raw=tiny_source().replace(b'pre <span',b'pre <span',1)
        self.check_oracle(raw,tiny_compile(raw),tiny_profile(raw),self.ledger(raw))
        # Entity callbacks coalesce, comments split, literal CRLF normalizes,
        # and numeric CR remains CR. Only source text/metadata is adjusted.
        raw=tiny_source().replace(b'pre <span',b'pre&#32;<span',1)
        self.check_oracle(raw,tiny_compile(raw),tiny_profile(raw),self.ledger(raw))
        raw=tiny_source().replace(b'</span> <em',b'</span> <!--audit--><em',1)
        old=tiny_profile(raw);old['nodeBindings'][1]['relativePath']=[0,4];old['readerLinks'][0]['relativePath']=[0,5]
        self.check_oracle(raw,tiny_compile(raw),old,self.ledger(raw,old))
        raw=tiny_source().replace(b'pre ',b'pre\r\n',1)
        ex=example('pre\nA kept','甲',[([4,5],[[0,1]])])
        b=intervals.compile_html(raw,[intervals.SentenceBinding('sentence',0,ex,english_class='en',chinese_class='zh')],
              expected_source_sha256=sha(raw),css_sha256='f'*64,plain_chunks_are_interaction_only=True)
        old=tiny_profile(raw);old['nodeBindings'][0]['exactText']='pre\nA kept甲'
        self.check_oracle(raw,b,old,self.ledger(raw,old,b))
        # Direct output of the current literal/entity-correct compiler.
        raw=tiny_source().replace(b'pre ',b'pre&#13;',1)
        ex=example('pre\rA kept','甲',[([4,5],[[0,1]])])
        b=intervals.compile_html(raw,[intervals.SentenceBinding('sentence',0,ex,english_class='en',chinese_class='zh')],
              expected_source_sha256=sha(raw),css_sha256='f'*64,plain_chunks_are_interaction_only=True)
        old=tiny_profile(raw);old['nodeBindings'][0]['exactText']='pre\rA kept甲'
        self.check_oracle(raw,b,old,self.ledger(raw,old,b))
        # A freshly pinned but false LF declaration cannot bless the CR DOM.
        wrong=copy.deepcopy(b.profile);entry=wrong['sources'][0]
        entry['example']['text']='pre\nA kept'
        entry['example']['translation_alignment']['englishHash']=sha(b'pre\nA kept')
        entry['alignment_sha256']=sha(intervals.profile_bytes(entry['example']['translation_alignment']))
        wrong['sentences'][0]['paragraphs'][0]['text_sha256']=sha(b'pre\nA kept')
        with self.assertRaisesRegex(ValueError,'paragraph text'):
            self.ledger(raw,old,intervals.CompiledIntervals(b.compact_html,wrong))
    def real(self,name):
        saved={};t=compiler_tests.ChunkIntervalsTests()
        def capture(raw,bindings):
            b=intervals.compile_html(raw,bindings,expected_source_sha256=sha(raw),css_sha256='f'*64,
                                     plain_chunks_are_interaction_only=True)
            saved.update(raw=raw,built=b);return b
        t.compile=capture
        getattr(t,'test_real_train_three_member_group_and_native_compile_without_old_profile'if name=='train'else
                  'test_real_abolish_native_uses_same_generic_interface_and_exact_inverse')()
        root=Path(__file__).parent/'fixtures/experimental-compiled-card-v1'
        profile_raw=(root/name/'profile.json').read_bytes()
        seals=json.loads((root/'fixture-seals.json').read_bytes())['files']
        pin=next(row['stored_sha256']for row in seals if row['repository_path']==name+'/profile.json')
        self.assertEqual(sha(profile_raw),pin)
        return saved['raw'],saved['built'],json.loads(profile_raw),profile_raw
    def test_real_train_old_profile_paths_are_compared_with_small_parse5(self):
        raw,built,old,original_bytes=self.real('train');before=copy.deepcopy(old)
        ledger=paths.build_path_ledger(raw,built.compact_html,intervals.profile_bytes(built.profile),original_bytes,
             expected_source_sha256=sha(raw),expected_compact_sha256=sha(built.compact_html),
             expected_interval_profile_sha256=built.profile_sha256,expected_compiled_profile_sha256=sha(original_bytes))
        self.check_oracle(raw,built,old,ledger)
        self.assertEqual(old,before);self.assertEqual(ledger['validated']['node_bindings'],83)
        self.assertEqual(len(ledger['anchor_additions']),12)
    def test_real_abolish_old_profile_paths_are_compared_with_small_parse5(self):
        raw,built,old,original_bytes=self.real('abolish')
        ledger=paths.build_path_ledger(raw,built.compact_html,intervals.profile_bytes(built.profile),original_bytes,
             expected_source_sha256=sha(raw),expected_compact_sha256=sha(built.compact_html),
             expected_interval_profile_sha256=built.profile_sha256,expected_compiled_profile_sha256=sha(original_bytes))
        self.check_oracle(raw,built,old,ledger);self.assertEqual(ledger['validated']['node_bindings'],15)
    def test_source_profile_pin_tag_text_key_and_old_position_mismatches_rejected(self):
        raw=tiny_source();old=tiny_profile(raw)
        for field,value in [('tag','STRONG'),('exactText','foreign'),('relativePath',[0,1]),('key','foreign')]:
            candidate=copy.deepcopy(old);candidate['nodeBindings'][1][field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):self.ledger(raw,candidate)
        candidate=copy.deepcopy(old);candidate['bindings']['derivedHTMLSha256']='0'*64
        with self.assertRaisesRegex(ValueError,'source pin'):self.ledger(raw,candidate)
        candidate=copy.deepcopy(old);candidate['nodeBindings'][0]['logicalRoot']['id']='[null,"wrong",null]'
        with self.assertRaisesRegex(ValueError,'source identity'):self.ledger(raw,candidate)
    def test_all_four_external_input_pins_are_required(self):
        raw=tiny_source();b=tiny_compile(raw);p=intervals.profile_bytes(b.profile);old=packed(tiny_profile(raw))
        kwargs=dict(expected_source_sha256=sha(raw),expected_compact_sha256=sha(b.compact_html),
                    expected_interval_profile_sha256=sha(p),expected_compiled_profile_sha256=sha(old))
        for key in kwargs:
            with self.subTest(key=key),self.assertRaisesRegex(ValueError,'external SHA'):
                paths.build_path_ledger(raw,b.compact_html,p,old,**{**kwargs,key:'0'*64})
    def test_claimed_nodes_cannot_be_removed_or_wrong_reader_accepted(self):
        raw=tiny_source();old=tiny_profile(raw)
        candidate=copy.deepcopy(old);candidate['readerLinks'][0]['relativePath']=[0,3]
        with self.assertRaises(ValueError):self.ledger(raw,candidate)
        candidate=copy.deepcopy(old);candidate['readerLinks'][0]['immutableAttrs'][1][1]='https://wrong.invalid/'
        with self.assertRaises(ValueError):self.ledger(raw,candidate)
        candidate=copy.deepcopy(old);candidate['nodeBindings'][1]['requiredAttrs'].append(['style','color:red'])
        with self.assertRaises(ValueError):self.ledger(raw,candidate)
    def test_template_and_textfree_svg_are_explicitly_preserved_not_path_authority(self):
        raw=tiny_source().replace(b'</a></span>',b'</a></span><template><div data-study-compiled-key="r">not live</div></template>',1)
        old=tiny_profile(raw)
        # Compiler preserves template markup but does not select anything in it.
        b=tiny_compile(raw);ledger=self.ledger(raw,old,b);self.check_oracle(raw,b,old,ledger)
        self.assertIn('template',[r['tag']for r in ledger['opaque_preserved']])
        raw=tiny_source();start=raw.index(b'<a ');end=raw.index(b'</a>')+4;link=raw[start:end].replace(b'</a>',b'<svg><path d="M0 0"></path></svg></a>')
        raw=(raw[:start]+raw[end:]).replace(b'</span><span class="zh">',b'</span>'+link+b'<span class="zh">',1)
        old=tiny_profile(raw);old['readerLinks'][0]['relativePath']=[1]
        ledger=self.ledger(raw,old);self.check_oracle(raw,tiny_compile(raw),old,ledger)
        self.assertIn('svg',[r['tag']for r in ledger['opaque_preserved']])
    def test_ambiguous_table_implicit_closure_and_namespace_binding_rejected(self):
        raw=tiny_source()
        for changed in [raw.replace(b'<em ',b'<table><em ',1).replace(b'</em>',b'</em></table>',1),
                        raw.replace(b'<em ',b'<p><em ',1).replace(b'</em>',b'</em><div></div></p>',1),
                        raw.replace(b'<em ',b'<svg><em ',1).replace(b'</em>',b'</em></svg>',1)]:
            # These are proof-bearing arbitrary inputs: bind source pin anew,
            # not a bypass of an original immutable expected source.
            with self.subTest(changed=changed[:30]),self.assertRaises(ValueError):self.ledger(changed)
    def test_limit_and_duplicate_json_are_rejected(self):
        raw=tiny_source();b=tiny_compile(raw);p=intervals.profile_bytes(b.profile);old=packed(tiny_profile(raw))
        kwargs=dict(expected_source_sha256=sha(raw),expected_compact_sha256=sha(b.compact_html),
                    expected_interval_profile_sha256=sha(p),expected_compiled_profile_sha256=sha(old))
        with self.assertRaisesRegex(ValueError,'limit'):paths.build_path_ledger(raw,b.compact_html,p,old,**kwargs,max_source_bytes=10)
        duplicate=old[:-1]+b',"version":1}'
        with self.assertRaisesRegex(ValueError,'duplicate JSON'):
            paths.build_path_ledger(raw,b.compact_html,p,duplicate,**{**kwargs,'expected_compiled_profile_sha256':sha(duplicate)})


    def test_pre_first_linefeed_and_comments_match_small_parse5(self):
        for pre,word in [(b'<pre>\r\nline</pre>','line'),(b'<pre><!--audit-->\nline</pre>','\nline')]:
            raw=tiny_source().replace(b'</a></span>',b'</a></span>'+pre,1)
            old=tiny_profile(raw);old['nodeBindings'][0]['exactText']='pre A kept'+word+'甲'
            b=tiny_compile(raw);self.check_oracle(raw,b,old,self.ledger(raw,old,b))
    def test_duplicate_live_key_rejected_and_opaque_nesting_is_bounded(self):
        raw=tiny_source()+b'<span data-study-compiled-key="k">foreign</span>'
        with self.assertRaisesRegex(ValueError,'duplicate bound key'):self.ledger(raw)
        raw=tiny_source().replace(b'</a></span>',b'</a></span><template><template><template>x</template></template></template>',1)
        b=tiny_compile(raw);old=packed(tiny_profile(raw));plan=intervals.profile_bytes(b.profile)
        with self.assertRaisesRegex(ValueError,'nesting'):
            paths.build_path_ledger(raw,b.compact_html,plan,old,expected_source_sha256=sha(raw),expected_compact_sha256=sha(b.compact_html),
                expected_interval_profile_sha256=sha(plan),expected_compiled_profile_sha256=sha(old),max_depth=4)


    def test_native_source_without_a_reader_preserves_null_identity(self):
        raw=tiny_source();start=raw.index(b'<a ');end=raw.index(b'</a>')+4;raw=raw[:start]+raw[end:]
        old=tiny_profile(raw);old['readerLinks']=[]
        for spec in old['nodeBindings']:spec['logicalRoot']['id']=None
        ledger=self.ledger(raw,old);self.assertEqual(ledger['validated']['reader_links'],0)


if __name__=='__main__':unittest.main()
