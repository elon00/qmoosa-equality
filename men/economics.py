"""Integer-only planning. This module does not mint or transfer funds."""
ALLOCATION_BPS = {'community_grants': 5000, 'social_enterprises': 2500,
                  'public_goods': 1500, 'operations': 1000}

def allocate(amount: int) -> dict[str, int]:
    if type(amount) is not int or amount < 0:
        raise ValueError('amount must be nonnegative integer base units')
    result = {k: amount * bps // 10000 for k, bps in ALLOCATION_BPS.items()}
    result['community_grants'] += amount - sum(result.values())
    return result

def issuance_budget(previous_supply: int, annual_bps: int, funded_units: int) -> int:
    for value in (previous_supply, annual_bps, funded_units):
        if type(value) is not int or value < 0:
            raise ValueError('nonnegative integers required')
    if annual_bps > 500:
        raise ValueError('proposed annual dilution ceiling is 5%')
    return min(previous_supply * annual_bps // 10000, funded_units)
