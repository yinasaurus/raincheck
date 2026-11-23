"""Re-export the chain errors defined next to the client."""

from chain.client import ChainRevert, ChainUnavailable

__all__ = ["ChainRevert", "ChainUnavailable"]
