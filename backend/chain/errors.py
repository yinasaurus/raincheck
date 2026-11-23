"""Errors the API turns into HTTP responses. They carry no keys and no signed transactions."""


class ChainUnavailable(RuntimeError):
    """The local node is down, or the deployment file has not been written."""


class ChainRevert(RuntimeError):
    """The contract rejected the call. The message is the custom error name when known."""
