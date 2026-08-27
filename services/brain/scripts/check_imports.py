import sys
sys.path.insert(0, 'services/brain')

checks = [
    ('GoogleProvider',   'from app.providers.google import GoogleProvider'),
    ('QuotaBudgeter',    'from app.routing.quota_budgeter import QuotaBudgeter'),
    ('MemoryManager',    'from app.memory.manager import MemoryManager'),
    ('PaperBroker',      'from app.trading.paper_broker import PaperBroker'),
    ('DeepResearchTask', 'from app.research.orchestrator import DeepResearchTask'),
    ('Phase8Engine',     'from app.phase8.engine import Phase8Engine'),
    ('RuntimeExecutor',  'from app.runtime.executor import Executor'),
    ('BrainGraph',       'from app.brain_graph.graph_engine import GraphEngine'),
    ('TaskCheckpoint',   'from app.reliability.checkpoints import TaskCheckpoint'),
    ('CRMEngine',        'from app.crm.engine import CRMEngine'),
    ('WhatsAppTool',     'from app.tools_builtin.whatsapp_tool import WhatsAppTool'),
    ('SystemTool',       'from app.tools_builtin.system import SystemTool'),
    ('WikipediaTool',    'from app.tools_builtin.wikipedia_tool import WikipediaTool'),
    ('NewsTool',         'from app.tools_builtin.news_tool import NewsTool'),
    ('DynamicMatcher',   'from app.tools.dynamic_matcher import get_tool_matcher'),
    ('ToolCatalog335',   'from app.tools.catalog_300 import ALL_300_TOOLS, count_tools'),
]

for name, stmt in checks:
    try:
        exec(stmt)
        print(f'  OK    {name}')
    except Exception as e:
        print(f'  FAIL  {name}  ->  {str(e)[:70]}')
