with open(r'C:\Users\HP\Desktop\YAPAY ZEKA\multimodal-studio\backend\ai_agent.py', 'r', encoding='utf-8') as f:
    content = f.read()

old = 'logger = logging.getLogger("nexus-agent-v6")\n\n# ============================================================\n# CALCULATOR TOOL (Safe Math Evaluation)\n# ============================================================'
new = '''logger = logging.getLogger("nexus-agent-v6")

# Import Brain
from brain import get_brain, NexusBrain

# Import RAG System
try:
    from rag_system import rag_add_document, rag_search, rag_list_documents, rag_delete_document, rag_get_stats
    RAG_AVAILABLE = True
except ImportError as e:
    logger.warning(f"RAG system not available: {e}")
    RAG_AVAILABLE = False

# ============================================================
# CALCULATOR TOOL (Safe Math Evaluation)
# ============================================================'''

if old in content:
    content = content.replace(old, new)
    with open(r'C:\Users\HP\Desktop\YAPAY ZEKA\multimodal-studio\backend\ai_agent.py', 'w', encoding='utf-8') as f:
        f.write(content)
    print('Replaced successfully!')
else:
    print('NOT FOUND')
    idx = content.find('logger = logging.getLogger')
    print(repr(content[idx:idx+150]))