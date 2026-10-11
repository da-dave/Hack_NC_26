from __future__ import annotations

import os
import re
from pathlib import Path
from typing import List, Optional

import pandas as pd
from pydantic import BaseModel, Field
from google import genai
from google.genai import types
from dotenv import load_dotenv


load_dotenv()

DATA_DIR = Path(__file__).parent / "data"
PANTRIES_CSV = DATA_DIR / "pantries.csv"
INVENTORY_CSV = DATA_DIR / "inventory.csv"

# Change this if your Gemini account exposes a different model.
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")

def gemini_parse(message:str):

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "GEMINI_API_KEY is not set. "
            "Set it before running search.py."
        )

    client = genai.Client(api_key=api_key)

    prompt = f"""

"""
