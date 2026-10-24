"""One streaming pass over each existing sealed resource; never parse DOM/JSON data."""
from pathlib import Path
import argparse,hashlib,json,gzip,os,stat,shutil,time
D=Path(__file__).resolve().parent
ROOT=Path('/Users/apple/Library/Application Support/AnkiStudyCatalog/exports/20261015/master-redbook-web-v3')
CHUNK=1024*1024
H=lambda:hashlib.sha256()
def identity(s):return {key:getattr(s,key) for key in ('st_dev','st_ino','st_mode','st_size','st_mtime_ns','st_ctime_ns')}
def opened(path):
    if path.is_symlink():raise ValueError('symlink source')
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW);s=os.fstat(fd)
    if not stat.S_ISREG(s.st_mode):os.close(fd);raise ValueError('nonregular source')
    return os.fdopen(fd,'rb'),s
assets=json.loads((D/'compiled-assets.json').read_bytes());rules=[assets['runtime']]
for entry in assets['entries'].values():rules.extend([entry['html'],entry['profile']])
records=[]
for rule in rules:
    src=ROOT/rule['src'];s=src.lstat();assert stat.S_ISREG(s.st_mode) and not src.is_symlink()
    assert rule['gzipSrc']==rule['src']+'.gz' and '/' not in rule['src']
    records.append({'source':str(src),'route':'book/'+rule['gzipSrc'],'rawRoute':'book/'+rule['src'],'rawBytes':s.st_size,'rawSha256':rule['sha256'],'gzipPath':str(D/rule['gzipSrc']),'before':identity(s)})
minimum=sum(r['rawBytes'] for r in records)+max(r['rawBytes'] for r in records)+1024*1024
preflight={'schema':'study-compiled-transport-compression-preflight.v1','stage':str(D),'chunkBytes':CHUNK,'worstAdditionalBytes':minimum,'availableBytes':shutil.disk_usage(D).free,'records':records,'largeDOM':False,'semanticProducer':False}
args=argparse.ArgumentParser();args.add_argument('--pack',action='store_true');opt=args.parse_args()
if not opt.pack:print(json.dumps(preflight,indent=2));raise SystemExit(0)
assert preflight['availableBytes']>minimum
report=[];began=time.monotonic()
for record in records:
    src=Path(record['source']);dest=Path(record['gzipPath']);tmp=dest.with_name(dest.name+'.part')
    assert not dest.exists() and not tmp.exists()
    inp,before=opened(src);assert identity(before)==record['before'];rawHash=H();rawCount=0
    with inp, tmp.open('xb') as out:
        with gzip.GzipFile(fileobj=out,filename='',mode='wb',compresslevel=6,mtime=0) as gz:
            while chunk:=inp.read(CHUNK):rawHash.update(chunk);rawCount+=len(chunk);gz.write(chunk)
        out.flush();os.fsync(out.fileno())
        assert identity(os.fstat(inp.fileno()))==record['before']
    assert identity(src.lstat())==record['before']
    assert rawHash.hexdigest()==record['rawSha256'] and rawCount==record['rawBytes']
    decodedHash=H();decodedCount=0
    with gzip.open(tmp,'rb') as decoded:
        while chunk:=decoded.read(CHUNK):decodedHash.update(chunk);decodedCount+=len(chunk)
    assert decodedHash.hexdigest()==record['rawSha256'] and decodedCount==record['rawBytes']
    compressedHash=H()
    with tmp.open('rb') as inp:
        assert inp.read(10)[4:8]==bytes(4);inp.seek(0)
        while chunk:=inp.read(CHUNK):compressedHash.update(chunk)
    assert not dest.exists();os.link(tmp,dest);tmp.unlink()
    report.append({**record,'gzipBytes':dest.stat().st_size,'gzipSha256':compressedHash.hexdigest(),'decodedSHAEqualsRaw':True,'decodedBytes':decodedCount,'contentType':'application/gzip','contentEncoding':None,'after':identity(src.lstat())})
result={**preflight,'status':'passed','elapsedSeconds':time.monotonic()-began,'newFiles':len(report),'gzipBytes':sum(r['gzipBytes'] for r in report),'decodedBytes':sum(r['rawBytes'] for r in report),'records':report,'CPUStopped':True}
(D/'packed-assets.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
