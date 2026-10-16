"""
RAG (Retrieval-Augmented Generation) System for NEXUS-CORE
=========================================================
Vector database with sentence-transformers embeddings for document search.
Uses ChromaDB for storage and sentence-transformers for embeddings.
"""

import os
import json
import logging
import importlib.util
from pathlib import Path
from typing import List, Dict, Optional, Any
from datetime import datetime

logger = logging.getLogger("nexus-rag")

# Heavy optional dependencies (chromadb, sentence-transformers) are NOT imported
# at module load time. Importing them costs ~25s (torch/transformers chain) and
# would slow down every `import ai_agent`. Instead we cheaply check presence via
# find_spec() and perform the real import lazily on first use (G3 optimisation).
def _module_available(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False

CHROMA_AVAILABLE = _module_available("chromadb")
ST_AVAILABLE = _module_available("sentence_transformers")

if not CHROMA_AVAILABLE:
    logger.warning("chromadb not installed — RAG vector store disabled")
if not ST_AVAILABLE:
    logger.warning("sentence-transformers not installed — RAG embeddings disabled")

# ChromaDB persistence directory
CHROMA_DIR = os.path.join(os.path.dirname(__file__), "chroma_db")
COLLECTION_NAME = "nexus_documents"

# Embedding model
EMBEDDING_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"

# Global instances
_chroma_client = None
_embedding_model = None
_collection = None


def get_chroma_client():
    """Get or create ChromaDB client (lazy import of chromadb)."""
    global _chroma_client
    if _chroma_client is None:
        if not CHROMA_AVAILABLE:
            raise RuntimeError("chromadb paketi kurulu değil — RAG devre dışı")
        import chromadb  # lazy: avoid ~1s+ import at module load
        os.makedirs(CHROMA_DIR, exist_ok=True)
        _chroma_client = chromadb.PersistentClient(path=CHROMA_DIR)
    return _chroma_client


def get_embedding_model():
    """Get or create sentence transformer embedding model (lazy import)."""
    global _embedding_model
    if _embedding_model is None:
        if not ST_AVAILABLE:
            raise RuntimeError("sentence-transformers paketi kurulu değil — embedding devre dışı")
        import sentence_transformers  # lazy: avoid ~25s import at module load
        logger.info(f"Loading embedding model: {EMBEDDING_MODEL}")
        _embedding_model = sentence_transformers.SentenceTransformer(EMBEDDING_MODEL)
    return _embedding_model


def get_collection():
    """Get or create the document collection."""
    global _collection
    if _collection is None:
        client = get_chroma_client()
        _collection = client.get_or_create_collection(
            name=COLLECTION_NAME,
            metadata={"description": "NEXUS-CORE document knowledge base"}
        )
    return _collection


def chunk_text(text: str, chunk_size: int = 500, overlap: int = 50) -> List[str]:
    """Split text into overlapping chunks."""
    if len(text) <= chunk_size:
        return [text]
    
    chunks = []
    start = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        # Try to break at sentence boundary
        if end < len(text):
            last_period = text.rfind('.', start, end)
            last_newline = text.rfind('\n', start, end)
            boundary = max(last_period, last_newline)
            if boundary > start:
                end = boundary + 1
        
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        
        start = end - overlap
        if start >= len(text):
            break
    
    return chunks


def add_document(content: str, metadata: Dict = None, doc_id: str = None) -> Dict:
    """
    Add a document to the vector database.
    
    Args:
        content: Document text content
        metadata: Optional metadata (title, source, category, etc.)
        doc_id: Optional custom document ID
    
    Returns:
        Dict with success status and document info
    """
    try:
        collection = get_collection()
        model = get_embedding_model()
        
        # Generate document ID if not provided
        if doc_id is None:
            doc_id = f"doc_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{hash(content) % 10000}"
        
        # Chunk the document
        chunks = chunk_text(content)
        
        # Generate embeddings for all chunks
        embeddings = model.encode(chunks).tolist()
        
        # Prepare metadata for each chunk
        chunk_metadatas = []
        chunk_ids = []
        
        for i, chunk in enumerate(chunks):
            chunk_id = f"{doc_id}_chunk_{i}"
            chunk_ids.append(chunk_id)
            
            meta = metadata.copy() if metadata else {}
            meta.update({
                "doc_id": doc_id,
                "chunk_index": i,
                "total_chunks": len(chunks),
                "added_at": datetime.now().isoformat(),
            })
            chunk_metadatas.append(meta)
        
        # Add to collection
        collection.add(
            documents=chunks,
            embeddings=embeddings,
            metadatas=chunk_metadatas,
            ids=chunk_ids
        )
        
        logger.info(f"Added document {doc_id} with {len(chunks)} chunks")
        
        return {
            "success": True,
            "doc_id": doc_id,
            "chunks": len(chunks),
            "chunk_ids": chunk_ids
        }
        
    except Exception as e:
        logger.error(f"Add document failed: {e}")
        return {"success": False, "error": str(e)}


def search_documents(query: str, n_results: int = 5, filter_metadata: Dict = None) -> Dict:
    """
    Search for relevant document chunks using semantic similarity.
    
    Args:
        query: Search query text
        n_results: Number of results to return
        filter_metadata: Optional metadata filter (e.g., {"category": "code"})
    
    Returns:
        Dict with search results
    """
    try:
        collection = get_collection()
        model = get_embedding_model()
        
        # Generate query embedding
        query_embedding = model.encode(query).tolist()
        
        # Prepare where clause for metadata filtering
        where = filter_metadata if filter_metadata else None
        
        # Search
        results = collection.query(
            query_embeddings=[query_embedding],
            n_results=n_results,
            where=where,
            include=["documents", "metadatas", "distances"]
        )
        
        # Format results
        formatted_results = []
        if results["documents"] and results["documents"][0]:
            for i in range(len(results["documents"][0])):
                formatted_results.append({
                    "content": results["documents"][0][i],
                    "metadata": results["metadatas"][0][i],
                    "distance": results["distances"][0][i],
                    "similarity": 1 - results["distances"][0][i]  # Convert distance to similarity
                })
        
        return {
            "success": True,
            "query": query,
            "results": formatted_results,
            "count": len(formatted_results)
        }
        
    except Exception as e:
        logger.error(f"Search failed: {e}")
        return {"success": False, "error": str(e)}


def delete_document(doc_id: str) -> Dict:
    """Delete all chunks of a document."""
    try:
        collection = get_collection()
        # Get all chunk IDs for this doc_id
        results = collection.get(
            where={"doc_id": doc_id},
            include=["ids"]
        )
        
        if results["ids"]:
            collection.delete(ids=results["ids"])
            logger.info(f"Deleted document {doc_id} ({len(results['ids'])} chunks)")
            return {"success": True, "deleted_chunks": len(results["ids"])}
        
        return {"success": False, "error": "Document not found"}
        
    except Exception as e:
        logger.error(f"Delete document failed: {e}")
        return {"success": False, "error": str(e)}


def list_documents() -> Dict:
    """List all documents in the knowledge base."""
    try:
        collection = get_collection()
        results = collection.get(include=["metadatas"])
        
        # Group by doc_id
        docs = {}
        for meta in results["metadatas"]:
            doc_id = meta.get("doc_id")
            if doc_id and doc_id not in docs:
                docs[doc_id] = {
                    "doc_id": doc_id,
                    "title": meta.get("title", doc_id),
                    "category": meta.get("category", "general"),
                    "chunks": 0,
                    "added_at": meta.get("added_at")
                }
            if doc_id in docs:
                docs[doc_id]["chunks"] += 1
        
        return {
            "success": True,
            "documents": list(docs.values()),
            "count": len(docs)
        }
        
    except Exception as e:
        logger.error(f"List documents failed: {e}")
        return {"success": False, "error": str(e)}


def get_stats() -> Dict:
    """Get knowledge base statistics."""
    try:
        collection = get_collection()
        count = collection.count()
        
        # Get unique doc_ids
        results = collection.get(include=["metadatas"])
        doc_ids = set()
        for meta in results["metadatas"]:
            if meta.get("doc_id"):
                doc_ids.add(meta["doc_id"])
        
        return {
            "success": True,
            "total_chunks": count,
            "total_documents": len(doc_ids),
            "collection_name": COLLECTION_NAME
        }
    except Exception as e:
        logger.error(f"Get stats failed: {e}")
        return {"success": False, "error": str(e)}


# Tool functions for AI Agent
async def rag_add_document(content: str, title: str = "", category: str = "general", 
                          source: str = "user", tags: List[str] = None) -> Dict:
    """Tool: Add document to knowledge base."""
    metadata = {
        "title": title,
        "category": category,
        "source": source,
        "tags": tags or []
    }
    return add_document(content, metadata)


async def rag_search(query: str, n_results: int = 5, category: str = None) -> Dict:
    """Tool: Search knowledge base for relevant information."""
    filter_meta = {"category": category} if category else None
    return search_documents(query, n_results, filter_meta)


async def rag_list_documents() -> Dict:
    """Tool: List all documents in knowledge base."""
    return list_documents()


async def rag_delete_document(doc_id: str) -> Dict:
    """Tool: Delete document from knowledge base."""
    return delete_document(doc_id)


async def rag_get_stats() -> Dict:
    """Tool: Get knowledge base statistics."""
    return get_stats()


# NOT: Koleksiyon artık import anında DEĞİL, ilk kullanımda (get_collection)
# tembel olarak oluşturulur. Böylece `import rag_system` / `import ai_agent`
# ağır bağımlılıkları (chromadb, sentence-transformers) yüklemez (G3 optimizasyonu).