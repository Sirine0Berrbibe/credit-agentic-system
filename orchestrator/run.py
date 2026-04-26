#!/usr/bin/env python
"""
Simple entry point - Run from project root
"""
import sys
import os
import uvicorn
from dotenv import load_dotenv

# Add current directory to path for relative imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
load_dotenv()

if __name__ == "__main__":
    reload_enabled = os.getenv("UVICORN_RELOAD", os.getenv("DEBUG", "false")).lower() == "true"
    uvicorn.run(
        "src.main:app",
        host=os.getenv("SERVICE_HOST", "0.0.0.0"),
        port=int(os.getenv("SERVICE_PORT", "8001")),
        reload=reload_enabled,
    )
