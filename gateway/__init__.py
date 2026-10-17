"""Gateway package — Core Operations for CLL1 Control Center."""

from gateway.server import run_gateway
from pathlib import Path

def main():
    """Entry point for gateway - uses project root as base_dir."""
    base_dir = str(Path(__file__).resolve().parent.parent)
    run_gateway(base_dir)

__all__ = ["main", "run_gateway"]
