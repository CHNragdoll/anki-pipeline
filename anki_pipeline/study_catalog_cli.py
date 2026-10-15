"""One entry point for every book's PostgreSQL import and generation."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import sys
import psycopg
from . import study_catalog as c


def output(value):print(json.dumps(value,ensure_ascii=False),flush=True)


def parser():
    root=argparse.ArgumentParser(description='统一 PostgreSQL 学习资料库：所有书共用一个生成入口')
    root.add_argument('--dsn-env',default='ANKI_STUDY_DSN',help='连接信息的环境变量名，不在参数中传密码')
    root.add_argument('--schema',default='study_catalog')
    sub=root.add_subparsers(dest='command',required=True)
    sub.add_parser('init');sub.add_parser('status')
    sub.add_parser('register-presentation')
    book=sub.add_parser('import-book');book.add_argument('--file',type=Path,required=True)
    book.add_argument('--id',required=True);book.add_argument('--title',required=True);book.add_argument('--edition',type=int,required=True)
    book.add_argument('--collection',type=Path);book.add_argument('--catalog',type=Path);book.add_argument('--sha256')
    history=sub.add_parser('import-history');history.add_argument('--file',type=Path,required=True)
    history.add_argument('--kind',choices=['legacy','semantic'],required=True)
    migrate=sub.add_parser('migrate');migrate.add_argument('--manifest',type=Path,required=True)
    migrate.add_argument('--report',type=Path,required=True);migrate.add_argument('--backups',type=Path,required=True)
    export=sub.add_parser('export');export.add_argument('--book',required=True)
    export.add_argument('--format',choices=['apkg','web'],required=True);export.add_argument('--output',type=Path,required=True)
    edit=sub.add_parser('edit-field');edit.add_argument('--component',required=True)
    edit.add_argument('--expected-file',type=Path,required=True);edit.add_argument('--value-file',type=Path,required=True)
    edit.add_argument('--reason',required=True);edit.add_argument('--backups',type=Path,required=True)
    saved=sub.add_parser('backup');saved.add_argument('--directory',type=Path,required=True)
    restore=sub.add_parser('restore');restore.add_argument('--file',type=Path,required=True)
    restore.add_argument('--new-schema',required=True)
    verify=sub.add_parser('verify');verify.add_argument('--deep',action='store_true')
    return root


def run(args):
    selected=c.Target(os.environ.get(args.dsn_env,c.DEFAULT_DSN),args.schema)
    if args.command=='init':c.initialize(selected);output(c.summary(selected))
    elif args.command=='status':output(c.summary(selected))
    elif args.command=='register-presentation':
        from .study_catalog_presentation import install
        output(install(selected))
    elif args.command=='import-book':
        from .study_catalog_import import import_package
        output(import_package(selected,args.file,book_id=args.id,title=args.title,edition=args.edition,
                              collection=args.collection,catalog=args.catalog,expected_sha=args.sha256,callback=output))
    elif args.command=='import-history':
        from .study_catalog_import import import_sqlite_history
        output(import_sqlite_history(selected,args.file,kind=args.kind,callback=output))
    elif args.command=='migrate':
        from .study_catalog_import import import_package,import_sqlite_history
        manifest=json.loads(args.manifest.read_text());c.initialize(selected)
        if manifest.get('schema')!='study-catalog-inputs.v1':raise ValueError('unknown migration manifest schema')
        c.guard_new_output(args.report,[args.manifest]);args.report.parent.mkdir(parents=True,exist_ok=True)
        saved=c.backup(selected,args.backups);output({'stage':'before-migration-backup','file':str(saved)})
        results=[]
        for book in manifest['books']:
            results.append(import_package(selected,book['package'],book_id=book['id'],title=book['title'],edition=book['edition'],
                collection=book.get('collection'),catalog=book.get('catalog'),expected_sha=book.get('sha256'),callback=output))
        for source in manifest.get('sqlite_sources',[]):
            results.append(import_sqlite_history(selected,source['file'],kind=source['kind'],callback=output))
        report={'schema':'study-catalog-migration.v1','engine':'postgresql','before_backup':str(saved),
                'imports':results,'summary':c.summary(selected),'source_manifest_sha256':__import__('hashlib').sha256(args.manifest.read_bytes()).hexdigest()}
        with args.report.open('x') as stream:json.dump(report,stream,ensure_ascii=False,indent=2)
        output(report)
    elif args.command=='edit-field':
        output(c.edit_component(selected,args.component,args.value_file.read_text(),expected=args.expected_file.read_text(),
                                reason=args.reason,backups=args.backups))
    elif args.command=='backup':output({'file':str(c.backup(selected,args.directory)),'engine':'postgresql'})
    elif args.command=='restore':
        c.restore(args.file,c.Target(selected.dsn,args.new_schema));output({'restored_schema':args.new_schema,'engine':'postgresql'})
    elif args.command=='export':
        from .study_catalog_export import export_book
        output(export_book(selected,args.book,args.output,format=args.format,callback=output))
    elif args.command=='verify':
        from .study_catalog_export import verify_catalog
        report=verify_catalog(selected,deep=args.deep);output(report)
        return 0 if report['ok'] else 2
    return 0


def main(argv=None):
    args=parser().parse_args(argv)
    try:return run(args)
    except (OSError,ValueError,psycopg.Error) as exc:
        # Never include a credential-bearing DSN or arbitrary server row DETAIL.
        output({'ok':False,'error':type(exc).__name__,'message':str(exc) if not isinstance(exc,psycopg.Error) else 'PostgreSQL operation failed; transaction was not accepted','sqlstate':getattr(exc,'sqlstate',None)})
        return 2


if __name__=='__main__':sys.exit(main())
