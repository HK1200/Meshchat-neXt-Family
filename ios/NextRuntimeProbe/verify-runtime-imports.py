"""Reject known local runtime imports omitted from the actual staged app.

External wheels and embedded C modules retain their own checks. This checks the
project's Python helpers, including imports inside deferred feature functions.
"""
import ast
from pathlib import Path
import sys

# This worker is reached only by the Android branch. The iOS Radio owner uses
# network_only and _open_network_radio, whose native bridge supplies pacing.
ANDROID_ONLY = {('family_radios', 'family_radio_pacing')}


def verify(staged, source_roots):
    staged = Path(staged)
    known = {path.stem for root in source_roots for path in Path(root).glob('*.py')}
    modules = {path.stem: path for path in staged.glob('*.py')}
    missing = []
    for name, path in sorted(modules.items()):
        tree = ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
        for node in ast.walk(tree):
            imported = []
            if isinstance(node, ast.Import):
                imported = [alias.name.split('.')[0] for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                imported = [(node.module or '').split('.')[0]]
            elif (isinstance(node, ast.Call) and node.args
                  and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)
                  and (isinstance(node.func, ast.Name) and node.func.id == '__import__'
                       or isinstance(node.func, ast.Attribute) and node.func.attr == 'import_module')):
                imported = [node.args[0].value.split('.')[0]]
            for dependency in imported:
                if (dependency in known and dependency not in modules
                        and (name, dependency) not in ANDROID_ONLY):
                    missing.append(f'{name}.py:{node.lineno}: {dependency}.py')
    if missing:
        raise ValueError('Required local runtime helpers are not packaged: ' + '; '.join(sorted(set(missing))))
    return len(modules)


if __name__ == '__main__':
    count = verify(Path(sys.argv[1]), [Path(value) for value in sys.argv[2:]])
    print(f'Checked local imports in {count} staged runtime modules')
