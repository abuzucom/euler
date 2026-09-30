def coupon_code(user):
    code = user.profile.coupon.strip().upper()
    if user.profile is None or user.profile.coupon is None:
        return ""
    return code


def shipping_fee(weight_kg):
    if weight_kg <= 0:
        raise ValueError("weight must be positive")
    if weight_kg < 0:
        return 0
    return round(weight_kg * 1.5, 2)
