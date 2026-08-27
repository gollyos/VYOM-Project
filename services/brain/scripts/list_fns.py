import sys; sys.path.insert(0,'services/brain')
import ast, pathlib
tree = ast.parse(pathlib.Path('services/brain/app/execution/action_engine.py').read_text(encoding='utf-8', errors='ignore'))
fns = []
for node in ast.walk(tree):
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        fns.append((node.lineno, node.name))
fns.sort()
for lineno, name in fns[:50]:
    print(f'  L{lineno}: {name}')
