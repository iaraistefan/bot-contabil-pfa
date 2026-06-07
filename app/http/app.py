"""
Flask HTTP API pentru Bot Contabil PFA.

AUTH (Bug #6 fix):
- Endpoint-urile API care întorc date specifice user-ului folosesc Telegram
  WebApp init_data pentru identificare.
- Validare HMAC cu bot token (Telegram standard) — niciun spoofing posibil.
- Fallback DEV_USER_ID din env pentru testare în browser direct (numai dev/owner).

CHANGELOG:
- + /api/v1/parcurs/<year>/<month> — date foaie de parcurs pentru dashboard
  (ture, km business/pasager/pozitionare, combustibil, vehicul).
"""

import os as _os
import hmac
import hashlib
import logging
from datetime import datetime
from threading import Thread
from typing import Optional
from urllib.parse import parse_qsl

from flask import Flask, jsonify, render_template, Response, request

from config import settings
from db import get_session
from app.repositories import transactions as tx_repo
from app.repositories import users as users_repo
from app.services import tax_engine
from app.domain import labels_ro
from app import storage
from app.integrations.exports import csv_export
from app.integrations.exports.registru import (
    generate_registru_xlsx, filename_registru
)

logger = logging.getLogger(__name__)

flask_app = Flask(
    "bot_contabil_api",
    template_folder=_os.path.join(_os.path.dirname(__file__), "templates"),
    static_folder=_os.path.join(_os.path.dirname(__file__), "static"),
)

if settings.env == "production":
    logging.getLogger("werkzeug").setLevel(logging.WARNING)


# ============================================================
#                    AUTH HELPERS
# ============================================================

def _validate_telegram_init_data(init_data: str, bot_token: str) -> Optional[dict]:
    """
    Valideaza semnatura HMAC a Telegram WebApp init_data.

    Surse oficiale se contrazic daca 'signature' se include sau nu in
    data_check_string la validarea cu hash. Asa ca incercam AMBELE variante:
      A) exclude hash + signature
      B) exclude doar hash (signature inclus)
    Acceptam daca oricare se potriveste.

    NU folosim parse_qsl (acela face unquote_plus si transforma '+' in spatiu,
    stricand campuri base64 ca query_id). Folosim unquote.
    """
    if not init_data or not bot_token:
        logger.warning(
            f"init_data validate: init_data_present={bool(init_data)}, "
            f"bot_token_present={bool(bot_token)}"
        )
        return None

    try:
        from urllib.parse import unquote

        received_hash = None
        all_pairs = []  # toate campurile (mai putin hash), cu signature inclus
        for chunk in init_data.split("&"):
            if not chunk:
                continue
            key, _, value = chunk.partition("=")
            if key == "hash":
                received_hash = value
                continue
            all_pairs.append((key, unquote(value)))

        if not received_hash:
            logger.warning("init_data: campul 'hash' lipseste")
            return None

        secret_key = hmac.new(
            b"WebAppData", bot_token.encode("utf-8"), hashlib.sha256
        ).digest()

        def _matches(pairs) -> bool:
            ordered = sorted(pairs, key=lambda kv: kv[0])
            dcs = "\n".join(f"{k}={v}" for k, v in ordered)
            expected = hmac.new(
                secret_key, dcs.encode("utf-8"), hashlib.sha256
            ).hexdigest()
            return hmac.compare_digest(expected, received_hash)

        pairs_no_sig = [(k, v) for k, v in all_pairs if k != "signature"]

        matched = None
        used = None
        if _matches(pairs_no_sig):
            matched = "fara_signature"
            used = pairs_no_sig
        elif _matches(all_pairs):
            matched = "cu_signature"
            used = all_pairs

        if not matched:
            logger.warning(
                f"init_data hash mismatch (ambele variante). "
                f"Campuri: {[k for k, _ in all_pairs]}. Verifica TELEGRAM_TOKEN."
            )
            return None

        logger.info(f"init_data VALID (varianta={matched})")

        parsed = {k: v for k, v in used}
        import json
        user_json = parsed.get("user")
        if user_json:
            try:
                parsed["user_obj"] = json.loads(user_json)
            except json.JSONDecodeError:
                pass
        return parsed

    except Exception as e:
        logger.error(f"init_data validation error: {e}")
        return None


