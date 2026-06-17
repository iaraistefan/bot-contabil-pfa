"""
#2-C — sync zilnic per-user + notificare „închiderea zilei" (confirm-first).

Generalizare run_bolt_daily_sync owner→per-user: iterează DOAR userii conectați
(bolt_client_id), izolare erori per-user, owner-env backward-compat. Confirm-first:
sync în cache + ping + buton OPȚIONAL; NU auto-postează.

Mock-uim API/DB — nu lovim Bolt real.
"""

from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.integrations import bolt_sync
from app.domain import crypto
from app.models import User


def _db(tmp_path, users):
    eng = create_engine(f"sqlite:///{(tmp_path / 'c.db').as_posix()}")
    User.metadata.create_all(eng)
    S = sessionmaker(bind=eng); s = S()
    for kw in users:
        s.add(User(**kw))
    s.commit(); s.close()
    return S


# ════════════════════════════════════════════════════════
# 1. Gate + generalizare: DOAR userii cu bolt_client_id
# ════════════════════════════════════════════════════════

def test_iterates_doar_userii_conectati(tmp_path, monkeypatch):
    S = _db(tmp_path, [
        {"telegram_id": 11, "bolt_client_id": "A", "bolt_client_secret_enc": "x"},  # conectat
        {"telegram_id": 12, "bolt_client_id": "B", "bolt_client_secret_enc": "y"},  # conectat
        {"telegram_id": 13},                                                        # NEconectat
    ])
    monkeypatch.setattr(bolt_sync, "get_session", lambda: S())
    monkeypatch.delenv("BOLT_OWNER_TELEGRAM_ID", raising=False)
    synced = []
    monkeypatch.setattr(bolt_sync, "_daily_sync_one", lambda token, u: synced.append(u.telegram_id))

    bolt_sync.run_bolt_daily_sync("tok")
    assert sorted(synced) == [11, 12]        # userul 13 (neconectat) NU e sincronizat


# ════════════════════════════════════════════════════════
# 2. Izolare erori per-user + notificări (confirm-first, fără auto-post)
# ════════════════════════════════════════════════════════

def test_izolare_erori_si_notificari(tmp_path, monkeypatch):
    S = _db(tmp_path, [
        {"telegram_id": 21, "bolt_client_id": "A", "bolt_client_secret_enc": "x"},  # OK
        {"telegram_id": 22, "bolt_client_id": "B", "bolt_client_secret_enc": "y"},  # crapă
    ])
    monkeypatch.setattr(bolt_sync, "get_session", lambda: S())
    monkeypatch.delenv("BOLT_OWNER_TELEGRAM_ID", raising=False)

    # client per-user „valid" (non-None) pentru ambii
    monkeypatch.setattr(bolt_sync, "bolt_client_for_user", lambda s, uid: SimpleNamespace())

    # collect_recent: OK pentru userul cu tg 21, crapă pentru 22 (chei revocate)
    def _collect(user_id, days=4, client=None):
        # mapăm user_id → telegram prin DB
        ss = S(); u = ss.get(User, user_id); tg = u.telegram_id; ss.close()
        if tg == 22:
            raise RuntimeError("401 revoked")
        return 3
    monkeypatch.setattr(bolt_sync, "collect_recent", _collect)
    monkeypatch.setattr(bolt_sync, "get_today_summary", lambda uid: {"n": 2, "net": 100.0})

    posted = []   # post_month NU trebuie apelat la sync (confirm-first)
    monkeypatch.setattr(bolt_sync, "post_month", lambda *a, **k: posted.append(a))
    buttons, plains = [], []
    monkeypatch.setattr(bolt_sync, "_send_with_button", lambda tok, chat, txt, y, m: buttons.append(chat))
    monkeypatch.setattr(bolt_sync, "_send_plain", lambda tok, chat, txt: plains.append(chat))

    bolt_sync.run_bolt_daily_sync("tok")   # NU trebuie să crape

    assert 21 in buttons          # user OK → notificare cu buton (opțional)
    assert 22 in plains           # user cu chei invalide → notificare reconectare
    assert posted == []           # CONFIRM-FIRST: nimic postat automat la sync


# ════════════════════════════════════════════════════════
# 3. Owner backward-compat (env), fără creds per-user
# ════════════════════════════════════════════════════════

def test_owner_env_backward_compat(tmp_path, monkeypatch):
    # owner NU e conectat per-user → rulează calea env veche (collect_recent silent)
    S = _db(tmp_path, [{"telegram_id": 777}])   # owner, fără bolt_client_id
    monkeypatch.setattr(bolt_sync, "get_session", lambda: S())
    monkeypatch.setenv("BOLT_OWNER_TELEGRAM_ID", "777")
    monkeypatch.setattr(bolt_sync.BoltClient, "available", lambda self: True)
    ss = S(); owner_uid = ss.query(User).filter_by(telegram_id=777).one().id; ss.close()
    monkeypatch.setattr(bolt_sync, "_resolve_user_id", lambda tg: owner_uid)
    env_calls = []
    monkeypatch.setattr(bolt_sync, "collect_recent",
                        lambda user_id, days=4, client=None: env_calls.append((user_id, client)))

    bolt_sync.run_bolt_daily_sync("tok")
    assert env_calls == [(owner_uid, None)]   # owner sincronizat pe env (client None)


def test_owner_conectat_per_user_nu_dubleaza(tmp_path, monkeypatch):
    # owner conectat per-user → e în buclă; calea env NU se mai rulează (dedup)
    S = _db(tmp_path, [{"telegram_id": 777, "bolt_client_id": "OWN", "bolt_client_secret_enc": "z"}])
    monkeypatch.setattr(bolt_sync, "get_session", lambda: S())
    monkeypatch.setenv("BOLT_OWNER_TELEGRAM_ID", "777")
    monkeypatch.setattr(bolt_sync.BoltClient, "available", lambda self: True)
    ss = S(); owner_uid = ss.query(User).filter_by(telegram_id=777).one().id; ss.close()
    monkeypatch.setattr(bolt_sync, "_resolve_user_id", lambda tg: owner_uid)
    monkeypatch.setattr(bolt_sync, "_daily_sync_one", lambda tok, u: None)   # bucla per-user
    env_calls = []
    monkeypatch.setattr(bolt_sync, "collect_recent",
                        lambda user_id, days=4, client=None: env_calls.append(user_id))

    bolt_sync.run_bolt_daily_sync("tok")
    assert env_calls == []   # owner deja în bucla per-user → fără dublu-sync env
