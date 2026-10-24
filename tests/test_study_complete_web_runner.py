"""Execute the actual final-alias For AST, including real FD/SHA read."""
import ast,importlib.util,os
from pathlib import Path
import sys,tempfile,unittest
HERE=Path(__file__).resolve().parent
REPO=HERE.parent
spec=importlib.util.spec_from_file_location('runner',REPO/'scripts/build_study_complete_web_batch.py');runner=importlib.util.module_from_spec(spec);spec.loader.exec_module(runner)
raw=(REPO/'scripts/build_study_complete_web_batch.py').read_bytes()
tree=ast.parse(raw)
loop=next(n for n in ast.walk(tree) if isinstance(n,ast.For) and isinstance(n.target,ast.Tuple) and [x.id for x in n.target.elts]==['alias','target','before','receipt'])
code=compile(ast.Module(body=[loop],type_ignores=[]),'<actual final alias loop>','exec')
class FinalAlias(unittest.TestCase):
 def run_case(self,attack=None):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);target=root/'catalog.json';target.write_bytes(b'{"same":"source bytes"}');alias=root/'link.json';alias.symlink_to(target)
   stamp=lambda s:[s.st_dev,s.st_ino,s.st_mode,s.st_size,s.st_mtime_ns,s.st_ctime_ns]
   receipt={'sha256':runner.pin(target)[0],'six':stamp(target.stat())};before=stamp(alias.lstat())
   def pin(path,expected):
    if attack=='source':os.chmod(target,target.stat().st_mode)
    if attack=='alias':alias.unlink();alias.symlink_to(target)
    return runner.pin(path,expected)
   exec(code,{'os':os,'pin':pin,'aliases':[(alias,target,before,receipt)]})
 def test_stable_actual_pin_passes(self):self.run_case()
 def test_source_same_bytes_ctime_during_pin_rejected(self):
  with self.assertRaisesRegex(ValueError,'final SHA'):self.run_case('source')
 def test_alias_replaced_during_pin_rejected(self):
  with self.assertRaisesRegex(ValueError,'final SHA'):self.run_case('alias')
if __name__=='__main__':unittest.main(verbosity=2)
