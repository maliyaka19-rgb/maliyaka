"""
Web Tools for NEXUS-CORE
========================
SafeCalculator + free web search (DuckDuckGo HTML scraping, SerpAPI fallback).
Extracted from ai_agent.py (Phase 3.2 modularization).
"""
import ast
import operator
import math
import re
import json
import time
import html
import logging
from typing import Dict, List, Optional, Any

import httpx

try:
    from bs4 import BeautifulSoup
    BS4_AVAILABLE = True
except ImportError:
    BS4_AVAILABLE = False

logger = logging.getLogger("nexus-agent-v6")

# ============================================================
# CALCULATOR TOOL (Safe Math Evaluation)
# ============================================================

import ast
import operator
import math

class SafeCalculator:
    """Safe mathematical expression evaluator using AST parsing."""
    
    # Supported operators
    BINARY_OPS = {
        ast.Add: operator.add,
        ast.Sub: operator.sub,
        ast.Mult: operator.mul,
        ast.Div: operator.truediv,
        ast.FloorDiv: operator.floordiv,
        ast.Mod: operator.mod,
        ast.Pow: operator.pow,
    }
    
    UNARY_OPS = {
        ast.UAdd: operator.pos,
        ast.USub: operator.neg,
    }
    
    # Allowed functions
    FUNCTIONS = {
        'abs': abs,
        'round': round,
        'min': min,
        'max': max,
        'sum': sum,
        'pow': pow,
        # Math module functions
        'sqrt': math.sqrt,
        'sin': math.sin,
        'cos': math.cos,
        'tan': math.tan,
        'log': math.log,
        'log10': math.log10,
        'exp': math.exp,
        'ceil': math.ceil,
        'floor': math.floor,
        'pi': math.pi,
        'e': math.e,
    }
    
    def evaluate(self, expr: str) -> Dict[str, Any]:
        """Safely evaluate a mathematical expression."""
        try:
            # Parse expression
            tree = ast.parse(expr, mode='eval')
            result = self._eval_node(tree.body)
            return {"success": True, "result": result, "expression": expr}
        except SyntaxError:
            return {"success": False, "error": "Geçersiz matematik ifadesi", "expression": expr}
        except ZeroDivisionError:
            return {"success": False, "error": "Sıfıra bölme hatası", "expression": expr}
        except Exception as e:
            return {"success": False, "error": f"Hesaplama hatası: {str(e)}", "expression": expr}
    
    def _eval_node(self, node: ast.AST) -> Any:
        """Recursively evaluate AST node."""
        if isinstance(node, ast.Constant):  # Python 3.8+
            if isinstance(node.value, (int, float)):
                return node.value
            raise ValueError("Sadece sayısal sabitler izin verilir")
        
        elif isinstance(node, ast.BinOp):
            left = self._eval_node(node.left)
            right = self._eval_node(node.right)
            op_type = type(node.op)
            if op_type in self.BINARY_OPS:
                return self.BINARY_OPS[op_type](left, right)
            raise ValueError(f"Desteklenmeyen operatör: {op_type}")
        
        elif isinstance(node, ast.UnaryOp):
            operand = self._eval_node(node.operand)
            op_type = type(node.op)
            if op_type in self.UNARY_OPS:
                return self.UNARY_OPS[op_type](operand)
            raise ValueError(f"Desteklenmeyen unary operatör: {op_type}")
        
        elif isinstance(node, ast.Call):
            # Function call
            if isinstance(node.func, ast.Name):
                func_name = node.func.id
                if func_name in self.FUNCTIONS:
                    func = self.FUNCTIONS[func_name]
                    args = [self._eval_node(arg) for arg in node.args]
                    kwargs = {kw.arg: self._eval_node(kw.value) for kw in node.keywords}
                    return func(*args, **kwargs)
            raise ValueError(f"Desteklenmeyen fonksiyon: {getattr(node.func, 'id', 'unknown')}")
        
        elif isinstance(node, ast.Name):
            # Constants like pi, e
            if node.id in self.FUNCTIONS:
                val = self.FUNCTIONS[node.id]
                if isinstance(val, (int, float)):
                    return val
            raise ValueError(f"Bilinmeyen isim: {node.id}")
        
        elif isinstance(node, ast.List):
            return [self._eval_node(item) for item in node.elts]
        
        elif isinstance(node, ast.Tuple):
            return tuple(self._eval_node(item) for item in node.elts)
        
        else:
            raise ValueError(f"Desteklenmeyen ifade türü: {type(node).__name__}")

# Global calculator instance
CALCULATOR = SafeCalculator()


# ============================================================
# WEB SEARCH (DuckDuckGo HTML Scraping - Free, No API Key)
# ============================================================

async def web_search_duckduckgo(query: str, max_results: int = 8) -> List[Dict[str, str]]:
    """
    Perform web search using DuckDuckGo HTML scraping.
    Free, no API key required, returns title, url, snippet.
    """
    import httpx
    from bs4 import BeautifulSoup
    
    try:
        # DuckDuckGo HTML endpoint
        url = "https://html.duckduckgo.com/html/"
        params = {"q": query, "kl": "tr-tr"}  # Turkish locale
        
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "tr-TR,tr;q=0.9,en;q=0.8",
        }
        
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            resp = await client.post(url, data=params, headers=headers)
            resp.raise_for_status()
            
            soup = BeautifulSoup(resp.text, "html.parser")
            
            # Parse results - DuckDuckGo uses .result__body class
            results = []
            for result in soup.select(".result__body"):
                title_elem = result.select_one(".result__title")
                snippet_elem = result.select_one(".result__snippet")
                url_elem = result.select_one(".result__url")
                
                if title_elem:
                    title = title_elem.get_text(strip=True)
                    url_link = title_elem.select_one("a")
                    url = url_link.get("href") if url_link else ""
                    
                    snippet = ""
                    if snippet_elem:
                        snippet = snippet_elem.get_text(strip=True)[:300]
                    
                    if title and url:
                        results.append({
                            "title": title,
                            "url": url,
                            "snippet": snippet
                        })
                
                if len(results) >= max_results:
                    break
            
            return results
            
    except Exception as e:
        logger.warning(f"DuckDuckGo search failed: {e}")
        return []


async def web_search_serpapi(query: str, max_results: int = 8) -> List[Dict[str, str]]:
    """
    Perform web search using SerpAPI (requires SERPAPI_KEY in .env).
    More reliable but requires API key (free tier: 100 searches/month).
    """
    import httpx
    
    api_key = os.getenv("SERPAPI_KEY", "")
    if not api_key:
        return []
    
    try:
        url = "https://serpapi.com/search"
        params = {
            "q": query,
            "api_key": api_key,
            "engine": "google",
            "gl": "tr",
            "hl": "tr",
            "num": max_results
        }
        
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()
            
            results = []
            for item in data.get("organic_results", [])[:max_results]:
                results.append({
                    "title": item.get("title", ""),
                    "url": item.get("link", ""),
                    "snippet": item.get("snippet", "")[:300]
                })
            return results
            
    except Exception as e:
        logger.warning(f"SerpAPI search failed: {e}")
        return []


async def web_search_unified(query: str, max_results: int = 8) -> List[Dict[str, str]]:
    """
    Unified web search: tries SerpAPI first (if key available), falls back to DuckDuckGo.
    """
    # Try SerpAPI first if key is configured
    if os.getenv("SERPAPI_KEY"):
        results = await web_search_serpapi(query, max_results)
        if results:
            return results
    
    # Fallback to DuckDuckGo
    return await web_search_duckduckgo(query, max_results)


