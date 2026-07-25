def normalize_minmax(value: float, minimum: float, maximum: float) -> float:
    """Normalize a value into the unit interval."""
    if maximum == minimum:
        return 0.0
    return (value - minimum) / (maximum - minimum)
