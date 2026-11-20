class DataError(Exception):
    """A source answered, but what it sent failed a check.

    The build then keeps that source's last good data and says so on the page,
    instead of publishing numbers it could not verify.
    """
