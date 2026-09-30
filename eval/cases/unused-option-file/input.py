RENDERERS = {"html": lambda text: f"<p>{text}</p>"}


def render(text, fmt="html", theme=None, strategy_registry=None):
    """Render text in the given format."""
    return RENDERERS[fmt](text)
