"""
NEXUS-CORE v6.0 - TRUE AI AGENT
================================
Real AI Agent with LLM reasoning, tool use, and conversation memory.
Works like ChatGPT but with specialized multimodal tools.

Architecture:
- LLM Core: OpenAI GPT-4 / GPT-3.5 / any compatible API
- Tools: Code Gen, Visual Gen, Video Gen, Web Search, Learning
- Memory: Conversation history + Long-term learning
- Agent Loop: Plan → Act → Observe → Reflect
"""

import json
import time
import uuid
import os
import re
import urllib.parse
from datetime import datetime
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field, asdict
from collections import deque
import logging
import asyncio
import httpx

# Load .env file
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# OpenAI SDK (or any compatible LLM API)
try:
    import openai
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False

logger = logging.getLogger("nexus-agent-v6")

# Import Brain
from brain import get_brain, NexusBrain

# Import RAG System
try:
    from rag_system import rag_add_document, rag_search, rag_list_documents, rag_delete_document, rag_get_stats
    RAG_AVAILABLE = True
except ImportError as e:
    logger.warning(f"RAG system not available: {e}")
    RAG_AVAILABLE = False


# ---- Modular components (Phase 3.2) ----
from web_tools import SafeCalculator, web_search_duckduckgo, web_search_serpapi, web_search_unified
from tools_spec import TOOLS
from memory import Message, Conversation, ConversationMemory, LearningMemory
from tool_executor import ToolExecutor

# ============================================================
# LLM CONFIGURATION
# ============================================================

@dataclass
class LLMConfig:
    """LLM provider configuration."""
    provider: str = "openai"  # openai, anthropic, local
    model: str = "gpt-4"
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    temperature: float = 0.7
    max_tokens: int = 4096
    streaming: bool = False


# ============================================================
# TOOL DEFINITIONS (Function Calling Format)
# ============================================================

# These are the tools available to the LLM

# ============================================================
# MAIN AI AGENT (LLM-POWERED)
# ============================================================

def _validate_response(data: Dict) -> bool:
    """Validate LLM response structure. Returns True if valid."""
    try:
        if not isinstance(data, dict):
            return False
        choices = data.get("choices")
        if not isinstance(choices, list) or len(choices) == 0:
            return False
        for choice in choices:
            if not isinstance(choice, dict):
                return False
            message = choice.get("message")
            if not isinstance(message, dict):
                return False
            if message.get("role") != "assistant":
                return False
            # tool_calls validation if present
            tool_calls = message.get("tool_calls")
            # OpenAI-uyumlu sağlayıcılar (ör. Groq gpt-oss-120b), asistan yalnızca
            # araç çağrısı ürettiğinde "content" alanını tamamen atlar (null bile
            # göndermez). Bu GEÇERLİ bir yanıttır → content veya tool_calls'ten en
            # az biri bulunmalıdır. (Aksi halde geçerli araç çağrıları reddedilip
            # gereksiz fallback zinciri tetikleniyordu.)
            if tool_calls is None and "content" not in message:
                return False
            if tool_calls is not None:
                if not isinstance(tool_calls, list):
                    return False
                for tc in tool_calls:
                    if not isinstance(tc, dict):
                        return False
                    if tc.get("type") != "function":
                        return False
                    func = tc.get("function")
                    if not isinstance(func, dict):
                        return False
                    if not isinstance(func.get("name"), str) or not isinstance(func.get("arguments"), str):
                        return False
        return True
    except Exception:
        return False


# How many times to retry the SAME provider/model after a 429 (rate limit)
# before falling back to other models/providers.
# Dusuk tut: uzun bekleme yerine fallback zinciri (diger modeller/saglayicilar) calsin.
_RATE_LIMIT_MAX_RETRIES = 1
_MAX_RATE_LIMIT_WAIT = 5.0  # saniye - Retry-After uzun donse bile kisitla


def _parse_retry_after(response, default: float = 20.0) -> float:
    """Extract a sane wait time (seconds) from a 429 response.

    Prefers the ``Retry-After`` header; falls back to parsing Groq/OpenAI-style
    messages such as "Please try again in 12.5s" or "in 1m30s". Sleeps are
    capped so a bad value can never hang the request for minutes.
    """
    try:
        header = response.headers.get("retry-after") or response.headers.get("Retry-After")
        if header:
            try:
                return max(1.0, min(float(header), 90.0))
            except (TypeError, ValueError):
                pass
    except Exception:
        pass
    try:
        body = response.text or ""
    except Exception:
        body = ""
    m = re.search(r"try again in\s+(\d+)m([\d.]+)s", body, re.IGNORECASE)
    if m:
        return max(1.0, min(int(m.group(1)) * 60 + float(m.group(2)) + 1.0, 120.0))
    m = re.search(r"try again in\s+([\d.]+)\s*s", body, re.IGNORECASE)
    if m:
        return max(1.0, min(float(m.group(1)) + 1.0, 90.0))
    return default


