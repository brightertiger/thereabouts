"""Domain errors; each is a `ValueError`, so existing handlers and tests still apply."""


class ConfigError(ValueError):
    """Configuration or policy files that cannot drive a run."""


class InputIntegrityError(ValueError):
    """An input artifact is missing, malformed or disagrees with its record."""


class PolicyViolation(ValueError):
    """Outputs break a declared policy or quality gate."""


class ArtifactIntegrityError(ValueError):
    """A written artifact failed its own verification."""
