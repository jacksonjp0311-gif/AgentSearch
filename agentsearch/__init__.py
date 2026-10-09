"""AgentSearch: a portable, explicit-scope search tool for agent harnesses."""
from ._version import VERSION as __version__

from .config import SearchConfig
from .engine import SearchEngine

__all__ = ["SearchConfig", "SearchEngine", "__version__"]