class NexusAIAgent:
    """
    True AI Agent powered by LLM.
    Understands natural language, selects tools, generates responses.
    """
    
    def __init__(self, llm_config: LLMConfig = None):
        """Auto-detect best available FREE LLM provider."""
        # Check all free providers in priority order
        groq_key = os.getenv("GROQ_API_KEY", "")
        gemini_key = os.getenv("GEMINI_API_KEY", "") or os.getenv("GOOGLE_AI_KEY", "")
        openrouter_key = os.getenv("OPENROUTER_API_KEY", "")
        together_key = os.getenv("TOGETHER_API_KEY", "")
        openai_key = os.getenv("OPENAI_API_KEY", "")
        
        # Validate keys (not placeholder)
        def is_valid(key: str) -> bool:
            return key and not key.startswith("your-") and not key.startswith("sk-placeholder") and len(key) > 10
        
        # Priority: Groq (free, fast) > Gemini (free tier) > Together > OpenRouter > OpenAI
        if is_valid(groq_key):
            api_key, base_url, model, provider = groq_key, "https://api.groq.com/openai/v1", "openai/gpt-oss-120b", "groq"
        elif is_valid(gemini_key):
            api_key, base_url, model, provider = gemini_key, "https://generativelanguage.googleapis.com/v1beta/openai/", "gemini-1.5-flash", "gemini"
        elif is_valid(together_key):
            api_key, base_url, model, provider = together_key, "https://api.together.xyz/v1", "meta-llama/Meta-Llama-3.1-70B-Instruct-Turbo", "together"
        elif is_valid(openrouter_key):
            api_key, base_url, model, provider = openrouter_key, "https://openrouter.ai/api/v1", "meta-llama/llama-3.1-70b-instruct:free", "openrouter"
        elif is_valid(openai_key):
            api_key, base_url, model, provider = openai_key, None, "gpt-4o-mini", "openai"
        else:
            api_key, base_url, model, provider = "sk-placeholder", None, "fallback", "fallback"
        
        self.llm_config = llm_config or LLMConfig(
            api_key=api_key, base_url=base_url, model=model
        )
        self.provider = provider
        logger.info(f"LLM Provider: {provider} | Model: {model}")
        
        # Initialize Brain for continuous learning
        self.brain = get_brain()
        
        self.memory = ConversationMemory(max_history=30)
        self.learning = LearningMemory()
        # Working directory for file operations (project root)
        working_dir = os.environ.get("NEXUS_WORKING_DIR", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        self.tools = ToolExecutor(working_dir=working_dir)
        self.system_prompt = self._build_system_prompt()
        # Per-chat tool allow-list (set from the active custom agent in chat()).
        # None/empty => advertise every tool.
        self._active_tools = None
    
    def _refresh_llm_config(self):
        """Refresh LLM config from model_config.json (latest active provider/model)."""
        try:
            from model_routes import _load_config, MODEL_CATALOG
            config = _load_config()
            active_provider = config.get("active_provider")
            active_model = config.get("active_model")
            if not active_provider or not active_model:
                return
            provider_info = MODEL_CATALOG.get(active_provider)
            if not provider_info:
                return
            api_key = config.get("api_keys", {}).get(active_provider, "") or os.getenv(provider_info["env_key"], "")
            if api_key and api_key not in ("sk-placeholder",):
                self.llm_config.api_key = api_key
                self.llm_config.base_url = provider_info["base_url"]
                self.llm_config.model = active_model
                self.provider = active_provider
        except Exception as e:
            logger.warning(f"Could not refresh LLM config: {e}")
    
    def _build_system_prompt(self, query: str = "") -> str:
        """Build the agent's system prompt with brain context."""
        brain_context = ""
        if query and hasattr(self, 'brain') and self.brain:
            brain_context = self.brain.get_context_for_llm(query)
            if brain_context and brain_context != "No prior learning context.":
                brain_context = f"\n\nBRAIN CONTEXT (learned from experience):\n{brain_context}\n"
        
        working_dir = getattr(self.tools, 'working_dir', 'current directory')
        
        return f"""You are NEXUS-CORE v6.1, an advanced AI coding agent with file system and command execution capabilities (like OpenCode/Cursor).
{brain_context}
You are working in: {working_dir}

## CORE CAPABILITIES

### 1. CODE ASSISTANT
- Generate production-ready code in any language
- Read, write, edit files in the project
- Search code across the project
- Execute shell commands
- Fix bugs, refactor code, add features

### 2. FILE OPERATIONS
- read_file: Read file contents (with line numbers)
- write_file: Create or overwrite files
- edit_file: Modify files by replacing text
- list_files: Explore project structure
- search_files: Find code/patterns across files

### 3. COMMAND EXECUTION
- execute_command: Run shell commands, scripts, install packages
- Can start servers, run tests, git operations, etc.

### 4. MULTIMODAL GENERATION
- generate_code: Create code from natural language
- generate_visual_prompt: AI art prompts (Midjourney, SD, DALL-E)
- generate_image: Generate ACTUAL IMAGE FILES using free Pollinations.ai (Flux, DALL-E, Midjourney styles). Returns direct image URL.
- generate_video_prompt: Cinematic video prompts (Veo, Sora, Runway)
- generate_real_video: Generate ACTUAL MP4 video files from text (~20s, free)

### 5. KNOWLEDGE & RESEARCH
- web_search: Search the web for current information
- search_learning: Search past interactions for patterns
- answer_question: Answer general knowledge questions

## REASONING FRAMEWORK (Chain of Thought)

Think through problems step-by-step before acting:

1. **UNDERSTAND** - What is the user really asking? What's the goal?
2. **PLAN** - What steps are needed? Which tools in what order?
3. **EXECUTE** - Use tools systematically, one at a time
4. **OBSERVE** - Analyze tool results, adjust if needed
5. **REFLECT** - Review the outcome, verify correctness
6. **RESPOND** - Provide clear, complete answer

## RULES

- Always respond in the SAME LANGUAGE as the user (Turkish if user writes Turkish, English if English)
- Be thorough but concise
- When editing files, show the user what you changed
- After edits, run tests or verify if appropriate
- For file operations, always use relative paths from the working directory
- Show file paths when discussing files
- Use markdown for code blocks
- When running commands, show the output
- If something fails, debug and fix it
- **Think before you act** - Complex tasks need planning
- **COMPLETE MULTI-STEP TASKS**: When the user asks for a multi-step deliverable (create a project, write several files, build a site/app), do ALL the steps with tools BEFORE answering. Do NOT stop after a single tool call, and do NOT merely describe what could be done — actually create/edit every required file, then verify (list files / run the command) and only then report.
- Never leave a task half-finished. If a tool returns an error, diagnose it and retry with a corrected call instead of giving up.
- Write file contents IN FULL — never abbreviate with "..." or placeholders.

## EXAMPLE WORKFLOW

User: "Fix the bug in main.py where login fails"

1. **Understand**: User wants login bug fixed in main.py
2. **Plan**: Read file → Analyze → Edit → Test → Explain
3. **Execute**: 
   - read_file("main.py") - Find the login function
   - Analyze the code
   - edit_file("main.py", old_text="...", new_text="...") - Fix the bug
   - execute_command("python -c 'import main'") - Verify it works
4. **Reflect**: Did the fix work? Any side effects?
5. **Respond**: Explain the fix and verification

## SELF-REFLECTION GUIDELINES

After completing a task, ask yourself:
- Did I fully answer the user's question?
- Are there edge cases I missed?
- Is the solution robust and maintainable?
- Should I suggest improvements or alternatives?

When you need to use tools, call them. Work like a real coding assistant — read code before editing, test after changes."""

    async def chat(self, user_message: str, conversation_id: str = None, history: List[Dict] = None, agent_id: str = None, tools_override: List[str] = None, system_prefix: str = None) -> Dict:
        """
        Main chat interface. Processes user message through LLM with tool use.
        Records experience in brain for continuous learning.

        tools_override : adım-bazlı EN AZ YETKİ için araç allow-list'i ZORLAR
                         (Kodlama Yöneticisi kullanır; yazma adımında salt-okuma
                         araçlarına daraltılabilir).
        system_prefix  : sistem istemine eklenen kısa ön-ek (görev tanımı/rol).
        """
        import time
        start_time = time.time()
        
        # Resolve agent_id: auto selection or specific agent
        custom_system_prompt = None
        self._active_tools = None  # reset per chat; set below if a custom agent is used
        self._active_model = None

        if agent_id == "auto":
            try:
                from custom_agents import auto_select_agent
                agent_id = auto_select_agent(user_message)
            except Exception as e:
                logger.debug(f"Auto-select agent error: {e}")
                agent_id = None

        if agent_id:
            try:
                from custom_agents import get_agent
                custom_agent = get_agent(agent_id)
                if custom_agent:
                    custom_system_prompt = custom_agent.get("system_prompt")
                    self._active_tools = custom_agent.get("tools") or None
                    if custom_agent.get("model"):
                        self._active_model = custom_agent["model"]
            except Exception as e:
                logger.debug(f"Custom agent load error: {e}")

        # Adım-bazlı araç izni: Kodlama Yöneticisi en az yetki ilkesini böyle uygular.
        if tools_override is not None:
            self._active_tools = list(tools_override)
            if not self._active_tools:
                # Boş liste = hiçbir araç yok (kesinlikle yazma yapamaz).
                self._active_tools = []
        if system_prefix:
            custom_system_prompt = (
                (custom_system_prompt + "\n\n") if custom_system_prompt else ""
            ) + system_prefix
        
        # Get or create conversation
        if conversation_id is None:
            conversation_id = str(uuid.uuid4())[:12]
        
        conv = self.memory.get_or_create(conversation_id)
        
        # Build message history for LLM with DYNAMIC brain context
        if custom_system_prompt:
            # Build tool guidance strictly for active tools to prevent tool mismatch hallucinations
            available_set = set(self._active_tools) if self._active_tools else {t["function"]["name"] for t in TOOLS}
            tool_doc = {
                "read_file": "- read_file: Dosya oku",
                "write_file": "- write_file: Dosya yaz/oluştur",
                "edit_file": "- edit_file: Dosyada düzenle",
                "list_files": "- list_files: Klasör listele",
                "search_files": "- search_files: Dosyalarda ara",
                "execute_command": "- execute_command: Komut çalıştır",
                "generate_code": "- generate_code: Üretim hazır kod oluştur",
                "generate_image": "- generate_image: Gerçek görsel dosyası üret (URL döndürür)",
                "generate_visual_prompt": "- generate_visual_prompt: Midjourney/DALL-E/SD için görsel prompt",
                "generate_video_prompt": "- generate_video_prompt: Veo/Sora/Runway için video prompt",
                "generate_real_video": "- generate_real_video: Gerçek MP4 video dosyası oluştur (ücretsiz, ~20sn sürer)",
                "calculate": "- calculate: Güvenli matematiksel ve istatistiksel hesaplama yap",
                "rag_search": "- rag_search: Bilgi tabanındaki belgelerde semantik arama yap",
                "rag_add_document": "- rag_add_document: Bilgi tabanına belge ekle",
                "rag_list_documents": "- rag_list_documents: Bilgi tabanındaki belgeleri listele",
                "rag_delete_document": "- rag_delete_document: Bilgi tabanından belge sil",
                "rag_get_stats": "- rag_get_stats: Bilgi tabanı istatistiklerini getir",
                "web_search": "- web_search: Web'de güncel bilgi ara",
                "search_learning": "- search_learning: Geçmiş deneyimlerde ara",
                "answer_question": "- answer_question: Genel bilgi sorularını cevapla",
            }
            active_guides = [tool_doc[t] for t in available_set if t in tool_doc]
            tools_block = "\n".join(active_guides) if active_guides else "Özel bir araç atanmadı; doğrudan yanıt ver."

            system_prompt = custom_system_prompt + f"""

## KULLANILABİLİR ARAÇLARIN
{tools_block}

## GÖREV TAMAMLAMA PROTOKOLÜ (ÇOK ÖNEMLİ)

Kullanıcı çok adımlı bir görev verdiğinde (örn. "bir site hazırla", "3 dosya oluştur", "proje kur ve çalıştır"):

1. **PLANLA**: Görevi küçük, net adımlara böl. Kaç dosya/değişiklik gerektiğini belirle.
2. **TAMAMEN YÜRÜT**: Görev bitene kadar araçları sırayla çağır. Yalnızca sana atanmış araçları kullan; bu liste dışındaki araçları ÇAĞIRMA. **Tek bir araç çağrısından sonra DURMA.** İstenen TÜM adımları tamamla. Yarım bırakma.
3. **DOĞRULA**: Bitince sonucu kontrol et (dosyaları listele, çıktıyı incele).
4. **HATA OLURSA**: Araç hata verirse pes etme; hatanın nedenini bul, düzelt ve görevi sürdür.
5. **RAPORLA**: Ancak her şey bittikten sonra kullanıcıya ne yaptığını özetleyen net bir metin yanıt ver.

Kurallar:
- Sana atanmamış araçları asla çağırma.
- Görevi asla "yapılabilir" diye tarif edip bırakma — GERÇEKTEN YAP.
- Dosya içeriğini tam yaz; "..." ile kısaltma.
- Türkçe yanıt ver."""
        else:
            system_prompt = self._build_system_prompt(user_message)
        messages = [{"role": "system", "content": system_prompt}]
        
        # Add conversation history
        if history:
            messages.extend(history)
        else:
            stored = self.memory.get_history(conversation_id, include_system=False)
            messages.extend(stored[-10:])
        
        messages.append({"role": "user", "content": user_message})
        
        # Persist user message AFTER building the prompt to avoid duplication:
        # get_history() already returns stored messages, so adding it before the
        # prompt build made the current user message appear twice to the LLM.
        self.memory.add_message(conversation_id, Message(role="user", content=user_message))
        
        # Detect intent for brain recording
        intent = self._detect_intent(user_message)
        
        # Call LLM with tool use
        try:
            tools_used = []
            full_response = ""
            thinking_steps = []  # Track thinking process
            
            # Add initial thinking step
            thinking_steps.append({
                "type": "thinking",
                "content": f"Sorunuz analiz ediliyor: \"{user_message[:100]}\"",
                "icon": "🧠"
            })
            
            max_iterations = 25
            iteration = -1
            for iteration in range(max_iterations):
                llm_response = await self._call_llm(messages)

                if not llm_response.get("success") or "data" not in llm_response:
                    logger.warning(f"LLM call failed in iteration {iteration}: {llm_response.get('error', 'unknown')}")
                    continue

                response_data = llm_response["data"] or {}
                choices = response_data.get("choices", [])
                
                if not choices:
                    break
                
                choice = choices[0]
                message = choice.get("message", {})
                tool_calls = message.get("tool_calls", [])
                
                # If there's content alongside tool calls, add as thinking
                if message.get("content") and tool_calls:
                    thinking_steps.append({
                        "type": "reasoning",
                        "content": message["content"][:300],
                        "icon": "💭"
                    })
                
                if not tool_calls:
                    full_response = message.get("content", "")
                    break
                
                messages.append(message)
                
                # Derinlemesine savunma: executor'a etkin araç allow-list'ini ver.
                _allowed_tools = self._allowed_tool_names()
                for tool_call in tool_calls:
                    if not isinstance(tool_call, dict):
                        logger.warning("Skipping malformed tool_call (not a dict)")
                        continue
                    fn = tool_call.get("function") or {}
                    func_name = fn.get("name")
                    call_id = tool_call.get("id")
                    if not func_name or not call_id:
                        logger.warning(f"Skipping malformed tool_call (name={func_name!r}, id={call_id!r})")
                        continue
                    try:
                        raw_args = fn.get("arguments", "{}") or "{}"
                        func_args = json.loads(raw_args) if isinstance(raw_args, str) else (raw_args if isinstance(raw_args, dict) else {})
                    except json.JSONDecodeError:
                        logger.warning(f"Invalid JSON in tool args: {str(fn.get('arguments', ''))[:100]}")
                        func_args = {}
                    
                    # Add tool thinking step
                    tool_desc = self._get_tool_description(func_name, func_args)
                    thinking_steps.append({
                        "type": "tool",
                        "content": tool_desc,
                        "icon": self._get_tool_icon(func_name),
                        "tool": func_name
                    })
                    
                    tool_result = await self.tools.execute(func_name, func_args, allowed=_allowed_tools)
                    tools_used.append(func_name)
                    
                    # Add tool result summary
                    result_summary = self._summarize_tool_result(func_name, tool_result)
                    if result_summary:
                        thinking_steps.append({
                            "type": "result",
                            "content": result_summary,
                            "icon": "✅"
                        })
                    
                    messages.append({
                        "role": "tool",
                        "tool_call_id": call_id,
                        "content": json.dumps(tool_result, ensure_ascii=False)
                    })

                    # If a tool failed, nudge the model to RECOVER instead of
                    # silently continuing with a broken step (root cause of many
                    # half-finished multi-step tasks).
                    if isinstance(tool_result, dict) and tool_result.get("success") is False:
                        err = tool_result.get("error") or tool_result.get("message") or ""
                        messages.append({
                            "role": "user",
                            "content": (
                                f"[SİSTEM NOTU] '{func_name}' aracı hata verdi: {str(err)[:300]}. "
                                "Nedeni gider, gerekirse farklı bir yol dene ve görevi tamamla. "
                                "Kullanıcıya yarım bırakma."
                            )
                        })
                    
                    self.memory.add_message(conversation_id, Message(
                        role="assistant", content=message.get("content", ""), tool_calls=[tool_call]
                    ))
                    self.memory.add_message(conversation_id, Message(
                        role="tool", content=json.dumps(tool_result, ensure_ascii=False), tool_call_id=call_id
                    ))
            
            # If loop ended without a text response, make one final call WITHOUT tools
            if not full_response:
                try:
                    import httpx
                    # Get current config
                    api_key = self.llm_config.api_key
                    base_url = self.llm_config.base_url or "https://openrouter.ai/api/v1"
                    model = self.llm_config.model
                    provider = getattr(self, 'provider', 'openrouter')
                    
                    if api_key and api_key not in ("sk-placeholder", ""):
                        # Trim messages to avoid token limits (same safe window as _call_llm).
                        final_messages = self._safe_window(messages, max_messages=20)
                        final_messages.append({
                            "role": "user",
                            "content": f"Kullanıcının sorusu: {user_message}\n\nYukarıdaki tüm araç sonuçlarını analiz et ve kullanıcının sorusuna kapsamlı bir yanıt ver. Sadece metin yanıt ver, tool kullanma."
                        })
                        
                        payload = {
                            "model": model,
                            "messages": final_messages,
                            "temperature": 0.7,
                            "max_tokens": 4096
                        }
                        headers = {
                            "Authorization": f"Bearer {api_key}",
                            "Content-Type": "application/json"
                        }
                        if provider == "openrouter":
                            headers["HTTP-Referer"] = "http://localhost:8080"
                            headers["X-Title"] = "NEXUS-CORE"
                        
                        async with httpx.AsyncClient(timeout=90) as client:
                            resp = None
                            for attempt in range(_RATE_LIMIT_MAX_RETRIES + 1):
                                resp = await client.post(f"{base_url}/chat/completions", headers=headers, json=payload)
                                if resp.status_code != 429 or attempt >= _RATE_LIMIT_MAX_RETRIES:
                                    break
                                wait = min(_parse_retry_after(resp), _MAX_RATE_LIMIT_WAIT)
                                logger.warning(
                                    f"Final call rate limited (429); waiting {wait:.1f}s "
                                    f"before retry {attempt + 1}/{_RATE_LIMIT_MAX_RETRIES}"
                                )
                                await asyncio.sleep(wait)
                            if resp is not None and resp.status_code == 200:
                                data = resp.json()
                                choices = data.get("choices", [])
                                if choices:
                                    full_response = choices[0].get("message", {}).get("content", "")
                                    logger.info(f"Final response generated: {len(full_response)} chars")
                            else:
                                logger.warning(f"Final call failed: {resp.status_code if resp is not None else '?'}")
                except Exception as fe:
                    logger.warning(f"Final response generation failed: {fe}")
            
            # If still empty, provide a helpful message
            if not full_response:
                if tools_used:
                    full_response = f"Analiz tamamlandı. {len(tools_used)} araç kullanıldı. Sonuçlar işlendi ancak metin yanıt oluşturulamadı. Lütfen tekrar deneyin."
                else:
                    full_response = "Üzgünüm, bir yanıt üretemedim. Lütfen tekrar deneyin."
            
            # Add self-reflection step if we have a response
            if full_response and len(full_response) > 50:
                thinking_steps.append({
                    "type": "reflection",
                    "content": "Yanıt gözden geçirildi ve doğrulandı",
                    "icon": "✨"
                })
            
            # Store assistant response
            self.memory.add_message(conversation_id, Message(role="assistant", content=full_response))
            
            # Record in learning memory (legacy)
            self.learning.record(
                query=user_message[:200],
                tools_used=tools_used,
                success=bool(full_response),
                response_summary=full_response[:200]
            )
            
            # === BRAIN: Record experience for continuous learning ===
            latency_ms = int((time.time() - start_time) * 1000)
            self.brain.record_experience(
                user_query=user_message,
                intent_detected=intent,
                tools_used=tools_used,
                success=bool(full_response),
                response_summary=full_response[:300],
                latency_ms=latency_ms,
                tokens_used=0,  # Could be extracted from LLM response
                context={"conversation_id": conversation_id, "iterations": iteration + 1}
            )
            
            # Add final thinking step
            thinking_steps.append({
                "type": "complete",
                "content": "Yanıt hazırlanıyor...",
                "icon": "✨"
            })
            
            return {
                "success": True,
                "response": full_response,
                "conversation_id": conversation_id,
                "tools_used": tools_used,
                "iterations": iteration + 1,
                "thinking_steps": thinking_steps
            }
            
        except Exception as e:
            import traceback
            logger.error(f"Chat error: {e}\n{traceback.format_exc()}")
            
            # Record failed experience
            latency_ms = int((time.time() - start_time) * 1000)
            self.brain.record_experience(
                user_query=user_message,
                intent_detected=intent,
                tools_used=[],
                success=False,
                response_summary="",
                latency_ms=latency_ms,
                error=str(e)
            )
            
            return {"success": False, "error": str(e), "conversation_id": conversation_id}
    
    def _get_tool_description(self, func_name: str, args: dict) -> str:
        """Generate human-readable tool description in Turkish."""
        if func_name == "read_file":
            path = args.get("path", "")
            return f"📖 Dosya okunuyor: {path}"
        elif func_name == "write_file":
            path = args.get("path", "")
            return f"📝 Dosya yazılıyor: {path}"
        elif func_name == "edit_file":
            path = args.get("path", "")
            return f"✏️ Dosya düzenleniyor: {path}"
        elif func_name == "list_files":
            path = args.get("path", ".")
            return f"📁 Klasör listeleniyor: {path}"
        elif func_name == "search_files":
            pattern = args.get("pattern", "")
            return f"🔍 Aranıyor: \"{pattern}\""
        elif func_name == "execute_command":
            cmd = args.get("command", "")
            return f"⚙️ Komut çalıştırılıyor: {cmd[:50]}"
        elif func_name == "generate_image":
            prompt = args.get("prompt", "")[:60]
            return f"🖼️ Görsel üretiliyor: {prompt}..."
        elif func_name == "generate_visual_prompt":
            subject = args.get("subject", "")[:60]
            return f"🎨 Görsel prompt yazılıyor: {subject}..."
        elif func_name == "generate_real_video":
            return f"🎥 Video üretiliyor (MP4)..."
        elif func_name == "calculate":
            expr = args.get("expression", "")[:80]
            return f"🧮 Hesaplanıyor: {expr}"
        else:
            return f"🔧 Araç kullanılıyor: {func_name}"
    
    def _get_tool_icon(self, func_name: str) -> str:
        """Get icon for tool."""
        icons = {
            "read_file": "📖",
            "write_file": "📝",
            "edit_file": "✏️",
            "list_files": "📁",
            "search_files": "🔍",
            "execute_command": "⚙️",
            "generate_code": "💻",
            "generate_visual_prompt": "🎨",
            "generate_image": "🖼️",
            "generate_video_prompt": "🎬",
            "generate_real_video": "🎥",
            "web_search": "🌐",
            "search_learning": "🧠",
            "answer_question": "💬",
            "calculate": "🧮"
        }
        return icons.get(func_name, "🔧")
    
    def _summarize_tool_result(self, func_name: str, result: dict) -> str:
        """Summarize tool result for thinking display."""
        if not result.get("success"):
            return None
        
        try:
            if func_name == "list_files":
                items = result.get("items", [])
                dirs = sum(1 for i in items if i.get("type") == "directory")
                files = len(items) - dirs
                return f"{dirs} klasör, {files} dosya bulundu"
            
            elif func_name == "read_file":
                content = result.get("content", "")
                lines = content.count("\n") + 1
                return f"Dosya okundu: {lines} satır"
            
            elif func_name == "search_files":
                matches = result.get("matches", [])
                return f"{len(matches)} eşleşme bulundu"
            
            elif func_name in ("write_file", "edit_file"):
                return "İşlem başarılı"
            
            elif func_name == "execute_command":
                output = result.get("output", "")
                if output:
                    return f"Çıktı alındı ({len(output)} karakter)"
                return "Komut çalıştırıldı"
        
        except:
            pass
        
        return None
    
    def _detect_intent(self, query: str) -> str:
        """Detect intent category for brain recording."""
        q = query.lower()
        if any(kw in q for kw in ["kod", "code", "api", "script", "python", "javascript", "function", "hello world"]):
            return "code"
        if any(kw in q for kw in ["görsel", "visual", "midjourney", "resim", "prompt", "çizim"]):
            return "visual"
        if any(kw in q for kw in ["video", "film", "sahne", "veo", "sora", "runway", "sinematik"]):
            return "video"
        return "question"
    
    def _tools_payload(self) -> list:
        """Tool specs advertised to the LLM.

        When the active agent declares a tool allow-list we advertise ONLY those
        tools (this enforces the per-agent capability list instead of treating it
        as inert metadata). Falls back to all tools when the allow-list is empty
        or unknown so the agent is never left without tools.
        """
        allowed = getattr(self, "_active_tools", None)
        # None  => kısıt YOK (tüm araçlar).  []  => hiç araç YOK (en az yetki).
        if allowed is None:
            return list(TOOLS)
        if not isinstance(allowed, (list, tuple, set)):
            logger.warning(f"Invalid _active_tools type {type(allowed).__name__}; using full TOOLS")
            return list(TOOLS)
        if len(allowed) == 0:
            # Kodlama Yöneticisi salt-okuma adımlarında bunu kullanır: hiç araç yok.
            return []
        wanted = set(allowed)
        filtered = [t for t in TOOLS if t.get("function", {}).get("name") in wanted]
        if not filtered:
            unknown = sorted(wanted - {t.get("function", {}).get("name") for t in TOOLS})
            logger.warning(f"Agent tool allow-list matched nothing (unknown={unknown}); using full TOOLS")
            return list(TOOLS)
        return filtered

    def _allowed_tool_names(self) -> set:
        """executor'ın zorlayacağı etkin araç adları kümesi.

        _tools_payload() ile BİREBİR tutarlıdır: reklam edilen araç = izinli araç.
        None (kısıt yok) -> tüm araç adları; [] -> boş küme (hiç araç).
        """
        try:
            return {
                t.get("function", {}).get("name")
                for t in self._tools_payload()
                if t.get("function", {}).get("name")
            }
        except Exception as e:
            logger.warning(f"_allowed_tool_names hatası, kısıt uygulanmıyor: {e}")
            return set()

    def _safe_window(self, messages: List[Dict], max_messages: int = 20) -> List[Dict]:
        """Return a token-safe window of the conversation.

        Keeps the system message plus the most recent messages, advancing the
        cut point to a valid boundary (a user message or a plain assistant
        message) so we never start on an orphaned tool result — providers reject
        that. Also caps total characters so a few huge tool outputs cannot blow
        past the provider's per-request token limit (Groq free TPM = 8000; the
        tool specs alone already cost ~2.8k tokens).
        """
        if not messages:
            return messages
        # messages[0] is system in our chat() flow; tolerate missing system.
        if isinstance(messages[0], dict) and messages[0].get("role") == "system":
            system = messages[0]
            rest = messages[1:]
        else:
            system = None
            rest = list(messages)
        if len(rest) <= max_messages:
            window = list(rest)
        else:
            start = len(rest) - max_messages
            while start < len(rest):
                m = rest[start]
                role = m.get("role") if isinstance(m, dict) else None
                if role == "user":
                    break
                if role == "assistant" and not m.get("tool_calls"):
                    break
                start += 1
            window = list(rest[start:])

        def _msg_len(m) -> int:
            try:
                return len(json.dumps(m, ensure_ascii=False))
            except Exception:
                return len(str(m))

        # Truncate any single oversized turn (huge tool output) to ~8k chars.
        trimmed = []
        for m in window:
            if isinstance(m, dict) and isinstance(m.get("content"), str) and len(m["content"]) > 8000:
                m = dict(m)
                m["content"] = m["content"][:8000] + "\n…[kırpıldı: çok uzun çıktı]"
            trimmed.append(m)
        window = trimmed

        total = sum(_msg_len(m) for m in window)
        while len(window) > 2 and total > 28000:
            window.pop(0)
            while window:
                r0 = window[0].get("role") if isinstance(window[0], dict) else None
                if r0 == "user":
                    break
                if r0 == "assistant" and not window[0].get("tool_calls"):
                    break
                window.pop(0)
            total = sum(_msg_len(m) for m in window)
        # Never end on assistant(tool_calls) without its tool answers.
        while window:
            last = window[-1]
            if isinstance(last, dict) and last.get("role") == "assistant" and last.get("tool_calls"):
                window.pop()
            else:
                break
        # Never start on a tool message whose assistant call was cut off.
        while window and isinstance(window[0], dict) and window[0].get("role") == "tool":
            window.pop(0)
        return ([system] if system is not None else []) + window

    async def _call_llm(self, messages: List[Dict]) -> Dict:
        """Call the LLM API with tools. Comprehensive multi-provider, multi-model fallback + response validation."""
        import httpx
        import json as json_mod

        # Keep the request within provider token limits (see _safe_window).
        messages = self._safe_window(messages)
        
        # JSON Schema for response validation
        RESPONSE_SCHEMA = {
            "type": "object",
            "required": ["choices"],
            "properties": {
                "choices": {
                    "type": "array",
                    "minItems": 1,
                    "items": {
                        "type": "object",
                        "required": ["message"],
                        "properties": {
                            "message": {
                                "type": "object",
                                "required": ["role", "content"],
                                "properties": {
                                    "role": {"type": "string", "enum": ["assistant"]},
                                    "content": {"type": ["string", "null"]},
                                    "tool_calls": {
                                        "type": ["array", "null"],
                                        "items": {
                                            "type": "object",
                                            "required": ["id", "type", "function"],
                                            "properties": {
                                                "id": {"type": "string"},
                                                "type": {"type": "string", "enum": ["function"]},
                                                "function": {
                                                    "type": "object",
                                                    "required": ["name", "arguments"],
                                                    "properties": {
                                                        "name": {"type": "string"},
                                                        "arguments": {"type": "string"}
                                                    }
                                                }
                                            }
                                        }
                                    }
                                }
                            },
                            "finish_reason": {"type": ["string", "null"]}
                        }
                    }
                }
            }
        }
        
        # Always load latest config from model_config.json
        self._refresh_llm_config()
        
        api_key = self.llm_config.api_key
        base_url = self.llm_config.base_url or "https://api.openai.com/v1"
        model = getattr(self, '_active_model', None) or self.llm_config.model
        provider = getattr(self, 'provider', 'openai')
        
        # Check for placeholder or missing key
        if not api_key or api_key in ("sk-placeholder", "sk-your-openai-key-here") or provider == "fallback":
            logger.warning(f"No valid API key for {provider}, initiating fallback chain")
            return await self._fallback_chain(messages)
        
        try:
            async with httpx.AsyncClient(timeout=90) as client:
                # Handle different provider APIs
                if provider == "gemini":
                    payload = {
                        "model": model,
                        "messages": messages,
                        "tools": self._tools_payload(),
                        "tool_choice": "auto",
                        "temperature": self.llm_config.temperature,
                        "max_tokens": self.llm_config.max_tokens
                    }
                    url = f"{base_url}models/{model}:generateContent?key={api_key}"
                    headers = {"Content-Type": "application/json"}
                else:
                    payload = {
                        "model": model,
                        "messages": messages,
                        "tools": self._tools_payload(),
                        "tool_choice": "auto",
                        "temperature": self.llm_config.temperature,
                        "max_tokens": self.llm_config.max_tokens
                    }
                    url = f"{base_url}/chat/completions"
                    headers = {
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json"
                    }
                    if provider == "openrouter":
                        headers["HTTP-Referer"] = "http://localhost:8080"
                        headers["X-Title"] = "NEXUS-CORE"
                
                # Rate-limit aware retry: a 429 (e.g. Groq TPM limit) is TEMPORARY.
                # Bekleme sureini kisitla (_MAX_RATE_LIMIT_WAIT) ve cok deneme yapma;
                # fallback zinciri (diger modeller/saglayicilar) calsin.
                response = None
                for attempt in range(_RATE_LIMIT_MAX_RETRIES + 1):
                    response = await client.post(url, headers=headers, json=payload)
                    if response.status_code != 429 or attempt >= _RATE_LIMIT_MAX_RETRIES:
                        break
                    wait = min(_parse_retry_after(response), _MAX_RATE_LIMIT_WAIT)
                    logger.warning(
                        f"Rate limited (429) on {provider}/{model}; waiting "
                        f"{wait:.1f}s before retry {attempt + 1}/{_RATE_LIMIT_MAX_RETRIES}"
                    )
                    await asyncio.sleep(wait)

                if response is not None and response.status_code == 200:
                    data = response.json()
                    if provider == "gemini" and "candidates" in data:
                        data = self._normalize_gemini_response(data)
                    
                    # Validate response structure
                    if not _validate_response(data):
                        logger.warning(f"Invalid response structure from {provider}/{model}, triggering fallback")
                        return await self._fallback_chain(messages, failed_provider=provider, failed_model=model)
                    
                    return {"success": True, "data": data}
                
                # Some models (e.g. gpt-oss on Groq) occasionally emit a tool call
                # for a tool that was NOT advertised in request.tools (e.g.
                # `write_file`), and the provider rejects the whole turn with a 400
                # "Tool call validation failed". Retrying the SAME model once with
                # tools disabled turns this into a normal text answer instead of
                # burning the entire 20+ provider fallback chain.
                if (
                    response is not None
                    and response.status_code == 400
                    and provider != "gemini"
                    and "tool" in response.text.lower()
                    and ("validation failed" in response.text.lower()
                         or "not in request.tools" in response.text.lower())
                ):
                    logger.info(
                        f"Tool-call mismatch on {provider}/{model}; retrying same "
                        f"model with tools disabled"
                    )
                    retry_payload = {k: v for k, v in payload.items() if k not in ("tools", "tool_choice")}
                    try:
                        retry_resp = await client.post(url, headers=headers, json=retry_payload)
                        if retry_resp.status_code == 200:
                            retry_data = retry_resp.json()
                            if _validate_response(retry_data):
                                logger.info("Tool-disabled retry succeeded")
                                return {"success": True, "data": retry_data, "tools_disabled": True}
                        logger.warning(
                            f"Tool-disabled retry failed {retry_resp.status_code}: {retry_resp.text[:150]}"
                        )
                    except Exception as e:
                        logger.warning(f"Tool-disabled retry error: {e}")

                # Any error -> trigger fallback chain. If the failure was a pure
                # rate limit we keep this provider (its other models have separate
                # quota buckets) instead of dropping the only working provider.
                status = response.status_code if response is not None else "?"
                rate_limited = response is not None and response.status_code == 429
                detail = response.text[:200] if response is not None else "no response"
                logger.warning(f"LLM API error {status} from {provider}/{model}: {detail}")
                return await self._fallback_chain(
                    messages, failed_provider=provider, failed_model=model, rate_limited=rate_limited
                )
        
        except httpx.TimeoutException:
            logger.warning(f"Timeout calling {provider}/{model}")
            return await self._fallback_chain(messages, failed_provider=provider, failed_model=model)
        except httpx.ConnectError:
            logger.warning(f"Connection error to {provider}")
            return await self._fallback_chain(messages, failed_provider=provider, failed_model=model)
        except Exception as e:
            logger.warning(f"LLM call failed: {e}")
            return await self._fallback_chain(messages, failed_provider=provider, failed_model=model)
    
    async def _fallback_chain(self, messages: List[Dict], failed_provider: str = None, failed_model: str = None, rate_limited: bool = False) -> Dict:
        """
        Comprehensive fallback chain:
        1. Try other models from SAME provider (priority order)
        2. Try other providers in priority order (Groq > OpenRouter > Gemini > Together > OpenAI > Anthropic)
        3. Each provider tries its models in priority order
        4. Final fallback: rule-based agent

        ``rate_limited=True`` means the original provider only hit a 429 (temporary
        quota), so it is KEPT (and tried first): its other models have independent
        per-model quota buckets and usually succeed immediately.
        """
        from model_routes import MODEL_CATALOG, _is_valid_key, _load_config

        # Same token guard as the primary call: a 413 in fallback ends the task.
        messages = self._safe_window(messages)

        config = _load_config()
        api_keys = config.get("api_keys", {})
        
        # Provider priority order (free first, then paid)
        provider_priority = ["groq", "openrouter", "gemini", "together", "openai", "anthropic"]
        
        # A rate-limited provider is NOT removed from the chain: its sibling models
        # have separate limits, so we try it first. Only a hard failure drops it.
        if failed_provider:
            if rate_limited:
                provider_priority = [failed_provider] + [p for p in provider_priority if p != failed_provider]
            else:
                provider_priority = [p for p in provider_priority if p != failed_provider]
        
        for provider_id in provider_priority:
            provider_info = MODEL_CATALOG.get(provider_id)
            if not provider_info:
                continue
            
            # Get API key for this provider
            env_key = provider_info["env_key"]
            api_key = api_keys.get(provider_id) or os.getenv(env_key, "")
            
            if not _is_valid_key(api_key):
                logger.debug(f"Fallback: No valid key for {provider_id}")
                continue
            
            # Determine models to try for this provider
            models_to_try = []
            if provider_id == failed_provider and failed_model:
                # Try other models from the same provider first
                for m in provider_info["models"]:
                    if m["id"] != failed_model:
                        models_to_try.append(m["id"])
            else:
                # Try all models in provider priority order
                models_to_try = [m["id"] for m in provider_info["models"]]
            
            for model_id in models_to_try:
                try:
                    logger.info(f"Fallback trying: {provider_id}/{model_id}")
                    
                    async with httpx.AsyncClient(timeout=60) as client:
                        if provider_id == "gemini":
                            payload = {
                                "model": model_id,
                                "messages": messages,
                                "tools": self._tools_payload(),
                                "tool_choice": "auto",
                                "temperature": 0.7,
                                "max_tokens": 4096
                            }
                            url = f"{provider_info['base_url']}models/{model_id}:generateContent?key={api_key}"
                            headers = {"Content-Type": "application/json"}
                        else:
                            payload = {
                                "model": model_id,
                                "messages": messages,
                                "tools": self._tools_payload(),
                                "tool_choice": "auto",
                                "temperature": 0.7,
                                "max_tokens": 4096
                            }
                            url = f"{provider_info['base_url']}/chat/completions"
                            headers = {
                                "Authorization": f"Bearer {api_key}",
                                "Content-Type": "application/json"
                            }
                            if provider_id == "openrouter":
                                headers["HTTP-Referer"] = "http://localhost:8080"
                                headers["X-Title"] = "NEXUS-CORE"
                        
                        response = await client.post(url, headers=headers, json=payload)
                        
                        if response.status_code == 200:
                            data = response.json()
                            if provider_id == "gemini" and "candidates" in data:
                                data = self._normalize_gemini_response(data)
                            
                            # Validate response structure
                            if not _validate_response(data):
                                logger.warning(f"Invalid response structure from fallback {provider_id}/{model_id}, trying next model")
                                continue
                            
                            logger.info(f"Fallback SUCCESS: {provider_id}/{model_id}")
                            # Update active config for future calls
                            self.llm_config.api_key = api_key
                            self.llm_config.base_url = provider_info["base_url"]
                            self.llm_config.model = model_id
                            self.provider = provider_id
                            # Persist active model + keys (re-encrypted via _save_config).
                            # NOTE: _load_config() returns DECRYPTED keys, so we must
                            # re-encrypt on save (previously wrote plaintext to disk).
                            from model_routes import _save_config
                            config = _load_config()
                            config["active_provider"] = provider_id
                            config["active_model"] = model_id
                            _save_config(config)
                            return {"success": True, "data": data}
                        elif response.status_code == 429:
                            logger.warning(f"Rate limited on {provider_id}/{model_id}, trying next model")
                            continue  # Try next model
                        else:
                            logger.warning(f"Fallback failed {provider_id}/{model_id}: {response.status_code} - {response.text[:200]}")
                            continue
                            
                except httpx.TimeoutException:
                    logger.warning(f"Timeout on fallback {provider_id}/{model_id}")
                    continue
                except Exception as e:
                    logger.warning(f"Fallback error on {provider_id}/{model_id}: {e}")
                    continue
        
        # All fallbacks exhausted -> rule-based agent
        logger.warning("All LLM fallbacks exhausted, using rule-based fallback")
        return await self._fallback_response(messages)
    
    def _normalize_gemini_response(self, data: Dict) -> Dict:
        """Convert Gemini response to OpenAI format."""
        try:
            candidate = data["candidates"][0]
            content = candidate["content"]["parts"][0].get("text", "")
            return {
                "choices": [{
                    "message": {
                        "role": "assistant",
                        "content": content,
                        "tool_calls": None  # Gemini function calling format differs
                    }
                }]
            }
        except Exception:
            return data
    
    async def _fallback_response(self, messages: List[Dict]) -> Dict:
        """
        Fallback when no API key or LLM error.
        Rule-based agent enhanced with BRAIN predictions for smarter tool selection.
        """
        # Get last user message (keep original case for prompts)
        user_msg = ""
        for msg in reversed(messages):
            if msg.get("role") == "user":
                user_msg = msg.get("content", "")
                break
        
        # If a tool already ran in this loop, format its result
        for msg in reversed(messages):
            if msg.get("role") == "tool":
                try:
                    tool_data = json.loads(msg.get("content", "{}"))
                    if tool_data.get("success"):
                        if "code" in tool_data:
                            return self._llm_style(
                                f"İşte istediğiniz kod ({tool_data.get('language', 'python')}, "
                                f"{tool_data.get('mode', 'api')} modu):\n\n"
                                f"```{tool_data.get('language', 'python')}\n{tool_data['code']}\n```\n\n"
                                f"Bu kodu doğrudan kopyalayıp kullanabilirsiniz. Değişiklik ister misiniz?"
                            )
                        if "final_prompt" in tool_data:
                            return self._llm_style(
                                f"İşte oluşturduğum profesyonel prompt:\n\n"
                                f"```\n{tool_data['final_prompt']}\n```\n\n"
                                f"Bu prompt'u Midjourney, Stable Diffusion, DALL-E, Veo, Sora veya "
                                f"Runway'de doğrudan kullanabilirsiniz. Detay eklememi ister misiniz?"
                            )
                except Exception:
                    pass
        
        # --- BRAIN-ENHANCED Intent detection ---
        import re
        q = user_msg.lower()
        
        # Get brain predictions for this query
        brain_predictions = []
        if hasattr(self, 'brain') and self.brain:
            brain_predictions = self.brain.predict_best_tool(user_msg)
        
        def has_any(words):
            for w in words:
                if re.search(r"(?<![a-zçğıöşü])" + re.escape(w) + r"(?![a-zçğıöşü])", q):
                    return True
            return False
        
        # Strong keywords = explicitly names a tool/domain
        code_strong = ["kod", "code", "api", "script", "fonksiyon", "function", "program",
                       "python", "javascript", "typescript", "backend", "react", "component",
                       "fastapi", "flask", "express", "html", "css", "sql", "bash",
                       "hello world", "fibonacci", "sınf", "class", "endpoint", "rest"]
        visual_strong = ["görsel", "gorsel", "visual", "image", "resim", "midjourney",
                         "dall-e", "dalle", "stable diffusion", "çizim", "cizim", "poster",
                         "logo", "fotoğraf", "fotograf", "prompt"]
        video_strong = ["video", "film", "sahne", "scene", "timecode", "veo", "sora",
                        "runway", "sinematik", "cinematic", "trailer", "klip"]
        
        # Weak keywords = only count if no strong match
        code_weak = ["yaz", "yazdır", "oluştur", "olustur", "programla"]
        visual_weak = ["art", "tema", "çiz", "cyberpunk"]
        video_weak = ["lansman", "kamera hareket", "hareket"]
        
        is_code = has_any(code_strong)
        is_visual = has_any(visual_strong)
        is_video = has_any(video_strong)
        
        # BRAIN OVERRIDE: If brain strongly predicts a tool, trust it
        for tool, confidence in brain_predictions:
            if confidence > 0.75:
                if tool == "generate_code":
                    is_code = True
                elif tool == "generate_visual_prompt":
                    is_visual = True
                elif tool == "generate_video_prompt":
                    is_video = True
        
        if not (is_code or is_visual or is_video):
            if has_any(code_weak):
                is_code = True
            elif has_any(visual_weak):
                is_visual = True
            elif has_any(video_weak):
                is_video = True
        
        # Multi-tool: user wants more than one output
        if sum([is_code, is_visual, is_video]) >= 2:
            return await self._run_multi_tool(user_msg, q)
        
        if is_code:
            return await self._run_code_tool(user_msg, q)
        
        if is_visual:
            return await self._run_visual_tool(user_msg, q)
        
        if is_video:
            return await self._run_video_tool(user_msg, q)

        # Weather queries: use web search even in fallback
        if any(kw in q for kw in ["hava durumu", "hava nasıl", "hava nasil", "weather", "derece", "sıcaklık", "sicaklik", "yağmur", "yagmur", "kar", "rüzgâr", "ruzgar", "nem"]):
            try:
                results = await web_search_unified(user_msg, 3)
                if results:
                    snippets = []
                    for r in results:
                        snippet = r.get("snippet", "").strip()
                        if snippet:
                            snippets.append(snippet[:200])
                    if snippets:
                        combined = " | ".join(snippets[:3])
                        return self._llm_style(f"🌤️ **Hava durumu bilgisi (web araması):**\n\n{combined}\n\n*Kaynak: DuckDuckGo web araması*")
            except Exception:
                pass  # Fall through to generic answer

        # Question answering (rule-based knowledge)
        return self._llm_style(self._answer_question(user_msg))
    
    def _llm_style(self, content: str) -> Dict:
        """Wrap content in OpenAI-style response format."""
        return {
            "success": True,
            "data": {"choices": [{"message": {"content": content, "role": "assistant"}}]}
        }
    
    async def _run_code_tool(self, user_msg: str, q: str) -> Dict:
        """Autonomously pick language/mode and generate code."""
        language = "python"
        if any(kw in q for kw in ["javascript", " node", "npm", " js ", "js)", "react", "express"]):
            language = "javascript"
        elif "typescript" in q or " ts " in q:
            language = "typescript"
        elif any(kw in q for kw in ["bash", "shell", "terminal", "powershell"]):
            language = "bash"
        elif "sql" in q:
            language = "sql"
        elif "go " in q or "golang" in q:
            language = "go"
        
        # Script vs API mode detection
        simple_kw = ["hello world", "basit", "simple", "script", "yazdır", "yazdir", "print",
                     "fonksiyon", "function", "fibonacci", "faktöriyel", "ortalama", "çalıştır",
                     "standalone", "tek dosya", "component"]
        api_kw = ["api", "rest", "endpoint", "sunucu", "server", "backend", "fastapi", "flask",
                  "express", "django", "crud", "servis", "microservis"]
        
        mode = "script" if (any(kw in q for kw in simple_kw) and not any(kw in q for kw in api_kw)) else "api"
        framework = "script" if mode == "script" else "fastapi"
        if language == "javascript" and mode == "api":
            framework = "express"
        
        result = await self.tools.execute("generate_code", {
            "prompt": user_msg, "language": language,
            "framework": framework, "mode": mode
        })
        if result.get("success"):
            return self._llm_style(
                f"İşte istediğiniz kod ({language} • {mode.upper()} modu):\n\n"
                f"```{language}\n{result['code']}\n```\n\n"
                f"Bu kodu kopyalayıp doğrudan kullanabilirsiniz. Değişiklik veya yeni özellik ister misiniz?"
            )
        return self._llm_style(f"Kod oluşturulurken hata oluştu: {result.get('error', 'Bilinmeyen')}")
    
    async def _run_visual_tool(self, user_msg: str, q: str) -> Dict:
        """Build visual prompt params from natural language."""
        style = "cinematic"
        if any(kw in q for kw in ["anime", "manga"]): style = "anime"
        elif any(kw in q for kw in ["minimal", "sade"]): style = "minimalist"
        elif any(kw in q for kw in ["gerçekçi", "realistik", "foto", "photoreal"]): style = "photorealistic"
        elif any(kw in q for kw in ["concept", "konsept", "fantastik"]): style = "conceptual"
        
        result = await self.tools.execute("generate_visual_prompt", {
            "subject": user_msg,
            "environment": "cinematic lighting, atmospheric depth, detailed environment",
            "camera": "35mm lens, f/1.8, shallow depth of field, high detail",
            "style": style
        })
        if result.get("success"):
            return self._llm_style(
                f"Profesyonel görsel promptunuz hazır ({style} stil):\n\n"
                f"```\n{result['final_prompt']}\n```\n\n"
                f"Bu prompt'u Midjourney v6, Stable Diffusion XL veya DALL-E 3'te doğrudan kullanabilirsiniz. "
                f"Stil veya kompozisyon değişikliği ister misiniz?"
            )
        return self._llm_style(f"Görsel prompt oluşturulurken hata: {result.get('error', 'Bilinmeyen')}")
    
    async def _run_video_tool(self, user_msg: str, q: str) -> Dict:
        """Generate video prompt AND optionally create real video file."""
        video_model = "veo"
        if "sora" in q: video_model = "sora"
        elif "runway" in q: video_model = "runway"
        elif "luma" in q: video_model = "luma"

        # First generate the cinematic prompt
        result = await self.tools.execute("generate_video_prompt", {
            "timecode": "[00:00 - 00:05]",
            "camera_movement": "dynamic cinematic camera movement, smooth dolly motion",
            "motion_dynamics": user_msg,
            "video_model": video_model
        })

        if not result.get("success"):
            return self._llm_style(f"Video prompt oluşturulurken hata: {result.get('error', 'Bilinmeyen')}")

        # Check if user wants REAL video (not just prompt)
        wants_real_video = any(kw in q for kw in [
            "gerçek video", "real video", "video oluştur", "video üret",
            "video yap", "make video", "create video", "generate video",
            "video dosyası", "video file"
        ])

        if wants_real_video:
            # Generate actual video via backend
            try:
                import httpx
                async with httpx.AsyncClient(timeout=90.0) as client:
                    resp = await client.post(
                        f"{self.tools.backend_url}/api/v1/generate/real-video",
                        json={
                            "prompt": user_msg,
                            "duration": 5,
                            "width": 1280,
                            "height": 720
                        }
                    )
                    data = resp.json()

                if data.get("success"):
                    video_url = f"http://localhost:8000{data['video_url']}"
                    return self._llm_style(
                        f"🎬 **Gerçek video oluşturuldu!**\n\n"
                        f"📹 **Video:** [{data['video_id']}]({video_url})\n\n"
                        f"```html\n<video controls width=\"640\">\n  <source src=\"{video_url}\" type=\"video/mp4\">\n</video>\n```\n\n"
                        f"**Prompt:** {data['prompt'][:100]}...\n"
                        f"**Süre:** {data['duration']} saniye | "
                        f"**Çözünürlük:** {data['resolution']} | "
                        f"**Boyut:** {data['size_kb']} KB\n\n"
                        f"---\n\n"
                        f"**Sinematik Prompt (Veo/Sora için):**\n"
                        f"```\n{result['final_prompt']}\n```\n\n"
                        f"Videoyu indirmek için: [Videoyu İndir]({video_url})"
                    )
                else:
                    return self._llm_style(
                        f"⚠️ Video dosyası oluşturulamadı: {data.get('error', 'Bilinmeyen hata')}\n\n"
                        f"Ancak sinematik promptunuz hazır:\n\n"
                        f"```\n{result['final_prompt']}\n```\n\n"
                        f"Bu prompt'u Google Veo, OpenAI Sora veya Runway Gen-3'te kullanabilirsiniz."
                    )
            except Exception as e:
                return self._llm_style(
                    f"⚠️ Video oluşturma hatası: {str(e)}\n\n"
                    f"Sinematik promptunuz yine de hazır:\n\n"
                    f"```\n{result['final_prompt']}\n```\n\n"
                    f"Bu prompt'u harici video AI'larında kullanabilirsiniz."
                )
        else:
            # Just return the prompt (existing behavior)
            return self._llm_style(
                f"Sinematik video promptunuz hazır ({video_model} uyumlu):\n\n"
                f"```\n{result['final_prompt']}\n```\n\n"
                f"Bu prompt'u Google Veo, OpenAI Sora veya Runway Gen-3'te kullanabilirsiniz. "
                f"**Gerçek video dosyası** oluşturmamı ister misiniz? ('Video oluştur' yazın)"
            )
    
    async def _run_multi_tool(self, user_msg: str, q: str) -> Dict:
        """User wants multiple outputs - run tools in sequence."""
        sections = []
        tools_used = []
        
        if any(kw in q for kw in ["kod", "code", "api", "script", "python", "javascript"]):
            r = await self._run_code_tool(user_msg, q)
            sections.append(r["data"]["choices"][0]["message"]["content"])
            tools_used.append("generate_code")
        
        if any(kw in q for kw in ["görsel", "gorsel", "visual", "midjourney", "resim", "poster"]):
            r = await self._run_visual_tool(user_msg, q)
            sections.append(r["data"]["choices"][0]["message"]["content"])
            tools_used.append("generate_visual_prompt")
        
        if any(kw in q for kw in ["video", "film", "sahne", "sinematik"]):
            r = await self._run_video_tool(user_msg, q)
            sections.append(r["data"]["choices"][0]["message"]["content"])
            tools_used.append("generate_video_prompt")
        
        combined = f"**{len(sections)} çıktı oluşturdum:**\n\n" + "\n\n---\n\n".join(sections)
        return self._llm_style(combined)
    
    def _answer_question(self, query: str) -> str:
        """Rule-based question answering."""
        q = query.lower().strip()
        
        if any(kw in q for kw in ["merhaba", "selam", "hey", "naber", "nasılsın", "nasilsin"]):
            return ("Merhaba! Ben **NEXUS-CORE v6.0** yapay zeka ajanıyım. "
                    "Kod üretebilir, görsel/video prompt hazırlayabilir ve sorularınızı "
                    "yanıtlayabilirim. Nasıl yardımcı olabilirim?")
        
        if any(kw in q for kw in ["kimsin", "kimsin", "ne yapabilirsin", "neler yapabilirsin", "kendini tanıt"]):
            return ("Ben **NEXUS-CORE v6.0**'ım — çok modlu bir yapay zeka ajanıyım.\n\n"
                    "1. 💻 **Kod Üretimi** — Python, JavaScript, API'ler, scriptler\n"
                    "2. 🎨 **Görsel Prompt** — Midjourney v6, SDXL, DALL-E 3\n"
                    "3. 🎬 **Video Prompt** — Google Veo, Sora, Runway Gen-3\n"
                    "4. ❓ **Soru-Cevap** — Genel bilgi ve açıklama\n"
                    "5. 🧠 **Öğrenme** — Geçmiş görevlerden ders çıkarır\n\n"
                    "Doğal dille yazmanız yeterli — gerisini ben hallederim.")
        
        if "yapay zeka" in q and ("nedir" in q or "ne demek" in q):
            return ("**Yapay Zeka (AI)**, insan zekasını taklit eden sistemlerin genel adıdır. "
                    "Temel alt dalları:\n\n"
                    "- **Makine Öğrenmesi (ML)**: Verilerden öğrenen algoritmalar\n"
                    "- **Derin Öğrenme**: Sinir ağları ile karmaşık örüntü tanıma\n"
                    "- **Doğal Dil İşleme (NLP)**: İnsan dilini anlama ve üretme\n"
                    "- **Bilgisayarlı Görüntü**: Görselleri analiz etme\n\n"
                    "Bugün LLM'ler (Large Language Models) bu alanın en gelişmiş örneğidir.")
        
        if any(kw in q for kw in ["python nedir", "python ne"]):
            return ("**Python**, okunabilirliği yüksek, geniş kütüphane ekosistemine sahip "
                    "çok amaçlı bir programlama dilidir. Veri bilimi, yapay zeka, web "
                    "geliştirme (FastAPI, Django) ve otomasyon için yaygındır.")
        
        # Don't return a fallback that echoes the query
        # Instead, try to give a useful generic response
        return ("Üzgünüm, şu anda tam yanıt üretemiyorum. LLM API'sine erişimde sorun yaşıyorum. "
                "Lütfen biraz bekleyip tekrar deneyin veya farklı bir soru sorun.")


# ============================================================
# GLOBAL AGENT INSTANCE
# ============================================================

_agent_v6: Optional[NexusAIAgent] = None

def get_agent_v6(force_new: bool = False) -> NexusAIAgent:
    """Get or create global agent instance."""
    global _agent_v6
    if force_new or _agent_v6 is None:
        _agent_v6 = NexusAIAgent()
    return _agent_v6

def reset_agent_v6():
    """Force recreation of agent with fresh config."""
    global _agent_v6
    _agent_v6 = None
    return get_agent_v6()


async def chat(user_message: str, conversation_id: str = None, history=None, agent_id: str = None, tools_override: list = None, system_prefix: str = None) -> Dict:
    """Quick chat function."""
    agent = get_agent_v6()
    return await agent.chat(
        user_message, conversation_id, history=history, agent_id=agent_id,
        tools_override=tools_override, system_prefix=system_prefix,
    )


def get_agent_info() -> Dict:
    """Get agent information."""
    return {
        "name": "NEXUS-CORE v6.0",
        "type": "True AI Agent",
        "capabilities": [
            "Question Answering",
            "Code Generation",
            "Visual Prompt Generation",
            "Video Prompt Generation",
            "Web Search",
            "Learning"
        ],
        "tools": [t["function"]["name"] for t in TOOLS],
        "llm_model": "gpt-4"
    }