class DomainError(Exception):
    """Base class for expected domain-rule failures."""


class InvalidTopicTransition(DomainError):
    """Raised when a topic lifecycle transition is not allowed."""


class InvalidDecision(DomainError):
    """Raised when an AI decision fails domain validation."""