def _resolve_user_id() -> Optional[int]:
    """
    Rezolvă user_id-ul DB-intern din request curent.

    Strategia:
    1. Verifică header X-Telegram-Init-Data (set de WebApp frontend)
       → validează HMAC → caută user în DB după telegram_id
    2. Fallback: env var DEV_USER_ID (pentru debug owner-only)

    Returnează None dacă nu poate identifica user-ul.
    """
    # Strategy 1: Telegram WebApp init_data
    init_data = request.headers.get("X-Telegram-Init-Data", "")
    logger.info(
        f"_resolve_user_id: init_data header present={bool(init_data)}, "
        f"len={len(init_data)}"
    )
    if init_data:
        validated = _validate_telegram_init_data(init_data, settings.telegram_token)
        if validated:
            user_obj = validated.get("user_obj") or {}
            telegram_id = user_obj.get("id")
            if telegram_id:
                session = get_session()
                try:
                    user = users_repo.get_by_telegram_id(
                        session, telegram_id=int(telegram_id)
                    )
                    if user:
                        logger.info(
                            f"_resolve_user_id: OK, telegram_id={telegram_id} "
                            f"-> user_id={user.id}"
                        )
                        return user.id
                    logger.warning(
                        f"_resolve_user_id: telegram_id={telegram_id} "
                        f"validat dar NU exista in DB"
                    )
                except Exception as e:
                    logger.error(f"_resolve_user_id DB error: {e}")
                finally:
                    session.close()

    # Strategy 2: DEV fallback (env var) — DOAR in development.
    # SECURITATE (fix Bug izolare dashboard): in productie aceasta cale
    # este COMPLET dezactivata. Altfel DEV_USER_ID ar functiona ca o
    # cheie universala — orice request fara init_data valid ar primi
    # datele acelui user, expunand datele unui cont tuturor.
    if settings.env != "production":
        dev_user_id = _os.environ.get("DEV_USER_ID")
        if dev_user_id:
            try:
                logger.warning(
                    f"_resolve_user_id: folosesc fallback DEV_USER_ID="
                    f"{dev_user_id} (permis DOAR in env={settings.env})"
                )
                return int(dev_user_id)
            except ValueError:
                pass

    return None


def _require_user():
    """
    Returnează (user_id, error_response).
    Dacă user_id e None → error_response e setat și apelantul trebuie să-l returneze.
    """
    user_id = _resolve_user_id()
    if user_id is None:
        return None, (jsonify({
            "error": "unauthorized",
            "message": (
                "Acces din browser interzis. Deschide Dashboard-ul prin "
                "butonul din botul de Telegram."
            ),
        }), 401)
    return user_id, None


# ============================================================
#                    HEALTH & STATUS
# ============================================================

@flask_app.route("/")
@flask_app.route("/healthz")
def healthz():
    return jsonify({
        "status": "ok",
        "service": "bot-contabil-pfa",
        "timestamp": datetime.utcnow().isoformat() + "Z",
    })


