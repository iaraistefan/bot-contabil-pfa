"""
Teste pentru comanda /sumar_test (Faza 3 PAS 5) — gardă owner-only.

Handler async; folosim fake Update/Context minimale. Verifică:
- non-owner / owner nesetat -> refuz, nimic trimis
- owner -> execută și trimite sumarul (DOAR lui), fără summary_sent
"""

from types import SimpleNamespace

import pytest

import bot_contabil
import db
from app.models import User, SummarySent
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


class FakeMsg:
    def __init__(self):
        self.replies = []
    async def reply_text(self, text, **kw):
        self.replies.append(text)


class FakeBot:
    def __init__(self):
        self.sent = []
    async def send_message(self, chat_id, text, **kw):
        self.sent.append((chat_id, text))


def _update(uid, msg, chat_id=999):
    return SimpleNamespace(
        effective_user=SimpleNamespace(id=uid),
        effective_chat=SimpleNamespace(id=chat_id),
        message=msg,
    )


@pytest.mark.asyncio
async def test_gard_non_owner_refuz(monkeypatch):
    monkeypatch.setattr(bot_contabil.settings, "owner_telegram_id", 111)
    msg = FakeMsg()
    bot = FakeBot()
    await bot_contabil.handle_sumar_test(_update(222, msg), SimpleNamespace(bot=bot))
    assert msg.replies == ["Comandă indisponibilă."]
    assert bot.sent == []                  # nimic trimis


@pytest.mark.asyncio
async def test_gard_owner_nesetat_inert(monkeypatch):
    monkeypatch.setattr(bot_contabil.settings, "owner_telegram_id", None)
    msg = FakeMsg()
    bot = FakeBot()
    await bot_contabil.handle_sumar_test(_update(222, msg), SimpleNamespace(bot=bot))
    assert msg.replies == ["Comandă indisponibilă."]
    assert bot.sent == []


@pytest.mark.asyncio
async def test_owner_executa_si_trimite(monkeypatch, tmp_path):
    monkeypatch.setattr(bot_contabil.settings, "owner_telegram_id", 777)

    eng = create_engine(f"sqlite:///{(tmp_path / 't.db').as_posix()}")
    User.metadata.create_all(eng)
    Session = sessionmaker(bind=eng)
    monkeypatch.setattr(bot_contabil, "get_session", lambda: Session())
    s = Session()
    s.add(User(telegram_id=777))
    s.commit()
    s.close()

    # build_summary_for_user mock -> mesaj fix
    monkeypatch.setattr(bot_contabil.sched_service, "build_summary_for_user",
                        lambda *a, **k: "SUMAR-PREVIEW")

    msg = FakeMsg()
    bot = FakeBot()
    await bot_contabil.handle_sumar_test(_update(777, msg), SimpleNamespace(bot=bot))

    assert bot.sent and bot.sent[0][1] == "SUMAR-PREVIEW"   # trimis owner-ului
    # preview NU scrie summary_sent
    s = Session()
    assert s.query(SummarySent).count() == 0
    s.close()


@pytest.mark.asyncio
async def test_owner_luna_goala_mesaj_clar(monkeypatch, tmp_path):
    monkeypatch.setattr(bot_contabil.settings, "owner_telegram_id", 888)

    eng = create_engine(f"sqlite:///{(tmp_path / 't.db').as_posix()}")
    User.metadata.create_all(eng)
    Session = sessionmaker(bind=eng)
    monkeypatch.setattr(bot_contabil, "get_session", lambda: Session())
    s = Session()
    s.add(User(telegram_id=888))
    s.commit()
    s.close()

    monkeypatch.setattr(bot_contabil.sched_service, "build_summary_for_user",
                        lambda *a, **k: None)   # lună goală

    msg = FakeMsg()
    bot = FakeBot()
    await bot_contabil.handle_sumar_test(_update(888, msg), SimpleNamespace(bot=bot))

    assert bot.sent == []                          # nimic trimis
    assert msg.replies and "nimic de sumarizat" in msg.replies[0]
