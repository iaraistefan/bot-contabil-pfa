"""
Teste pentru ruta de download document (Faza 2, PAS 4).

DB sqlite IZOLAT (monkeypatch get_session) + auth prin DEV_USER_ID (ENV=test) +
storage.get_bytes mock-uit. Verifică ownership STRICT + stările 404.
"""

from app.http import app as webapp
from app import storage
from app.models import User, SourceFile, Document
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

SHA = "a" * 64


def _setup(tmp_path, monkeypatch):
    eng = create_engine(f"sqlite:///{(tmp_path / 't.db').as_posix()}")
    User.metadata.create_all(eng)
    Session = sessionmaker(bind=eng)
    monkeypatch.setattr(webapp, "get_session", lambda: Session())

    s = Session()
    owner = User(telegram_id=111)
    other = User(telegram_id=222)
    s.add_all([owner, other])
    s.commit()
    owner_id, other_id = owner.id, other.id

    sf = SourceFile(
        user_id=owner_id, kind="photo", sha256=SHA, mime="image/jpeg",
        storage_path=f"user_{owner_id}/2026/06/{SHA}.jpg",
    )
    s.add(sf)
    s.commit()
    doc = Document(
        user_id=owner_id, source_file_id=sf.id, data_doc="05.06.2026",
        platforma="Lukoil", tip="CHELTUIALA", brut=60.0, status="posted",
    )
    doc_nofile = Document(
        user_id=owner_id, source_file_id=None, data_doc="01.06.2026",
        tip="VENIT", brut=100.0, status="posted",
    )
    s.add_all([doc, doc_nofile])
    s.commit()
    ids = {"owner": owner_id, "other": other_id,
           "doc": doc.id, "doc_nofile": doc_nofile.id}
    s.close()
    return ids


def _client(monkeypatch, uid):
    monkeypatch.setenv("DEV_USER_ID", str(uid))
    webapp.flask_app.config["TESTING"] = True
    return webapp.flask_app.test_client()


# ────────────────────────────────────────────────────────────

def test_owner_descarca_propriul_document(monkeypatch, tmp_path):
    ids = _setup(tmp_path, monkeypatch)
    monkeypatch.setattr(storage, "get_bytes", lambda p: b"FAKE-IMG-BYTES")
    c = _client(monkeypatch, ids["owner"])
    r = c.get(f"/api/v1/documents/{ids['doc']}/file")
    assert r.status_code == 200
    assert r.data == b"FAKE-IMG-BYTES"
    assert r.mimetype == "image/jpeg"
    assert "attachment" in r.headers.get("Content-Disposition", "")


def test_alt_user_nu_poate_descarca(monkeypatch, tmp_path):
    ids = _setup(tmp_path, monkeypatch)
    monkeypatch.setattr(storage, "get_bytes", lambda p: b"SECRET")
    c = _client(monkeypatch, ids["other"])           # alt user autentificat
    r = c.get(f"/api/v1/documents/{ids['doc']}/file")  # documentul owner-ului
    assert r.status_code == 404                       # ownership: nu se scurge


def test_document_fara_fisier(monkeypatch, tmp_path):
    ids = _setup(tmp_path, monkeypatch)
    c = _client(monkeypatch, ids["owner"])
    r = c.get(f"/api/v1/documents/{ids['doc_nofile']}/file")
    assert r.status_code == 404


def test_fisier_indisponibil_istoric(monkeypatch, tmp_path):
    ids = _setup(tmp_path, monkeypatch)
    def _raise(p):
        raise FileNotFoundError(p)
    monkeypatch.setattr(storage, "get_bytes", _raise)
    c = _client(monkeypatch, ids["owner"])
    r = c.get(f"/api/v1/documents/{ids['doc']}/file")
    assert r.status_code == 404


def test_document_inexistent(monkeypatch, tmp_path):
    ids = _setup(tmp_path, monkeypatch)
    c = _client(monkeypatch, ids["owner"])
    r = c.get("/api/v1/documents/999999/file")
    assert r.status_code == 404
