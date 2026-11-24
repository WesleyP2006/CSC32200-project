class NoveltyError(Exception):
    """Any rule violation or missing resource. The GUI shows str(e) and carries on."""


class Unavailable(NoveltyError):
    """Ollama (or a camera/microphone) is missing. Only the feature that needs it stops working (SR-08)."""
