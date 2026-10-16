"""
LLM Tool Specifications for NEXUS-CORE
======================================
OpenAI-format TOOLS list passed to the LLM.
Extracted from ai_agent.py (Phase 3.2 modularization).
"""

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "generate_code",
            "description": "Generate production-ready code. Use when user asks for code, API, script, function, or programming help.",
            "parameters": {
                "type": "object",
                "properties": {
                    "prompt": {
                        "type": "string",
                        "description": "What code to generate (natural language)"
                    },
                    "language": {
                        "type": "string",
                        "enum": ["python", "javascript", "typescript", "go", "rust", "bash", "sql"],
                        "description": "Programming language"
                    },
                    "mode": {
                        "type": "string",
                        "enum": ["api", "script"],
                        "description": "api for REST APIs/frameworks, script for simple standalone code"
                    }
                },
                "required": ["prompt"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "generate_visual_prompt",
            "description": "Generate professional AI art prompt (Midjourney v6, Stable Diffusion, DALL-E 3). Use when user asks for image, visual, picture, or art.",
            "parameters": {
                "type": "object",
                "properties": {
                    "subject": {
                        "type": "string",
                        "description": "Detailed subject description (anatomy, texture, materials)"
                    },
                    "environment": {
                        "type": "string",
                        "description": "Lighting and environment terms (volumetric lighting, golden hour, studio softbox)"
                    },
                    "camera": {
                        "type": "string",
                        "description": "Camera and lens specifications (35mm, f/1.8, depth of field)"
                    },
                    "style": {
                        "type": "string",
                        "enum": ["cinematic", "realistic", "conceptual", "minimalist", "anime", "photorealistic"],
                        "description": "Visual style"
                    }
                },
                "required": ["subject", "environment", "camera"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "generate_image",
            "description": "Generate ACTUAL IMAGE FILE using free Pollinations.ai API (Flux, DALL-E, Midjourney styles). Use when user wants a real image, photo, artwork generated and displayed. Returns direct image URL.",
            "parameters": {
                "type": "object",
                "properties": {
                    "prompt": {
                        "type": "string",
                        "description": "Image description in English (detailed, artistic). Example: 'A cyberpunk cityscape at night, neon lights, rain, photorealistic, 8k'"
                    },
                    "width": {
                        "type": "integer",
                        "description": "Width in pixels (256-2048)",
                        "default": 1024
                    },
                    "height": {
                        "type": "integer",
                        "description": "Height in pixels (256-2048)",
                        "default": 1024
                    },
                    "model": {
                        "type": "string",
                        "enum": ["flux", "gptimage", "dall-e", "midjourney", "turbo"],
                        "description": "AI model to use",
                        "default": "flux"
                    },
                    "seed": {
                        "type": "integer",
                        "description": "Optional seed for reproducibility"
                    },
                    "enhance": {
                        "type": "boolean",
                        "description": "Auto-enhance prompt",
                        "default": True
                    }
                },
                "required": ["prompt"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "generate_video_prompt",
            "description": "Generate cinematic video AI prompt (Google Veo, OpenAI Sora, Runway Gen-3). Use when user asks for video, film, scene, or motion.",
            "parameters": {
                "type": "object",
                "properties": {
                    "timecode": {
                        "type": "string",
                        "description": "Timecode range like [00:00 - 00:05]"
                    },
                    "camera_movement": {
                        "type": "string",
                        "description": "Camera movement technique (FPV drone dive, dolly zoom, orbit shot)"
                    },
                    "motion_dynamics": {
                        "type": "string",
                        "description": "Motion description (speed, direction, physics)"
                    },
                    "video_model": {
                        "type": "string",
                        "enum": ["veo", "sora", "runway", "luma"],
                        "description": "Target video AI model"
                    }
                },
                "required": ["timecode", "camera_movement", "motion_dynamics"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "generate_real_video",
            "description": "Generate an ACTUAL video file (MP4) from text description. Use when user wants to CREATE/MAKE a video, not just get a prompt. Takes ~20-30 seconds. Free via Pollinations.ai.",
            "parameters": {
                "type": "object",
                "properties": {
                    "prompt": {
                        "type": "string",
                        "description": "Detailed description of the video content"
                    },
                    "duration": {
                        "type": "integer",
                        "description": "Video duration in seconds (1-15, default 5)"
                    },
                    "style": {
                        "type": "string",
                        "enum": ["cinematic", "realistic", "anime", "artistic", "minimal"],
                        "description": "Visual style of the video"
                    },
                    "width": {
                        "type": "integer",
                        "description": "Video width in pixels (default 1280)"
                    },
                    "height": {
                        "type": "integer",
                        "description": "Video height in pixels (default 720)"
                    }
                },
                "required": ["prompt"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_learning",
            "description": "Search past experiences and learned lessons. Use to find previous solutions or patterns.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "What to search for"
                    },
                    "category": {
                        "type": "string",
                        "enum": ["code", "visual", "video", "all"],
                        "description": "Filter by category"
                    }
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Search the web for current information, news, documentation, or facts.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query"
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum number of results (default 8)",
                        "default": 8
                    }
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "calculate",
            "description": "Evaluate mathematical expressions safely. Supports +, -, *, /, //, %, **, parentheses, and functions like sqrt, sin, cos, log, abs, round, min, max, pi, e. Use for math, calculations, unit conversions.",
            "parameters": {
                "type": "object",
                "properties": {
                    "expression": {
                        "type": "string",
                        "description": "Mathematical expression to evaluate. Examples: '2 + 2', 'sqrt(16)', 'sin(pi/2)', '(100 * 1.5) / 2', 'log10(1000)'"
                    }
                },
                "required": ["expression"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "answer_question",
            "description": "Answer a general knowledge question directly without using tools.",
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "The question to answer"
                    }
                },
                "required": ["question"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "rag_add_document",
            "description": "Add a document to the knowledge base for future retrieval. Use when user wants to save information, code, notes, or references.",
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {
                        "type": "string",
                        "description": "Document content to store (text, code, notes, etc.)"
                    },
                    "title": {
                        "type": "string",
                        "description": "Document title",
                        "default": ""
                    },
                    "category": {
                        "type": "string",
                        "enum": ["general", "code", "visual", "video", "research", "documentation"],
                        "description": "Document category for organization",
                        "default": "general"
                    },
                    "source": {
                        "type": "string",
                        "description": "Source of the information",
                        "default": "user"
                    },
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Tags for easier searching"
                    }
                },
                "required": ["content"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "rag_search",
            "description": "Search the knowledge base for relevant documents using semantic search. Use when user asks about previously stored information, needs context from saved documents, or wants to find related content.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query - what to search for in the knowledge base"
                    },
                    "n_results": {
                        "type": "integer",
                        "description": "Number of results to return (default 5)",
                        "default": 5
                    },
                    "category": {
                        "type": "string",
                        "enum": ["general", "code", "visual", "video", "research", "documentation"],
                        "description": "Filter by document category"
                    }
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "rag_list_documents",
            "description": "List all documents in the knowledge base. Use to see what documents are stored.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "rag_delete_document",
            "description": "Delete a document from the knowledge base. Use when user wants to remove stored information.",
            "parameters": {
                "type": "object",
                "properties": {
                    "doc_id": {
                        "type": "string",
                        "description": "Document ID to delete"
                    }
                },
                "required": ["doc_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "rag_get_stats",
            "description": "Get knowledge base statistics (total documents, chunks, etc.).",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    # ===== AGENT TOOLS (OpenCode-style) =====
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read the contents of a file from the project directory. Use when user wants to see, analyze, or understand a file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Relative path to the file (e.g., 'src/main.py', 'README.md')"
                    },
                    "start_line": {
                        "type": "integer",
                        "description": "Start line number (1-based, optional)"
                    },
                    "end_line": {
                        "type": "integer",
                        "description": "End line number (optional)"
                    }
                },
                "required": ["path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Write content to a file. Creates new files or overwrites existing ones. Use when user wants to create or save a file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Relative path to the file (e.g., 'src/main.py', 'README.md')"
                    },
                    "content": {
                        "type": "string",
                        "description": "The content to write to the file"
                    },
                    "append": {
                        "type": "boolean",
                        "description": "If true, append to file instead of overwriting"
                    }
                },
                "required": ["path", "content"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "edit_file",
            "description": "Edit a file by replacing specific text. Use when user wants to modify, fix, or update an existing file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Relative path to the file"
                    },
                    "old_text": {
                        "type": "string",
                        "description": "Exact text to find and replace"
                    },
                    "new_text": {
                        "type": "string",
                        "description": "Replacement text"
                    }
                },
                "required": ["path", "old_text", "new_text"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": "List files and directories in a folder. Use when user wants to see project structure or find files.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Directory path (relative). Use '.' for root, 'src' for src folder, etc."
                    },
                    "recursive": {
                        "type": "boolean",
                        "description": "If true, list files recursively"
                    }
                },
                "required": ["path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_files",
            "description": "Search for text pattern in files. Use when user wants to find code, text, or references across the project.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Text or pattern to search for"
                    },
                    "file_type": {
                        "type": "string",
                        "description": "Filter by file extension (e.g., '.py', '.js'). Leave empty for all files."
                    },
                    "path": {
                        "type": "string",
                        "description": "Directory to search in (relative). Use '.' for root."
                    }
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "execute_command",
            "description": "Execute a shell command (bash/powershell). Use when user wants to run scripts, install packages, start servers, or perform terminal operations.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "The command to execute"
                    },
                    "timeout": {
                        "type": "integer",
                        "description": "Timeout in seconds (default 30)"
                    }
                },
                "required": ["command"]
            }
        }
    }
]


