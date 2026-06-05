"""
Setup global pentru teste.

Modulele care importa lantul `config` (ex. app.services.tax_engine ->
app.models -> config) instantiaza Settings() la import, care cere variabile
de mediu obligatorii (telegram_token, openai_api_key). Pentru teste punem
valori dummy. setdefault: nu suprascrie un env real daca exista.
"""

import os

os.environ.setdefault("TELEGRAM_TOKEN", "test-telegram-token")
os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")
os.environ.setdefault("ENV", "test")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test_data.db")
