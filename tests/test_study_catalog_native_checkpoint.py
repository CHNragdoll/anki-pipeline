"""Two-note official SDK acceptance; no GUI or personal collection paths."""
import hashlib
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from scripts import verify_study_catalog_native as verifier


class NativeCheckpointTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app=Path('/Applications/Anki.app/Contents/Resources/app_packages')
        if not app.is_dir():raise unittest.SkipTest('official installed Anki SDK unavailable')
        try:import zstandard  # Optional modern expected-archive dependency.
        except ImportError as error:raise unittest.SkipTest('optional zstandard binding unavailable') from error
        sys.path.insert(0,str(app))
        import anki.collection
        from anki.import_export_pb2 import ExportAnkiPackageOptions
        cls.sdk=anki.collection;cls.Collection=anki.collection.Collection;cls.ExportOptions=ExportAnkiPackageOptions

    def test_real_default_update_twice_checkpoints_preserve_review_suspend_flags_and_log(self):
        with tempfile.TemporaryDirectory(prefix='study-native-checkpoint-fixture-') as folder:
            root=Path(folder);fixture=root/'fixture';fixture.mkdir()
            source=root/'source.apkg';candidate=root/'candidate.apkg'
            col=self.Collection(str(fixture/'collection.anki2'))
            try:
                model=col.models.by_name('Basic');self.assertIsNotNone(model)
                first=col.new_note(model);first.fields=['first','原背面 e\u0301 <img src="fixture.svg">']
                second=col.new_note(model);second.fields=['second','完整中文😀 unchanged']
                col.add_note(first,1);col.add_note(second,1)
                # A real default IF_NEWER update, without sleeping or changing
                # the verifier's import options/model/identity rules.
                col.db.execute('update notes set mod=mod-2 where id=?',first.id)
                media=b'<svg xmlns="http://www.w3.org/2000/svg"><text>original</text></svg>'
                (Path(col.media.dir())/'fixture.svg').write_bytes(media)
                col.export_anki_package(out_path=str(source),options=self.ExportOptions(
                    with_scheduling=True,with_media=True,legacy=True),limit=None)
                first=col.get_note(first.id);first.fields[1]='更新完整中文 e\u0301 <img src="fixture.svg">';col.update_note(first)
                col.export_anki_package(out_path=str(candidate),options=self.ExportOptions(
                    with_scheduling=True,with_media=True,legacy=False),limit=None)
            finally:col.close()
            before={p:hashlib.sha256(p.read_bytes()).hexdigest()for p in (source,candidate)}
            opened=[];closed=[];imports=[]
            def snapshot(value):
                columns=[r[1]for r in value.db.all('pragma table_info(cards)')]
                kept=[i for i,n in enumerate(columns)if n not in {'mod','usn'}]
                return dict(ids=value.db.all('select id,guid,mid from notes order by id'),
                    states=[[r[i]for i in kept]for r in value.db.all('select * from cards order by id')],
                    log=value.db.all('select * from revlog order by id'),
                    suspended_flagged=value.db.all('select id,queue,flags from cards where queue=-1 and (flags&7)=3'),
                    fields=value.db.all('select guid,flds from notes order by guid'),
                    media=(Path(value.media.dir())/'fixture.svg').read_bytes() if (Path(value.media.dir())/'fixture.svg').exists() else None)
            def collection(path):
                path=Path(path);self.assertEqual(path.name,'collection.anki2')
                self.assertTrue(path.parent.name.startswith('study-native-qa-'))
                value=self.Collection(str(path));opened.append(snapshot(value))
                close=value.close;load=value.import_anki_package
                def import_package(request):
                    imports.append((request.package_path,request.options.SerializeToString()))
                    return load(request)
                def close_collection(*args,**kwargs):
                    state=snapshot(value);state['wal_before']=(Path(str(path)+'-wal').stat().st_size if Path(str(path)+'-wal').exists() else 0)
                    close(*args,**kwargs)
                    state['wal_after']=(Path(str(path)+'-wal').stat().st_size if Path(str(path)+'-wal').exists() else 0)
                    closed.append(state)
                value.import_anki_package=import_package;value.close=close_collection
                return value
            with patch.object(self.sdk,'Collection',side_effect=collection):
                result=verifier.verify(source,candidate,root/'REPORT.json')
            self.assertEqual(len(opened),4,'initial + source checkpoint + two actual candidate checkpoints')
            self.assertEqual(len(closed),4)
            self.assertEqual(imports,[(str(p.resolve()),b'\x20\x01')for p in (source,candidate,candidate)])
            for index in range(3):
                self.assertEqual({k:v for k,v in closed[index].items()if not k.startswith('wal_')},opened[index+1])
                self.assertEqual(closed[index]['wal_after'],0,'official close checkpoints/removes WAL')
            self.assertEqual(len(closed[0]['suspended_flagged']),1)
            self.assertTrue(closed[0]['log']);self.assertEqual(closed[0]['log'],closed[-1]['log'])
            self.assertEqual(closed[0]['ids'],closed[-1]['ids']);self.assertEqual(closed[0]['states'],closed[-1]['states'])
            final=closed[-1]['fields'];self.assertEqual(len(final),2)
            self.assertTrue(any('更新完整中文' in row[1]for row in final))
            self.assertTrue(any('完整中文😀 unchanged' in row[1]for row in final))
            self.assertEqual(closed[-1]['media'],media)
            self.assertEqual(result['duplicate_update_imports'],2)
            self.assertTrue(result['identity_schedule_flags_revlog_preserved'])
            self.assertEqual(result['field_verification']['notes_checked'],2)
            self.assertEqual(result['media_verification']['files_checked'],1)
            self.assertEqual(result['native_rendered_samples'],2)
            self.assertEqual(result['native_collection_checkpoints'],3)
            self.assertEqual(before,{p:hashlib.sha256(p.read_bytes()).hexdigest()for p in before})

    def test_failed_checkpoint_close_is_retried_by_final_cleanup(self):
        with tempfile.TemporaryDirectory(prefix='study-native-close-failure-fixture-') as folder:
            root=Path(folder);fixture=root/'fixture';fixture.mkdir()
            source=root/'source.apkg';candidate=root/'candidate.apkg'
            col=self.Collection(str(fixture/'collection.anki2'))
            try:
                note=col.new_note(col.models.by_name('Basic'));note.fields=['first','完整正文']
                col.add_note(note,1)
                col.export_anki_package(out_path=str(source),options=self.ExportOptions(
                    with_scheduling=True,with_media=True,legacy=True),limit=None)
            finally:col.close()
            candidate.write_bytes(source.read_bytes())
            opened=[];close_calls=[]
            def collection(path):
                value=self.Collection(str(path));opened.append(value);close=value.close
                def close_once_fails(*args,**kwargs):
                    close_calls.append(value)
                    if len(close_calls)==1:raise RuntimeError('injected checkpoint close failure')
                    return close(*args,**kwargs)
                value.close=close_once_fails
                return value
            report=root/'REPORT.json'
            with patch.object(self.sdk,'Collection',side_effect=collection):
                with self.assertRaisesRegex(RuntimeError,'injected checkpoint close failure'):
                    verifier.verify(source,candidate,report)
            self.assertEqual(len(opened),1)
            self.assertEqual(len(close_calls),2,'final cleanup must retry the still-open collection')
            self.assertIsNone(opened[0].db)
            self.assertFalse(report.exists(),'a failed checkpoint must not publish PASS evidence')


if __name__=='__main__':unittest.main()
