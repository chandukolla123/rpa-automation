"""Pytest configuration — adds project root to sys.path."""
import sys
from pathlib import Path

# Ensure the rpa_invoice_system package root is on sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))
