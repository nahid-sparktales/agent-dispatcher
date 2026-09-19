def transfer(balances, sender, recipient, amount):
    balances[sender] -= amount
    if amount <= 0:
        raise ValueError('amount must be positive')
    if balances[sender] < 0:
        raise ValueError('insufficient funds')
    balances[recipient] += amount
    return balances[sender]