@flask_app.route("/metrics")
def metrics():
    """Metrice publice agregate (fără date specifice unui user)."""
    session = get_session()
    try:
        from app.models import Document, Transaction, SourceFile, User
        return jsonify({
            "status": "ok",
            "users": session.query(User).count(),
            "documents": session.query(Document).count(),
            "transactions": session.query(Transaction).count(),
            "source_files": session.query(SourceFile).count(),
            "timestamp": datetime.utcnow().isoformat() + "Z",
        })
    except Exception as e:
        logger.error(f"Metrics error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        session.close()


# ============================================================
#                    DASHBOARD
# ============================================================

@flask_app.route("/dashboard")
def dashboard():
    """Dashboard HTML — autentificarea se face în frontend prin Telegram WebApp."""
    return render_template("dashboard.html")


# ============================================================
#                    API v1 — Date specifice user
# ============================================================

@flask_app.route("/api/v1/period/<int:year>/<int:month>")
def period_totals(year: int, month: int):
    if not (1 <= month <= 12 and 2020 <= year <= 2099):
        return jsonify({"error": "invalid period"}), 400

    user_id, err = _require_user()
    if err:
        return err

    session = get_session()
    try:
        totals = tax_engine.compute_period(
            session, user_id=user_id, year=year, month=month
        )
        return jsonify(totals)
    except Exception as e:
        logger.error(f"API period error {year}/{month} user={user_id}: {e}")
        return jsonify({"error": "internal error"}), 500
    finally:
        session.close()


@flask_app.route("/api/v1/transactions/<int:year>/<int:month>")
def transactions_list(year: int, month: int):
    if not (1 <= month <= 12 and 2020 <= year <= 2099):
        return jsonify({"error": "invalid period"}), 400

    user_id, err = _require_user()
    if err:
        return err

    session = get_session()
    try:
        txs = tx_repo.list_for_period(
            session, user_id=user_id, year=year, month=month
        )
        # Activitatea o data per request (nu per tranzactie) — pentru etichete RO.
        activity = tax_engine._get_user_activity(session, user_id)
        data = [{
            "id": tx.id,
            "tx_type": tx.tx_type,
            "category": tx.category,
            "amount_brut": tx.amount_brut,
            "amount_vat": tx.amount_vat,
            "amount_net": tx.amount_net,
            "currency": tx.currency,
            "deductibility_pct": tx.deductibility_pct,
            "payment_method": tx.payment_method,
            "counterparty": tx.counterparty,
            "vat_treatment": tx.vat_treatment,
            "occurred_on": tx.occurred_on.isoformat() if tx.occurred_on else None,
            "period_year": tx.period_year,
            "period_month": tx.period_month,
            "document_id": tx.document_id,
            # Etichete RO (sursa unica: app.domain.labels_ro). Campurile brute de
            # mai sus RAMAN — frontend-ul le foloseste la icon/culoare.
            "category_ro": labels_ro.category_label(tx.category, activity),
            "tx_type_ro": labels_ro.tx_type_label(tx.tx_type),
            "payment_ro": labels_ro.payment_label(tx.payment_method),
            "vat_treatment_ro": labels_ro.vat_treatment_label(tx.vat_treatment),
        } for tx in txs]
        return jsonify({
            "year": year, "month": month,
            "count": len(data), "transactions": data,
        })
    except Exception as e:
        logger.error(f"API transactions error {year}/{month} user={user_id}: {e}")
        return jsonify({"error": "internal error"}), 500
    finally:
        session.close()


@flask_app.route("/api/v1/parcurs/<int:year>/<int:month>")
def parcurs_summary(year: int, month: int):
    """
    Date foaie de parcurs pentru dashboard.

    Intoarce: ture, km business/personal/total, km cu pasager (Bolt) +
    pozitionare, vehiculul default, tura deschisa (daca exista) si sumarul
    de combustibil (plafon vs bonuri).
    """
    if not (1 <= month <= 12 and 2020 <= year <= 2099):
        return jsonify({"error": "invalid period"}), 400

    user_id, err = _require_user()
    if err:
        return err

    from app.services import foaie_parcurs
    from app.repositories import trip_logs as trip_repo
    from app.repositories import vehicule as vehicule_repo

    # --- 1. Date din DB (ture, vehicul, tura deschisa) ---
    session = get_session()
    try:
        trips = trip_repo.list_for_month(session, user_id, year, month)
        summary = foaie_parcurs.compute_month_summary(trips)
        open_trip = trip_repo.get_open_trip(session, user_id)
        vehicul = vehicule_repo.get_default(session, user_id)

        ture = [{
            "id": t.id,
            "trip_date": t.trip_date.isoformat() if t.trip_date else None,
            "odometer_start": t.odometer_start,
            "odometer_end": t.odometer_end,
            "km": t.km,
            "status": t.status,
            "ora_start": t.ora_start,
            "ora_stop": t.ora_stop,
            "purpose": t.purpose,
        } for t in trips]

        resp = {
            "year": year, "month": month,
            "nr_ture": summary["nr_ture"],
            "km_business": summary["km_business"],
            "km_personal": summary["km_personal"],
            "km_total": summary["km_total"],
            "pct_business": summary["pct_business"],
            "has_open": summary["has_open"],
            "open_trip": ({
                "odometer_start": open_trip.odometer_start,
                "ora_start": open_trip.ora_start,
                "trip_date": open_trip.trip_date.isoformat() if open_trip.trip_date else None,
            } if open_trip else None),
            "vehicul": ({
                "nr_inmatriculare": vehicul.nr_inmatriculare,
                "marca_model": vehicul.marca_model,
                "norma_consum": vehicul.norma_consum,
                "km_curent": vehicul.km_curent,
            } if vehicul else None),
            "ture": ture,
        }
    except Exception as e:
        logger.error(f"API parcurs error {year}/{month} user={user_id}: {e}")
        return jsonify({"error": "internal error"}), 500
    finally:
        session.close()

    # --- 2. Km cu pasager (Bolt) — cache only, sesiune proprie ---
    try:
        from app.integrations import bolt_sync
        bolt_km = bolt_sync.get_month_km(user_id, year, month)
        km_bolt = bolt_km.get("km", 0.0)
    except Exception as e:
        logger.error(f"API parcurs bolt km error: {e}")
        km_bolt = 0.0

    km_business = resp["km_business"]
    resp["km_bolt_pasager"] = km_bolt
    resp["km_pozitionare"] = (
        max(round(km_business - km_bolt, 1), 0.0) if km_business > 0 else 0.0
    )

    # --- 3. Combustibil — sesiune proprie in get_fuel_summary ---
    try:
        from app.services import combustibil
        fuel = combustibil.get_fuel_summary(user_id, year, month)
        resp["combustibil"] = {
            "plafon_litri": fuel["plafon_litri"],
            "plafon_lei": fuel["plafon_lei"],
            "total_bonuri_lei": fuel["total_bonuri_lei"],
            "total_litri": fuel["total_litri"],
            "pret_mediu": fuel["pret_mediu"],
            "pret_din_bonuri": fuel["pret_din_bonuri"],
            "mai_poti_lei": fuel["mai_poti_lei"],
            "norma_consum": fuel["norma_consum"],
            "nr_bonuri": fuel["nr_bonuri"],
        }
    except Exception as e:
        logger.error(f"API parcurs fuel error: {e}")
        resp["combustibil"] = None

    return jsonify(resp)


@flask_app.route("/api/v1/obligatii/<int:year>/<int:month>")
def obligatii_fiscale(year: int, month: int):
    """
    Obligatii fiscale calculate pentru luna (Calendar + Plati in dashboard).

    Foloseste fiscal_calendar.get_obligations_for_user cu profilul real al
    user-ului. Baza intracomunitara (comision Bolt) vine din TVA colectat
    (vat_out_total / cota_tva a perioadei), deci nu mai sapam separat in facturi.
    """
    if not (1 <= month <= 12 and 2020 <= year <= 2099):
        return jsonify({"error": "invalid period"}), 400

    user_id, err = _require_user()
    if err:
        return err

    from app.domain import fiscal_calendar

    # mapare judet -> cod (extensibil)
    JUDET_MAP = {
        "BISTRITA-NASAUD": "BN", "BISTRIȚA-NĂSĂUD": "BN",
        "CLUJ": "CJ", "BUCURESTI": "B", "BUCUREȘTI": "B",
    }

    session = get_session()
    try:
        profile = users_repo.get_profile_dict(session, user_id) or {}

        # parametri profil (cu fallback-uri sigure pentru PFA ridesharing)
        forma_juridica = profile.get("forma_juridica") or "PFA"
        activity_code = profile.get("activity_code") or "ridesharing"
        regim_tva = (profile.get("regim_tva") or "").lower()
        is_vat_payer = ("platitor" in regim_tva) and ("neplatitor" not in regim_tva)
        # cod special TVA (art. 317): explicit din profil, altfel dedus
        has_cod_special = bool(profile.get("cod_special_tva"))
        if not has_cod_special and activity_code == "ridesharing" and not is_vat_payer:
            has_cod_special = True
        judet_raw = (profile.get("judet") or "").upper().strip()
        judet = JUDET_MAP.get(judet_raw, judet_raw[:2] if judet_raw else None)

        # baza intracom (comision Bolt) din TVA colectat
        totals = tax_engine.compute_period(
            session, user_id=user_id, year=year, month=month
        )
        vat_out = float(totals.get("vat_out_total") or 0.0)
        cota = float(totals.get("cota_tva") or 0.21)  # cota perioadei (sursă unică)
        intracom_base = round(vat_out / cota, 2) if vat_out > 0 else 0.0
        has_intracom = vat_out > 0
    except Exception as e:
        logger.error(f"API obligatii profil error {year}/{month} user={user_id}: {e}")
        session.close()
        return jsonify({"error": "internal error"}), 500
    finally:
        session.close()

    try:
        obligatii = fiscal_calendar.get_obligations_for_user(
            year, month, forma_juridica, activity_code,
            has_intracom_invoice=has_intracom,
            intracom_base_amount=intracom_base,
            has_cod_special_tva=has_cod_special,
            is_vat_payer=is_vat_payer,
            judet=judet,
            only_applicable=True,
        )
        data = [{
            "cod": o.definitie.cod,
            "nume": o.definitie.nume,
            "descriere": o.definitie.descriere,
            "frecventa": o.definitie.frecventa.value,
            "termen": o.termen.isoformat(),
            "zile_ramase": o.zile_ramase,
            "status": o.status.value,
            "suma_estimata": o.suma_estimata,
            "baza_calcul": o.baza_calcul,
            "iban": (o.iban_cont.iban if o.iban_cont else None),
            "cod_buget": (o.iban_cont.cod_buget if o.iban_cont else None),
            "bonus_info": o.definitie.bonus_info,
            "estimare_in_curs": False,
            "estimare_an": None,
        } for o in obligatii]

        # Injecteaza suma reala D212 (impozit+CAS+CASS anual) din sursa unica
        # (acelasi numar ca /api/v1/declaratie-unica si ca declaratia depusa).
        # An venit = termen.year - 1 (D212 declara anul anterior termenului).
        # venit_brut == 0 (an fara date) -> NU "0 lei" sec, ci "estimare in curs".
        d212_idx = [i for i, o in enumerate(obligatii) if o.definitie.cod == "D212"]
        if d212_idx:
            d212_session = get_session()
            try:
                for i in d212_idx:
                    an_venit = obligatii[i].termen.year - 1
                    r = tax_engine.compute_d212_anual(
                        d212_session, user_id=user_id, an=an_venit
                    )
                    if r.venit_brut > 0:
                        data[i]["suma_estimata"] = r.total_plata
                        data[i]["baza_calcul"] = r.venit_net
                    else:
                        data[i]["suma_estimata"] = None
                        data[i]["estimare_in_curs"] = True
                        data[i]["estimare_an"] = an_venit
            except Exception as e:
                logger.error(
                    f"API obligatii D212 suma error {year}/{month} "
                    f"user={user_id}: {e}"
                )
            finally:
                d212_session.close()

        return jsonify({
            "year": year, "month": month,
            "intracom_base": intracom_base,
            "count": len(data),
            "obligatii": data,
        })
    except Exception as e:
        logger.error(f"API obligatii calc error {year}/{month} user={user_id}: {e}")
        return jsonify({"error": "internal error"}), 500


@flask_app.route("/api/v1/declaratie-unica/<int:year>")
def declaratie_unica_d212(year: int):
    """
    Declaratia Unica (D212) — calcul anual: impozit + CAS + CASS.

    Aduna venitul brut si cheltuielile deductibile din toate cele 12 luni
    (din motorul fiscal) si calculeaza obligatiile anuale. Orientativ.
    """
    if not (2020 <= year <= 2099):
        return jsonify({"error": "invalid year"}), 400

    user_id, err = _require_user()
    if err:
        return err

    session = get_session()
    try:
        # Sursa unica: helper partajat (acelasi numar ca declaratia reala si
        # ca suma D212 din cardul "cat platesc").
        r = tax_engine.compute_d212_anual(session, user_id=user_id, an=year)
    except Exception as e:
        logger.error(f"API D212 error {year} user={user_id}: {e}")
        return jsonify({"error": "internal error"}), 500
    finally:
        session.close()

    return jsonify({
            "an": r.an,
            "venit_brut": r.venit_brut,
            "cheltuieli": r.cheltuieli,
            "venit_net": r.venit_net,
            "cas": r.cas,
            "cass": r.cass,
            "impozit": r.impozit,
            "total_plata": r.total_plata,
            "bonificatie": r.bonificatie,
            "total_cu_bonificatie": r.total_cu_bonificatie,
            "ghid": r.ghid_telegram,
            "ghid_plain": r.ghid_plain,
            "avertismente": r.avertismente,
        })


@flask_app.route("/api/v1/declaratie/<tip>/<int:year>/<int:month>")
def genereaza_declaratie(tip: str, year: int, month: int):
    """
    Genereaza o declaratie ANAF (D390/D301/D100) pentru luna data.

    Query params optionale:
      - format=ghid (default) -> JSON cu ghid de completare + meta
      - format=xml            -> descarca fisierul XML

    Baza intracom (comision Bolt) vine din TVA colectat (vat_out/cota perioadei),
    la fel ca la /obligatii. Datele firmei (CUI, cod special, banca, IBAN)
    vin din profilul user-ului.
    """
    tip = (tip or "").upper().strip()
    if tip not in ("D390", "D301", "D100"):
        return jsonify({"error": "tip necunoscut",
                        "message": "Foloseste D390, D301 sau D100."}), 400
    if not (1 <= month <= 12 and 2020 <= year <= 2099):
        return jsonify({"error": "invalid period"}), 400

    user_id, err = _require_user()
    if err:
        return err

    fmt = (request.args.get("format") or "ghid").lower()

    from app.integrations.anaf import declaratii_service as decl

    session = get_session()
    try:
        profile = users_repo.get_profile_dict(session, user_id) or {}
        totals = tax_engine.compute_period(
            session, user_id=user_id, year=year, month=month
        )
        vat_out = float(totals.get("vat_out_total") or 0.0)
        cota = float(totals.get("cota_tva") or 0.21)  # cota perioadei (sursă unică)
        baza_intracom = round(vat_out / cota, 2) if vat_out > 0 else 0.0
    except Exception as e:
        logger.error(f"API declaratie profil error {tip} {year}/{month} user={user_id}: {e}")
        session.close()
        return jsonify({"error": "internal error"}), 500
    finally:
        session.close()

    if baza_intracom <= 0:
        return jsonify({
            "error": "fara_baza",
            "message": (
                f"Nu exista factura Bolt (comision) in {month:02d}/{year}, "
                f"deci {tip} nu se depune pentru aceasta luna."
            ),
        }), 400

    try:
        firma = decl.date_firma_din_profil(profile)
        rez = decl.genereaza(tip, year, month, baza_intracom, firma=firma)
    except Exception as e:
        logger.error(f"API declaratie gen error {tip} {year}/{month} user={user_id}: {e}")
        return jsonify({"error": "internal error", "message": str(e)}), 500

    if fmt == "xml":
        return Response(
            rez.xml,
            mimetype="application/xml; charset=utf-8",
            headers={"Content-Disposition":
                     f"attachment; filename={rez.nume_fisier_xml}"},
        )

    # default: JSON cu ghid + meta
    return jsonify({
        "tip": rez.tip,
        "year": rez.an,
        "month": rez.luna,
        "ghid": rez.ghid_telegram,
        "ghid_plain": rez.ghid_plain,
        "are_plata": rez.are_plata,
        "suma_plata": rez.suma_plata,
        "namespace_de_confirmat": rez.namespace_de_confirmat,
        "avertismente": rez.avertismente,
        "xml_url": f"/api/v1/declaratie/{tip}/{year}/{month}?format=xml",
        "nume_fisier_xml": rez.nume_fisier_xml,
    })


@flask_app.route("/api/v1/setari", methods=["GET"])
def setari_get():
    """Citeste setarile editabile de user (date bancare pentru declaratii)."""
    user_id, err = _require_user()
    if err:
        return err

    session = get_session()
    try:
        profile = users_repo.get_profile_dict(session, user_id) or {}
        return jsonify({
            "banca": profile.get("banca") or "",
            "iban": profile.get("iban") or "",
            "firma_nume": profile.get("firma_nume") or "",
            "firma_cui": profile.get("firma_cui") or "",
            "cod_special_tva": profile.get("cod_special_tva") or "",
        })
    except Exception as e:
        logger.error(f"API setari GET error user={user_id}: {e}")
        return jsonify({"error": "internal error"}), 500
    finally:
        session.close()


@flask_app.route("/api/v1/setari", methods=["POST"])
def setari_post():
    """Salveaza setarile editabile de user (banca + IBAN)."""
    user_id, err = _require_user()
    if err:
        return err

    body = request.get_json(silent=True) or {}
    banca = body.get("banca")
    iban = body.get("iban")

    # validare minimala IBAN (RO + 22 caractere alfanumerice = 24 total)
    if iban:
        iban_clean = "".join(c for c in str(iban).upper() if c.isalnum())
        if iban_clean and not (iban_clean.startswith("RO") and len(iban_clean) == 24):
            return jsonify({
                "error": "invalid_iban",
                "message": "IBAN-ul pare invalid. Un IBAN romanesc are forma "
                           "RO + 22 caractere (24 in total).",
            }), 400

    session = get_session()
    try:
        user = users_repo.get_by_id(session, user_id)
        if user is None:
            return jsonify({"error": "user not found"}), 404
        users_repo.update_profile(
            session, user,
            banca=(banca if banca is not None else None),
            iban=(iban if iban is not None else None),
        )
        session.commit()
        profile = users_repo.get_profile_dict(session, user_id) or {}
        return jsonify({
            "ok": True,
            "banca": profile.get("banca") or "",
            "iban": profile.get("iban") or "",
        })
    except Exception as e:
        session.rollback()
        logger.error(f"API setari POST error user={user_id}: {e}")
        return jsonify({"error": "internal error"}), 500
    finally:
        session.close()


@flask_app.route("/api/v1/documents")
def documents_recent():
    user_id, err = _require_user()
    if err:
        return err

    session = get_session()
    try:
        from app.models import Document
        docs = (
            session.query(Document)
            .filter(Document.user_id == user_id)
            .order_by(Document.id.desc())
            .limit(20)
            .all()
        )
        data = [{
            "id": doc.id,
            "data_doc": doc.data_doc,
            "platforma": doc.platforma,
            "tip": doc.tip,
            "brut": doc.brut,
            "tva": doc.tva,
            "net": doc.net,
            "status": doc.status,
            "detalii": doc.detalii,
            "prompt_version": doc.prompt_version,
            "created_at": doc.created_at.isoformat() if doc.created_at else None,
        } for doc in docs]
        return jsonify({"count": len(data), "documents": data})
    except Exception as e:
        logger.error(f"API documents error user={user_id}: {e}")
        return jsonify({"error": "internal error"}), 500
    finally:
        session.close()


@flask_app.route("/api/v1/documents/<int:doc_id>/file")
def document_file(doc_id: int):
    """
    Descarcă fișierul original arhivat al unui document (stream din R2/disk).

    Ownership STRICT: doar documentele user-ului autentificat (filtru user_id).
    404 dacă: nu există / nu e al lui / fără fișier / fișier indisponibil
    (istoric pierdut). Bucket-ul rămâne privat — totul trece prin auth.
    """
    user_id, err = _require_user()
    if err:
        return err

    session = get_session()
    try:
        from app.models import Document
        doc = (
            session.query(Document)
            .filter(Document.id == doc_id, Document.user_id == user_id)
            .one_or_none()
        )
        if doc is None:
            return jsonify({"error": "not found"}), 404
        sf = doc.source_file
        if sf is None or not sf.storage_path:
            return jsonify({"error": "document fără fișier atașat"}), 404
        try:
            data = storage.get_bytes(sf.storage_path)
        except FileNotFoundError:
            return jsonify({"error": "fișier indisponibil"}), 404

        ext = (sf.storage_path.rsplit(".", 1)[-1]
               if "." in sf.storage_path else "bin")
        filename = f"document_{doc_id}.{ext}"
        return Response(
            data,
            mimetype=(sf.mime or "application/octet-stream"),
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except Exception as e:
        logger.error(f"API document file error doc={doc_id} user={user_id}: {e}")
        return jsonify({"error": "internal error"}), 500
    finally:
        session.close()


# ============================================================
#                    API v1 — Export CSV
# ============================================================

@flask_app.route("/api/v1/transactions/export/<int:year>/<int:month>")
def export_transactions_csv(year: int, month: int):
    if not (1 <= month <= 12 and 2020 <= year <= 2099):
        return "Invalid period", 400

    user_id, err = _require_user()
    if err:
        return "Unauthorized", 401

    session = get_session()
    try:
        txs = tx_repo.list_for_period(
            session, user_id=user_id, year=year, month=month
        )
        csv_bytes = csv_export.generate_transactions_csv(txs, year, month)
        fname = csv_export.filename_transactions(year, month)
        return Response(
            csv_bytes,
            mimetype="text/csv; charset=utf-8",
            headers={"Content-Disposition": f"attachment; filename={fname}"},
        )
    except Exception as e:
        logger.error(f"CSV export error {year}/{month} user={user_id}: {e}")
        return "Export error", 500
    finally:
        session.close()


@flask_app.route("/api/v1/period/export/<int:year>/<int:month>")
def export_period_csv(year: int, month: int):
    if not (1 <= month <= 12 and 2020 <= year <= 2099):
        return "Invalid period", 400

    user_id, err = _require_user()
    if err:
        return "Unauthorized", 401

    session = get_session()
    try:
        totals = tax_engine.compute_period(
            session, user_id=user_id, year=year, month=month
        )
        csv_bytes = csv_export.generate_rezumat_csv(totals)
        fname = csv_export.filename_rezumat(year, month)
        return Response(
            csv_bytes,
            mimetype="text/csv; charset=utf-8",
            headers={"Content-Disposition": f"attachment; filename={fname}"},
        )
    except Exception as e:
        logger.error(f"Period CSV export error {year}/{month} user={user_id}: {e}")
        return "Export error", 500
    finally:
        session.close()


# ============================================================
#                    API v1 — Registru Încasări și Plăți
# ============================================================

@flask_app.route("/api/v1/registru/export/<int:year>")
def export_registru(year: int):
    """Generează Registrul de Încasări și Plăți pentru un an întreg."""
    if not 2020 <= year <= 2099:
        return "Invalid year", 400

    user_id, err = _require_user()
    if err:
        return "Unauthorized", 401

    session = get_session()
    try:
        # Folosim numele firmei din profilul user-ului
        profile = users_repo.get_profile_dict(session, user_id) or {}
        pfa_name = profile.get("firma_nume") or "PFA"
        pfa_cui = profile.get("firma_cui") or ""

        from app.models import Transaction
        txs = (
            session.query(Transaction)
            .filter(
                Transaction.user_id == user_id,
                Transaction.period_year == year,
                Transaction.locked == False,
            )
            .order_by(Transaction.occurred_on)
            .all()
        )
        xlsx_bytes = generate_registru_xlsx(
            txs, year, pfa_name=pfa_name, pfa_cui=pfa_cui,
        )
        fname = filename_registru(year)
        return Response(
            xlsx_bytes,
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f"attachment; filename={fname}"},
        )
    except Exception as e:
        logger.error(f"Registru export error {year} user={user_id}: {e}")
        return "Export error", 500
    finally:
        session.close()


# ============================================================
#                    Runner
# ============================================================

def run_flask():
    flask_app.run(
        host="0.0.0.0",
        port=settings.port,
        debug=False,
        use_reloader=False,
    )


def start_http_server():
    t = Thread(target=run_flask, daemon=True, name="flask-api")
    t.start()
    logger.info(f"✅ HTTP API started on port {settings.port}")
