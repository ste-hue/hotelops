"""Data contracts — fail fast when input schemas change."""


class SchemaViolationError(Exception):
    """Raised when input data does not match the expected column schema."""


def validate_columns(
    found: list[str] | set[str],
    required: set[str],
    context: str,
) -> None:
    """Raise SchemaViolationError if any required column is missing.

    Args:
        found: Column names present in the data.
        required: Column names that must be present.
        context: Human-readable label for error messages
                 (e.g. "Sella CSV gennaio.csv").
    """
    missing = required - set(found)
    if missing:
        raise SchemaViolationError(
            f"{context}: missing columns {sorted(missing)}"
        )
