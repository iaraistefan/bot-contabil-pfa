"""Import de extrase bancare (PDF/CSV) → format neutru BankTxn.

Granița curată: fiecare parser de bancă (bt_parser, viitor ing_parser etc.)
scoate ACELAȘI BankTxn; conducta (upload → preview → ...) nu depinde de bancă.
"""
