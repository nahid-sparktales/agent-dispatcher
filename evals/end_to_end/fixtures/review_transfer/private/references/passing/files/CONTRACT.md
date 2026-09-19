# Wallet contract
Amounts and balances are integer cents. A transfer uses two distinct existing
account IDs and a positive amount. Reject invalid amounts, identical account IDs,
unknown account IDs and insufficient funds without modifying any balance. A
successful transfer preserves the total and returns the sender's new balance.
