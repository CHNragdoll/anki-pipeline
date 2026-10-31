import unittest
from types import SimpleNamespace
from anki_pipeline.study_catalog_native_units import plan_moves

class NativeUnitPlanTests(unittest.TestCase):
    def col(self, rows, target=True):
        return SimpleNamespace(db=SimpleNamespace(all=lambda *args:rows),decks=SimpleNamespace(name=lambda did:{10:'B::2023 年',11:'B::2023 年::单选题',20:'自定义'}[did],by_name=lambda name:{'id':11} if target else None))
    def test_only_unique_unfiltered_original_location_moves(self):
        mapping={guid:{'from':'B::2023 年','to':'B::2023 年::单选题'} for guid in ['valid','custom','filtered','duplicate','missing','done']}
        rows=[(1,10,0,'valid'),(2,20,0,'custom'),(3,10,20,'filtered'),(4,10,0,'duplicate'),(5,10,0,'duplicate'),(6,11,0,'done')]
        plan=plan_moves(self.col(rows),mapping)
        self.assertEqual(plan['moves'],{11:[1]});self.assertEqual(plan['already'],1)
        self.assertEqual(set(plan['skipped']),{'custom','filtered','duplicate','missing'})
    def test_missing_target_never_creates_deck(self):
        with self.assertRaises(ValueError):plan_moves(self.col([(1,10,0,'a')],False),{'a':{'from':'B::2023 年','to':'B::2023 年::单选题'}})
