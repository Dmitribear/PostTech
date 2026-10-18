class JanaUnavailable(Exception):
    """A model, configuration or local knowledge dependency is unavailable."""


class JanaBusy(JanaUnavailable):
    """Temporary bounded inference queue saturation, distinct from an outage."""
