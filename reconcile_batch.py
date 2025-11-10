
import pandas as pd, os
# Example script - user should adapt paths and mapping
orders = pd.read_csv(os.environ.get("ORDERS_CSV_PATH"))
payments = pd.read_csv(os.environ.get("PAYMENTS_CSV_PATH"))
# Basic reconcile using simple merge - adapt mapping
orders['__id__'] = orders['Sub Order No'].astype(str).str.strip()
payments['__id__'] = payments['Packet Id'].astype(str).str.strip()
merged = pd.merge(orders, payments, left_on='__id__', right_on='__id', how='outer', indicator=True)
merged.to_csv("reconcile_result.csv", index=False)
print("Reconcile output saved to reconcile_result.csv")
