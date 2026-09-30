"""Order total helpers."""

TAX_RATE = 0.0825


def order_subtotal(prices: list[float]) -> float:
    """Return the sum of line prices."""
    return sum(prices)


def average_price(prices: list[float]) -> float:
    """Return the mean line price, or 0.0 for an empty order."""
    if not prices:
        return 0.0
    return order_subtotal(prices) / len(prices)


def order_total(prices: list[float]) -> float:
    """Return the subtotal plus sales tax."""
    return order_subtotal(prices) * (1 + TAX_RATE)
