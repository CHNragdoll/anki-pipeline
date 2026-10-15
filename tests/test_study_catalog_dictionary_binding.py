"""Reviewed source corrections must not masquerade as the original entry."""
from copy import deepcopy
import unittest

from anki_pipeline.study_catalog_import import _dictionary_binding


class DictionaryBindingTests(unittest.TestCase):
    def test_reviewed_definition_keeps_new_evidence_and_original_binding(self):
        record={'definition_source':'oxford','definition_provenance':{
            'components':[{'source':'oxford','sense_start':0,'sense_count':1,'html_sha256':'a'*64}]}}
        sense={'ordinal':0}
        original=_dictionary_binding(record,sense)
        correction={'schema':'study-catalog-dictionary-correction.v1','dictionary':'oxford',
            'entry_html_sha256':'b'*64,'evidence_sha256':'c'*64,'original_binding':original,
            'reason':'按完整词典条目核对补全释义'}
        record['definition_provenance']['catalog_sense_revisions']={'0':correction}
        self.assertEqual(_dictionary_binding(record,sense),correction)
        self.assertNotEqual(_dictionary_binding(record,sense)['entry_html_sha256'],original['entry_html_sha256'])
        for change in ({'dictionary':'invented-source'},{'evidence_sha256':'missing'}, {'reason':''}):
            invalid=deepcopy(record)
            invalid['definition_provenance']['catalog_sense_revisions']['0'].update(change)
            with self.assertRaisesRegex(ValueError,'provenance correction'):_dictionary_binding(invalid,sense)


if __name__=='__main__':unittest.main()
