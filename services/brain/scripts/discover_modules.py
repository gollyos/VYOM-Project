"""
VYOM Module Discovery Script
Finds the actual location of key modules across the codebase.
"""
import sys
sys.path.insert(0, 'services/brain')

from pathlib import Path
brain = Path('services/brain/app')

# Find actual file locations for modules that failed
modules_to_find = [
    'gemini', 'openai', 'briefing', 'morning',
    'phase18', 'local_alpha', 'research_engine',
    'crm_engine', 'phase8', 'personal_os',
    'financial_intelligence', 'paper_trade',
    'brain_graph', 'memory_manager',
    'telegram_gateway', 'whatsapp',
    'browser_agent', 'routing', 'quota'
]

print("FILE SEARCH RESULTS:")
print("=" * 70)
for keyword in modules_to_find:
    matches = list(brain.rglob(f'*{keyword}*.py'))
    if matches:
        for m in matches[:3]:
            loc = len(m.read_text(errors='ignore').splitlines())
            print(f"  [{loc:>5} LOC] {m.relative_to(brain)}")
    else:
        print(f"  [NOT FOUND] *{keyword}*")

print("\nPROVIDERS DIR:")
prov = brain / 'providers'
if prov.exists():
    for f in prov.iterdir():
        if f.suffix == '.py':
            loc = len(f.read_text(errors='ignore').splitlines())
            print(f"  [{loc:>5} LOC] providers/{f.name}")
else:
    print("  providers/ dir missing")
