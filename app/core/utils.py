def get_seconds(
    *,
    seconds: int | None = None,
    minutes: int | None = None,
    hours: int | None = None,
    days: int | None = None,
) -> int:
    """
    Returns the total number of seconds represented by the given time components.
    """
    total_seconds = 0
    if seconds is not None:
        total_seconds += seconds
    if minutes is not None:
        total_seconds += minutes * 60
    if hours is not None:
        total_seconds += hours * 3600
    if days is not None:
        total_seconds += days * 86400
    return total_seconds
