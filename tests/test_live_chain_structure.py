"""Contract guard for the S0–S10 test layout, not a production unit test."""
import ast
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / 'tests/live_chain_manifest.json'


def test_chain_unit_ownership_and_retained_integration_cases():
    manifest = json.loads(MANIFEST.read_text())
    targets = []
    definitions = set()
    for file in manifest['python_units']:
        tree = ast.parse((ROOT / file).read_text())
        for fn in tree.body:
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)) or not fn.name.startswith('test_'):
                continue
            marks = [d for d in fn.decorator_list if isinstance(d, ast.Call)
                     and isinstance(d.func, ast.Attribute) and d.func.attr == 'target']
            assert len(marks) == 1, (file, fn.name, 'one declared function target required')
            target = ast.literal_eval(marks[0].args[0])
            module, symbol = target.split(':')
            production = ast.parse((ROOT / (module.replace('.', '/') + '.py')).read_text())
            nodes = production.body
            for name in symbol.split('.'):
                node = next(n for n in nodes if getattr(n, 'name', None) == name)
                nodes = getattr(node, 'body', [])
            assert isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)), target
            targets.append(target)
            definitions.add(f'{file}::{fn.name}')
    assert targets and len(targets) == len(set(targets)), 'duplicate unit ownership'
    assert set(targets) == set(manifest['python_targets']), 'missing or undeclared function owner'
    for source, cases in manifest['legacy_cases'].items():
        old = ast.parse(subprocess.check_output(['git', 'show', f'19a96c9:{source}'], text=True))
        originals = {n.name: n for n in old.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name.startswith('test_')}
        assert set(cases) == set(originals), (source, 'unaccounted old test')
        for name, destination in cases.items():
            if isinstance(destination, list):
                assert set(destination) <= definitions, (source, name, 'missing replacement owner')
            else:
                assert destination in manifest['python_integration']
                new = ast.parse((ROOT / destination).read_text())
                found = next(n for n in new.body if getattr(n, 'name', None) == name)
                assert ast.dump(found) == ast.dump(originals[name]), (source, name, 'integration test changed')
    script = json.loads((ROOT / 'package.json').read_text())['scripts']['test:js'].split()
    for file in manifest['js_integration'] + manifest['js_units']:
        assert (ROOT / file).is_file() and file in script, file
