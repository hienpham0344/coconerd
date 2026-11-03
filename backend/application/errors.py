"""Business errors independent of transport and persistence."""


class ChannelNotAllowedError(Exception):
    """The guild or channel is disabled for message ingestion."""


class NotFound(Exception):
    """The requested resource does not exist in the supplied scope."""


class Conflict(Exception):
    """The current resource state prevents the requested operation."""


class InvalidTransition(Exception):
    """The supplied operation parameters are invalid."""
