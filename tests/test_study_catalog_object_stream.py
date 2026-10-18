"""Bounded object reads, with no persistent PostgreSQL fixture or writes."""
import hashlib
import io
import os
import unittest
from unittest.mock import patch
import zlib

import psycopg
from anki_pipeline import study_catalog as catalog


class Row:
    def __init__(self,value):self.value=value
    def fetchone(self):return self.value


class ObjectDatabase:
    def __init__(self,codec,raw,encoded=None,*,size=None,key=None,fault=None):
        self.codec=codec;self.data=encoded if encoded is not None else raw
        self.size=len(raw) if size is None else size
        self.key=key or hashlib.sha256(raw).hexdigest();self.calls=[];self.fault=fault

    def execute(self,query,params):
        query=' '.join(query.split());self.calls.append((query,params))
        if query=='select codec,byte_length,data from objects where id=%s':
            if len(self.data)>128:raise AssertionError('large object data was materialized in one query')
            return Row((self.codec,self.size,self.data))
        if query.startswith('select codec,byte_length,octet_length(data),'):
            threshold,key=params
            return Row((self.codec,self.size,len(self.data),self.data if len(self.data)<=threshold else None))
        if query.startswith('select substring(data from %s for %s)'):
            start,length,key,codec,size,encoded_size=params
            if (key,codec,size,encoded_size)!=(self.key,self.codec,self.size,len(self.data)):return Row(None)
            value=self.data[start-1:start-1+length]
            if self.fault=='missing':return Row(None)
            if self.fault=='short':value=value[:-1]
            if self.fault=='long':value+=b'x'
            return Row((value,))
        raise AssertionError('unexpected query: '+query)


class ObjectStreamTests(unittest.TestCase):
    def setUp(self):
        # Small explicit boundaries exercise every wire/decompress boundary.
        self.inline=patch.object(catalog,'_OBJECT_INLINE_BYTES',128,create=True)
        self.chunk=patch.object(catalog,'_OBJECT_READ_BYTES',37,create=True)
        self.inline.start();self.chunk.start()
        self.addCleanup(self.inline.stop);self.addCleanup(self.chunk.stop)

    def write(self,db):
        output=io.BytesIO();count=catalog.write_object(db,db.key,output)
        return count,output.getvalue()

    def test_large_raw_and_zlib_never_fetch_entire_data(self):
        raw=bytes(range(256))*16
        for codec,data in (('raw',raw),('zlib',zlib.compress(raw))):
            with self.subTest(codec=codec):
                db=ObjectDatabase(codec,raw,data);self.assertEqual(self.write(db),(len(raw),raw))
                reads=[params for query,params in db.calls if query.startswith('select substring')]
                self.assertEqual([args[0] for args in reads],list(range(1,len(data)+1,37)))
                self.assertTrue(all(0<args[1]<=37 for args in reads))
                self.assertEqual(len(db.calls),len(reads)+1)

    def test_small_and_empty_objects_keep_one_query(self):
        for raw in (b'',b'raw\x00\xff'):
            for codec,data in (('raw',raw),('zlib',zlib.compress(raw))):
                with self.subTest(raw=raw,codec=codec):
                    db=ObjectDatabase(codec,raw,data)
                    self.assertEqual(self.write(db),(len(raw),raw));self.assertEqual(len(db.calls),1)

    def test_decompressed_output_is_bounded_despite_large_expansion(self):
        raw=b'x'*(2*1024**2+19);db=ObjectDatabase('zlib',raw,zlib.compress(raw))
        class Sink:
            def __init__(self):self.digest=hashlib.sha256();self.sizes=[]
            def write(self,part):self.digest.update(part);self.sizes.append(len(part))
        output=Sink();count=catalog.write_object(db,db.key,output)
        self.assertEqual(count,len(raw));self.assertEqual(output.digest.hexdigest(),db.key)
        self.assertLessEqual(max(output.sizes),1024**2)

    def test_invalid_encoded_content_length_digest_and_codec_reject(self):
        raw=bytes(range(256))*16;encoded=zlib.compress(raw)
        cases=(('raw',raw,len(raw)-1,None),('raw',raw,len(raw)+1,None),
               ('raw',raw,len(raw),'0'*64),('zlib',b'corrupt'*100,len(raw),None),
               ('zlib',encoded[:-1],len(raw),None),('zlib',encoded+b'trailing',len(raw),None),
               ('zlib',encoded+encoded,len(raw),None),('zlib',encoded,len(raw)-1,None),
               ('zlib',encoded,len(raw)+1,None),('unknown',raw,len(raw),None))
        for codec,data,size,key in cases:
            with self.subTest(codec=codec,size=size,tail=data[-8:]):
                db=ObjectDatabase(codec,raw,data,size=size,key=key)
                with self.assertRaises(ValueError):self.write(db)
                with self.assertRaises(ValueError):catalog.write_encoded_object(db.key,codec,size,data,io.BytesIO())

    def test_missing_short_and_oversized_chunk_reject(self):
        raw=bytes(range(256))*16
        for fault in ('missing','short','long'):
            with self.subTest(fault=fault),self.assertRaises(ValueError):
                self.write(ObjectDatabase('raw',raw,fault=fault))

    def test_missing_object_rejects(self):
        class Missing:
            def execute(self,*args):return Row(None)
        with self.assertRaisesRegex(ValueError,'missing catalog object'):
            catalog.write_object(Missing(),'0'*64,io.BytesIO())

    @unittest.skipUnless(os.environ.get('ANKI_STUDY_TEST_DSN'),'requires explicit isolated read-only PostgreSQL test connection')
    def test_real_postgres_bytea_substring_and_inline_case(self):
        raw=bytes(range(256))*16
        with psycopg.connect(os.environ['ANKI_STUDY_TEST_DSN']) as connection,connection.transaction():
            connection.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            for codec,data in (('raw',raw),('zlib',zlib.compress(raw)),('raw',b'')):
                actual=raw if data else b'';key=hashlib.sha256(actual).hexdigest()
                class Fixture:
                    def execute(self,query,params):
                        return connection.execute('WITH objects(id,codec,byte_length,data) AS '
                            '(VALUES (%s::text,%s::text,%s::bigint,%s::bytea)) '+query,
                            (key,codec,len(actual),data,*params))
                output=io.BytesIO()
                self.assertEqual(catalog.write_object(Fixture(),key,output),len(actual))
                self.assertEqual(output.getvalue(),actual)


if __name__=='__main__':unittest.main()
