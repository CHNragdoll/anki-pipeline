import unittest
from anki_pipeline.study_catalog_units import validate,membership

class UnitProjectionTests(unittest.TestCase):
    def setUp(self):
        self.units={'10':{'id':10,'name':'Book::2023 年'},'11':{'id':11,'name':'Book::2023 年::单选题'}}
    def test_complete_identity_mapping_and_shared_membership(self):
        validate(self.units,{'100':11},[100])
        book={'units':self.units,'unit_overlay':{'cards':{'100':11}}}
        self.assertEqual(membership(book,100,10),(11,'Book::2023 年::单选题'))
        self.assertEqual(membership({'units':self.units},100,10),(10,'Book::2023 年'))
    def test_incomplete_extra_unknown_and_duplicate_decks_rejected(self):
        for cards in [{},{'100':11,'101':11},{'100':99}]:
            with self.subTest(cards=cards),self.assertRaises(ValueError):validate(self.units,cards,[100])
        with self.assertRaises(ValueError):validate({**self.units,'12':{'id':12,'name':self.units['11']['name']}},{'100':11},[100])
