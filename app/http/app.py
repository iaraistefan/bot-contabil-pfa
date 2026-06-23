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
from datetime import datetime, date
from app.domain.tax_rules import cota_tva  # sursă unică cotă TVA pe dată (fiscal #1)
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

def _d100_block(session, user_id: int, year: int, month: int, totals: dict) -> dict:
    """
    Bloc D100 (impozit nerezident) pentru web — backend CALCULEAZĂ, JS DOAR afișează
    (regula de aur: zero recalcul în JS). Sursă unică a sumei: calcul_impozit_nerezident.

    status (contract cu 4 stări — JS depinde de el; NU adăuga al 5-lea):
      - "fara_baza"     → vat_out<=0 SAU tot vat_out neatribuit → D100 nu se depune
      - "neconfigurat"  → brand recunoscut cu regim nesetat → NU afișăm sumă (prompt)
      - "scutit"        → toate brandurile la CRF 0% → suma 0, D207 anual
      - "de_depus"      → ≥1 brand cu cotă>0 → suma reală agregată (lei întregi)

    SPLIT per-platformă (Uber sub-pas B): sursă unică `tax_engine.compute_d100_plan`
    (aceeași folosită de bot/XML). Câmpuri noi: `defalcare` (din care Bolt/Uber, CU
    BANI) + `neatribuit_lei` (nudge „verifică furnizorul"). `cota` rămâne pentru
    afișajul single-brand (None la mixt).
    """
    from app.domain.fiscal_profile import from_user_dict

    profile = from_user_dict(users_repo.get_profile_dict(session, user_id) or {})
    cota_p = float(totals.get("cota_tva") or cota_tva(date(year, month, 1)))
    by_brand = tax_engine.vat_out_by_brand(session, user_id=user_id, year=year, month=month)
    plan = tax_engine.compute_d100_plan(by_brand, cota_p, profile)

    defalcare = [
        {"brand": s.brand, "eticheta": s.eticheta, "baza": s.baza,
         "cota": s.cota, "suma": s.suma}
        for s in plan.segmente
    ]
    # `cota` single-brand: doar când e un segment (afișaj „X%"); mixt → None.
    cota_afisaj = plan.segmente[0].cota if len(plan.segmente) == 1 else None
    if plan.status == "scutit":
        cota_afisaj = 0.0

    return {
        "status": plan.status,
        "suma": plan.suma_declarata,            # lei întregi (None la neconfigurat/fara_baza)
        "cota": cota_afisaj,
        "defalcare": defalcare,                 # din care Bolt X · Uber Y (cu bani)
        "neatribuit_lei": plan.neatribuit_lei,  # >0 → nudge „verifică furnizorul"
    }


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
        totals["d100"] = _d100_block(session, user_id, year, month, totals)
        # Deltă month-over-month — OPT-IN (?mom=1). Aditiv: apelurile existente (fără param)
        # rămân neatinse (regresie 0 + fără compute_period extra). Frontend-ul cere ?mom=1
        # doar pentru ultima lună completă (badge tendință confirmată).
        if request.args.get("mom") == "1":
            totals["mom"] = tax_engine.compute_mom(
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
            # Verdict pe LITRI (#5): depasit True/False/None(necunoscut),
            # mai_poti_litri = câți L mai poate deduce. mai_poti_lei informativ.
            "depasit": fuel["depasit"],
            "mai_poti_litri": fuel["mai_poti_litri"],
            "mai_poti_lei": fuel["mai_poti_lei"],
            "norma_consum": fuel["norma_consum"],
            "nr_bonuri": fuel["nr_bonuri"],
            "nr_bonuri_cu_litri": fuel["nr_bonuri_cu_litri"],
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
        cota = float(totals.get("cota_tva") or cota_tva(date(year, month, 1)))  # cota perioadei (sursă unică)
        intracom_base = round(vat_out / cota, 2) if vat_out > 0 else 0.0
        has_intracom = vat_out > 0
        # D100 split per-platformă (Uber sub-pas D): planul = sursă unică suma+status,
        # IDENTIC cu _d100_block → cele două ecrane web nu mai pot diverge.
        d100_plan = tax_engine.d100_plan_for(session, user_id=user_id, year=year, month=month)
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
            d100_suma=d100_plan.suma_declarata,
            d100_status=d100_plan.status,
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


@flask_app.route("/api/v1/ghid")
def ghid_obligatii():
    """
    Ghidul de obligații (sub-pas Ghid 2+3): conținutul pedagogic din DEFINITII_OBLIGATII,
    grupat pe frecvență (lunar/anual/o dată). SURSĂ UNICĂ — backend serializează, JS DOAR
    afișează (regula de aur).

    PERSONALIZARE (sub-pas 3): default = DOAR obligațiile userului (filtrat pe profil, via
    `ghid_codes_for_user`, același helper ca Telegram). `?all=1` → toate (toggle „vezi
    toate"). Profil incomplet → toate + nudge (anti-omisiune: nu ascundem D100/D301/D390).
    """
    user_id, err = _require_user()
    if err:
        return err

    from app.domain import fiscal_calendar
    from app.services.ghid_ui import ghid_codes_for_user
    force_all = bool(request.args.get("all"))
    session = get_session()
    try:
        codes, personalizat, nudge = ghid_codes_for_user(
            session, user_id, force_all=force_all)
        grupuri = [
            {
                "cheie": g["cheie"],
                "label": g["label"],
                "obligatii": [
                    {
                        "cod": d.cod,
                        "nume": d.nume,
                        "frecventa": d.frecventa.value,
                        "ce_e": d.ce_e,
                        "cui_se_aplica": d.cui_se_aplica,
                        "cand": d.cand,
                        "cum_depun": d.cum_depun,
                        "de_ce": d.de_ce,
                        "penalty_info": d.penalty_info,
                        "formula_suma": d.formula_suma,
                    }
                    for d in g["obligatii"]
                ],
            }
            for g in fiscal_calendar.ghid_grupuri(codes)
        ]
        from app.domain import casa_marcat
        return jsonify({"personalizat": personalizat, "nudge": nudge, "grupuri": grupuri,
                        "amef": casa_marcat.AMEF_INFO})
    except Exception as e:
        logger.error(f"API ghid error user={user_id}: {e}")
        return jsonify({"error": "internal error"}), 500
    finally:
        session.close()


@flask_app.route("/api/v1/certificat")
def certificat_bolt():
    """
    Certificat de rezidență fiscală Bolt (secțiune Setări). SURSĂ UNICĂ:
    `app.services.certificat` (text + nume fișier dinamic pe an). Documentul COMUN
    Bolt, NU personalizat — `disponibil` reflectă dacă owner-ul a pus PDF-ul anului.
    """
    _, err = _require_user()
    if err:
        return err
    from app.services import certificat
    an = certificat.current_year()
    return jsonify({
        "an": an,
        "url": certificat.url(an),
        "disponibil": certificat.exists(an),
        "intro": certificat.INTRO,
        "ghid_obtinere": certificat.GHID_OBTINERE,
    })


@flask_app.route("/api/v1/onboarding/status")
def onboarding_status():
    """
    Starea onboarding (wizard nou, sub-pas A) — frontend-ul rutează: dacă NU e complet →
    afișează wizardul (nu dashboard-ul normal). Routing prin STARE, nu prin URL.
    """
    user_id, err = _require_user()
    if err:
        return err
    from app.repositories import vehicule as vehicule_repo
    session = get_session()
    try:
        profile = users_repo.get_profile_dict(session, user_id) or {}
        # Rehidratare wizard (sub-pas C): la resume, frontend-ul pre-populează WIZ.data cu
        # ce-a introdus deja userul (nu doar sare la pasul corect). Derivăm is_ridesharing
        # și platformele din profil; vehiculul implicit din vehicule_repo.
        regim_bolt = profile.get("regim_nerezident_bolt")
        regim_uber = profile.get("regim_nerezident_uber")
        if regim_bolt and regim_uber:
            platforme = "AMBELE"
        elif regim_bolt:
            platforme = "BOLT"
        elif regim_uber:
            platforme = "UBER"
        else:
            platforme = None
        veh = vehicule_repo.get_default(session, user_id)
        data = {
            "name": profile.get("name"),
            "firma_cui": profile.get("firma_cui"),
            "firma_nume": profile.get("firma_nume"),
            "firma_forma_juridica": profile.get("firma_forma_juridica"),
            "regim_tva": profile.get("regim_tva"),
            "regim_impunere": profile.get("regim_impunere"),
            "caen_principal": profile.get("caen_principal"),
            "activity_code": profile.get("activity_code"),
            "judet": profile.get("judet"),
            "localitate": profile.get("localitate"),
            "regim_nerezident_bolt": regim_bolt,
            "regim_nerezident_uber": regim_uber,
            "is_ridesharing": profile.get("activity_code") == "ridesharing",
            "_platforme": platforme,
            "_boltConnected": bool(profile.get("bolt_client_id")),
            "norma_venit_anuala": profile.get("norma_venit_anuala"),
            "is_pensionar": bool(profile.get("is_pensionar")),
            "is_salariat": bool(profile.get("is_salariat")),
            "incaseaza_numerar": bool(profile.get("incaseaza_numerar")),
            # Proportionalizare mid-an (PAS 4a) — date activitate (optionale, ISO str/None).
            "data_inceput_activitate": profile.get("data_inceput_activitate"),
            "data_sfarsit_activitate": profile.get("data_sfarsit_activitate"),
            # Activitate mixta (PAS 4b) — flag + data adaugare activitate neeligibila.
            "are_activitate_neeligibila_norma": bool(profile.get("are_activitate_neeligibila_norma")),
            "data_activitate_neeligibila": profile.get("data_activitate_neeligibila"),
            # An fiscal curent — pentru gardianul de selecție normă (ridesharing pe
            # normă doar din 2026; sub-pas PAS 1-UI). Sursa regulii = norma_venit.norma_permisa.
            "_an_fiscal": date.today().year,
            "veh_nr": veh.nr_inmatriculare if veh else None,
            "veh_marca": veh.marca_model if veh else None,
            "veh_consum": veh.norma_consum if veh else None,
            "veh_tip": veh.tip_detinere if veh else None,
        }
        return jsonify({
            "onboarding_completed": bool(profile.get("onboarding_completed")),
            "current_step": profile.get("onboarding_step") or 0,
            "data": data,
        })
    except Exception as e:
        logger.error(f"API onboarding/status error user={user_id}: {e}")
        return jsonify({"error": "internal error"}), 500
    finally:
        session.close()


@flask_app.route("/api/v1/cui-lookup")
def cui_lookup():
    """
    Cercetare CUI pentru wizard (B1) — wrap `lookup_cui` (ANAF V9) + activitate din CAEN
    + flag ridesharing (deblochează pașii Bolt). Backend cercetează, JS afișează cardul.
    """
    _, err = _require_user()
    if err:
        return err
    cui = (request.args.get("cui") or "").strip()
    from app.integrations.anaf_lookup import lookup_cui
    from app.services.onboarding import activity_from_caen, ACTIVITIES_BY_CODE
    res = lookup_cui(cui)
    if not res.get("found"):
        return jsonify({"found": False, "error": res.get("error") or "Firmă negăsită"})
    activity = activity_from_caen(res.get("cod_caen") or "")
    act_label = ACTIVITIES_BY_CODE.get(activity, {}).get("label") if activity else None
    return jsonify({
        "found": True,
        "cui": res.get("cui"),
        "denumire": res.get("denumire"),
        "cod_caen": res.get("cod_caen"),
        "activity_code": activity,                       # ex. "ridesharing" (sau None)
        "activity_label": act_label,
        "is_ridesharing": activity == "ridesharing",     # deblochează pașii Bolt (B2)
        "forma_juridica": res.get("forma_juridica_detectata"),
        "regim_tva": res.get("regim_tva"),
        "is_platitor_tva": res.get("is_platitor_tva"),
        "is_inactiv": res.get("is_inactiv"),
        "stare_inregistrare": res.get("stare_inregistrare"),
        "judet": res.get("judet"),
        "localitate": res.get("localitate"),
        "adresa_completa": res.get("adresa_completa"),
    })


# Câmpurile pe care wizardul le poate salva (allowlist — restul se ignoră).
_ONBOARDING_SAVE_FIELDS = {
    "name", "firma_nume", "firma_cui", "firma_forma_juridica", "cod_special_tva",
    "regim_tva", "regim_impunere", "regim_nerezident_bolt", "regim_nerezident_uber",
    "caen_principal", "activity_code", "judet", "localitate", "norma_venit_anuala",
    "is_pensionar", "is_salariat", "incaseaza_numerar",
    # Proportionalizare mid-an (PAS 4a): date activitate (optionale). Vin ca ISO
    # str din JSON → parsate la `date` inainte de update_profile (vezi _parse_date_field).
    "data_inceput_activitate", "data_sfarsit_activitate",
    # Activitate mixta (PAS 4b): flag + data adaugare activitate neeligibila pentru norma.
    "are_activitate_neeligibila_norma", "data_activitate_neeligibila",
}

# Campurile de tip DATA din allowlist — primite ca ISO „YYYY-MM-DD" si convertite la
# obiect `date` (string gol → None = sterge data, util la corectarea unei greseli).
_ONBOARDING_DATE_FIELDS = {
    "data_inceput_activitate", "data_sfarsit_activitate", "data_activitate_neeligibila",
}


def _parse_date_field(val):
    """ISO „YYYY-MM-DD" → date | None. Valoare goala/invalida → None (necompletat)."""
    if not val:
        return None
    try:
        return date.fromisoformat(str(val)[:10])
    except (ValueError, TypeError):
        return None


@flask_app.route("/api/v1/norma-lookup")
def norma_lookup():
    """
    Norma anuală de venit pentru județ + tip localitate (PAS 1-UI). Wrap subțire peste
    `norma_venit.norma_anuala` (sursă unică). Județ/tip neacoperit → found=False → frontend-ul
    cere valoarea manual (NU presupunem o cifră la ANAF). Per-user (auth).
    """
    _, err = _require_user()
    if err:
        return err
    from app.domain import norma_venit
    judet = (request.args.get("judet") or "").strip()
    tip = (request.args.get("tip") or "").strip()
    caen = (request.args.get("caen") or "4933").strip()
    an = int(request.args.get("an") or date.today().year)
    val = norma_venit.norma_anuala(judet, tip, an=an, caen=caen)
    if val is None:
        return jsonify({"found": False, "norma": None, "sursa": None})
    # sursa (trasabilitate) — din nomenclator, dacă există
    cod = norma_venit._normalize_judet(judet)
    sursa = (norma_venit.NORMA_VENIT_4933.get(an, {}).get(cod, {}) or {}).get("_sursa")
    return jsonify({"found": True, "norma": val, "sursa": sursa})


@flask_app.route("/api/v1/casa-marcat")
def casa_marcat_status():
    """
    Semnal „ai nevoie de casă de marcat (AMEF)?" (PAS 3). Combină DATELE (income_cash pe an,
    din tranzacții CASH) cu DECLARAȚIA (incaseaza_numerar) — date reale au prioritate. Sursă
    unică: `casa_marcat.necesita_amef`. Ton INFORMATIV (+ trimitere la ghid). Per-user.
    """
    user_id, err = _require_user()
    if err:
        return err
    from app.domain import casa_marcat
    year = int(request.args.get("year") or date.today().year)
    session = get_session()
    try:
        profile = users_repo.get_profile_dict(session, user_id) or {}
        declarat = bool(profile.get("incaseaza_numerar"))
        income_cash = tx_repo.cash_income_for_year(session, user_id, year)
        necesita, motiv = casa_marcat.necesita_amef(income_cash, declarat)
        return jsonify({
            "necesita": necesita,
            "motiv": motiv,
            "income_cash": income_cash,
            "declarat": declarat,
            "info": casa_marcat.AMEF_INFO,
        })
    except Exception as e:
        logger.error(f"API casa-marcat error user={user_id}: {e}")
        return jsonify({"error": "internal error"}), 500
    finally:
        session.close()


@flask_app.route("/api/v1/onboarding/save", methods=["POST"])
def onboarding_save():
    """
    Salvare generică a unui pas din wizard (B1): scrie câmpurile de profil permise
    (allowlist, refolosește update_profile) + avansează `onboarding_step`. NU finalizează
    (asta = /complete, sub-pas C). Per-user (_require_user).
    """
    user_id, err = _require_user()
    if err:
        return err
    body = request.get_json(silent=True) or {}
    fields = {k: v for k, v in body.items() if k in _ONBOARDING_SAVE_FIELDS}
    # Datele de activitate (PAS 4a) vin ca ISO str → convertim la `date` pentru ORM.
    # String gol/invalid → None: update_profile aplica DOAR non-None, deci o data goala
    # lasa valoarea neschimbata (setarea unei date noi functioneaza; capturarea e optionala).
    for k in _ONBOARDING_DATE_FIELDS:
        if k in fields:
            fields[k] = _parse_date_field(fields[k])
    fields = {k: v for k, v in fields.items() if not (k in _ONBOARDING_DATE_FIELDS and v is None)}
    step = body.get("step")
    session = get_session()
    try:
        user = users_repo.get_by_id(session, user_id)
        if user is None:
            return jsonify({"error": "user not found"}), 404
        if fields:
            users_repo.update_profile(session, user, **fields)
        if isinstance(step, int) and step > (user.onboarding_step or 0):
            users_repo.set_onboarding_step(session, user, step)
        session.commit()
        return jsonify({"ok": True, "current_step": user.onboarding_step or 0})
    except Exception as e:
        session.rollback()
        logger.error(f"API onboarding/save error user={user_id}: {e}")
        return jsonify({"error": "internal error"}), 500
    finally:
        session.close()


@flask_app.route("/api/v1/vehicul", methods=["POST"])
def vehicul_create():
    """Creează un vehicul din wizard (B1) — refolosește vehicule_repo.create. Per-user."""
    user_id, err = _require_user()
    if err:
        return err
    body = request.get_json(silent=True) or {}
    nr = (body.get("nr_inmatriculare") or "").strip()
    if not nr:
        return jsonify({"error": "invalid", "message": "Numărul de înmatriculare e obligatoriu."}), 400
    from app.repositories import vehicule as vehicule_repo
    session = get_session()
    try:
        v = vehicule_repo.create(
            session, user_id=user_id, nr_inmatriculare=nr,
            marca_model=body.get("marca_model"),
            norma_consum=float(body.get("norma_consum") or 7.5),
            tip_detinere=body.get("tip_detinere"),
        )
        session.commit()
        return jsonify({"ok": True, "vehicul_id": v.id})
    except Exception as e:
        session.rollback()
        logger.error(f"API vehicul create error user={user_id}: {e}")
        return jsonify({"error": "internal error"}), 500
    finally:
        session.close()


# Câmpuri minime obligatorii pentru finalizare (sub-pas C). Bolt e OPȚIONAL.
# firma = CUI sau denumire (calea manuală are doar denumirea).
def _onboarding_missing(profile, has_vehicul):
    missing = []
    if not (profile.get("name") or "").strip():
        missing.append("name")
    if not ((profile.get("firma_cui") or "").strip() or (profile.get("firma_nume") or "").strip()):
        missing.append("firma")
    if not (profile.get("regim_impunere") or "").strip():
        missing.append("regim_impunere")
    if not has_vehicul:
        missing.append("masina")
    return missing


@flask_app.route("/api/v1/onboarding/complete", methods=["POST"])
def onboarding_complete():
    """
    Finalizare wizard (sub-pas C): validează câmpurile minime obligatorii → marchează
    onboarding_completed=True (userul intră în dashboard normal). Bolt e opțional (nu se
    verifică). Lipsă → 400 + lista câmpurilor lipsă (frontend-ul indică pasul). Per-user.
    """
    user_id, err = _require_user()
    if err:
        return err
    from app.repositories import vehicule as vehicule_repo
    session = get_session()
    try:
        profile = users_repo.get_profile_dict(session, user_id) or {}
        has_vehicul = vehicule_repo.count_active(session, user_id) > 0
        missing = _onboarding_missing(profile, has_vehicul)
        if missing:
            return jsonify({
                "ok": False, "missing": missing,
                "message": "Mai sunt câmpuri obligatorii de completat.",
            }), 400
        user = users_repo.get_by_id(session, user_id)
        if user is None:
            return jsonify({"error": "user not found"}), 404
        users_repo.complete_onboarding(session, user)
        session.commit()
        return jsonify({"ok": True})
    except Exception as e:
        session.rollback()
        logger.error(f"API onboarding/complete error user={user_id}: {e}")
        return jsonify({"error": "internal error"}), 500
    finally:
        session.close()


@flask_app.route("/api/v1/bolt/status")
def bolt_status():
    """Status conectare Bolt (#2-B) — secretul NU se întoarce NICIODATĂ în clar (mascat)."""
    user_id, err = _require_user()
    if err:
        return err
    from app.domain import crypto
    session = get_session()
    try:
        profile = users_repo.get_profile_dict(session, user_id) or {}
        cid = profile.get("bolt_client_id")
        connected = bool(cid and profile.get("bolt_client_secret_enc"))
        return jsonify({
            "connected": connected,
            "connected_at": profile.get("bolt_connected_at"),
            "client_id": cid or "",                      # în clar (identificator)
            "secret_masked": "••••••" if connected else "",   # NICIODATĂ secretul real
            "crypto_available": crypto.is_available(),
        })
    except Exception as e:
        logger.error(f"API bolt/status error user={user_id}: {e}")
        return jsonify({"error": "internal error"}), 500
    finally:
        session.close()


@flask_app.route("/api/v1/bolt/connect", methods=["POST"])
def bolt_connect():
    """
    Conectează contul Bolt (#2-B): validează cheile printr-un token de test → dacă OK,
    stochează client_id (clar) + secret CRIPTAT + connected_at. Eșec → NU stochează.
    Secretul intră direct în criptare; NU se loghează, NU se întoarce.
    """
    user_id, err = _require_user()
    if err:
        return err
    body = request.get_json(silent=True) or {}
    client_id = (body.get("client_id") or "").strip()
    client_secret = (body.get("client_secret") or "").strip()

    from app.integrations.bolt_sync import validate_bolt_credentials
    from app.domain import crypto
    ok, msg = validate_bolt_credentials(client_id, client_secret)
    if not ok:
        return jsonify({"error": "invalid_credentials", "message": msg}), 400

    session = get_session()
    try:
        user = users_repo.get_by_id(session, user_id)
        if user is None:
            return jsonify({"error": "user not found"}), 404
        now = datetime.utcnow()
        users_repo.update_profile(
            session, user,
            bolt_client_id=client_id,
            bolt_client_secret_enc=crypto.encrypt(client_secret),   # CRIPTAT
            bolt_connected_at=now,
        )
        session.commit()
        return jsonify({"ok": True, "connected_at": now.isoformat()})
    except Exception as e:
        session.rollback()
        logger.error(f"API bolt/connect error user={user_id}: {e}")
        return jsonify({"error": "internal error"}), 500
    finally:
        session.close()


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
    vat_st = None
    try:
        # Sursa unica: helper partajat (acelasi numar ca declaratia reala si
        # ca suma D212 din cardul "cat platesc").
        r = tax_engine.compute_d212_anual(session, user_id=user_id, an=year)
        # B8: status plafon TVA. Cifra de afaceri = venit_brut (încasări din propriile
        # prestări, fără TVA la neplătitor). Sursă unică: FiscalProfile.vat_threshold_status
        # (aceeași cale ca alerta din proactive_alerts). Non-fatal: eroare → vat=None.
        try:
            from app.domain import fiscal_profile as _fp
            vat_st = _fp.from_user_id(session, user_id).vat_threshold_status(r.venit_brut)
        except Exception as _e:
            logger.error(f"API D212 vat status error user={user_id}: {_e}")
            vat_st = None
    except Exception as e:
        logger.error(f"API D212 error {year} user={user_id}: {e}")
        return jsonify({"error": "internal error"}), 500
    finally:
        session.close()

    # A3: defalcare explicativă + praguri pentru hero-ul fiscal (Prezentare web).
    # Sursă unică: app.domain.contributii (aceleași funcții pe care le folosește
    # motorul D212) → ZERO calcul fiscal nou. Baza impozitului = venit net − CAS −
    # CASS (identic cu d212_calc.venit_impozabil), NU venitul net.
    from app.domain import contributii
    vn = r.venit_net
    cas_d = contributii.calcul_cas(vn, year)
    cass_d = contributii.calcul_cass(vn, year)
    venit_impozabil = max(0.0, round(vn - r.cas - r.cass, 2))

    breakdown = [
        {
            "tip": "impozit", "suma": r.impozit, "baza": venit_impozabil,
            "cota_pct": 10, "aplicabil": r.impozit > 0,
            "nota": "Impozit 10% pe venitul net rămas după scăderea CAS și CASS.",
        },
        {
            "tip": "cas", "suma": r.cas, "baza": cas_d["baza"],
            "cota_pct": cas_d["cota_pct"], "aplicabil": cas_d["aplicabil"],
            "nota": cas_d["nota"],
        },
        {
            "tip": "cass", "suma": r.cass, "baza": cass_d["baza"],
            "cota_pct": cass_d["cota_pct"], "aplicabil": cass_d["aplicabil"],
            "nota": cass_d["nota"],
        },
    ]

    praguri = {
        "venit_net": vn,
        "salariu_minim": contributii.salariu_minim(year),
        "cas12": contributii.prag_cas_status(vn, year),    # CAS devine obligatoriu
        "cas24": contributii.prag_cas24_status(vn, year),  # baza CAS se dublează
        "cass6": contributii.prag_cass6_status(vn, year),  # podeaua CASS (baza minimă)
        "cass60": contributii.prag_cass60_status(vn, year),  # CASS se plafonează
    }

    # B8: bloc TVA pentru banda de praguri (cifra_afaceri + remaining_ron peste ce
    # întoarce vat_threshold_status). threshold din VAT_THRESHOLD_RON (sursă unică).
    if vat_st is None:
        vat = None
    else:
        _thr = vat_st.get("threshold_ron")
        vat = {
            "is_payer": vat_st.get("is_payer", False),
            "cifra_afaceri": r.venit_brut,
            "threshold_ron": _thr,
            "utilized_pct": vat_st.get("utilized_pct"),
            "remaining_ron": (max(0.0, round(_thr - r.venit_brut, 2)) if _thr else None),
            "status": vat_st.get("status"),
            "message": vat_st.get("message"),
        }

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
            "breakdown": breakdown,
            "praguri": praguri,
            "vat": vat,
            "ghid": r.ghid_telegram,
            "ghid_plain": r.ghid_plain,
            "avertismente": r.avertismente,
        })


@flask_app.route("/api/v1/simulare-regim/<int:year>")
def simulare_regim_endpoint(year: int):
    """
    Simulator regim NORMĂ vs SISTEM REAL pentru userul curent (A2).

    Refolosește venit_brut/cheltuieli YTD din `compute_d212_anual` (SURSĂ UNICĂ — exact
    aceeași cale ca /api/v1/declaratie-unica, deci cifrele se potrivesc) + profilul
    (normă STOCATĂ, activitate, regim curent, pensionar/salariat) → cheamă funcția pură
    `simulare_regim`. Întoarce DOAR date + coduri de avertisment (mesajele lizibile se
    construiesc în UI). Orientativ.

    Normă = valoarea stocată în profil (None → NORMA_INDISPONIBILA, NU inventăm). Pentru
    userii pe real fără normă completată, UI-ul (A3.2) caută live norma pe tip localitate
    și o trimite via `?norma=<float>` (IPOTEZĂ — NU se scrie în profil, doar pentru simulare).

    Query opțional `?norma=<float>`: prezent valid >0 → override (ipoteză); absent/gol →
    norma stocată (regresie 0); invalid (≤0 / non-numeric) → 400.
    """
    if not (2020 <= year <= 2099):
        return jsonify({"error": "invalid year"}), 400

    user_id, err = _require_user()
    if err:
        return err

    # Override normă (A3.2): ipoteză „ce-ar fi dacă", NU schimbă profilul. Gol/absent →
    # None (folosim stocata). Prezent dar invalid (≤0 / non-numeric) → 400 explicit.
    norma_override = None
    norma_raw = (request.args.get("norma") or "").strip()
    if norma_raw:
        try:
            norma_override = float(norma_raw)
        except (TypeError, ValueError):
            return jsonify({"error": "invalid norma"}), 400
        if norma_override <= 0:
            return jsonify({"error": "invalid norma"}), 400

    session = get_session()
    try:
        # Sursă unică: aceleași venit_brut/cheltuieli YTD ca declarația reală.
        r = tax_engine.compute_d212_anual(session, user_id=user_id, an=year)
        profile = users_repo.get_profile_dict(session, user_id) or {}
    except Exception as e:
        logger.error(f"API simulare-regim error {year} user={user_id}: {e}")
        return jsonify({"error": "internal error"}), 500
    finally:
        session.close()

    from app.integrations.anaf.simulare_regim import simulare_regim
    regim_curent = profile.get("regim_impunere") or "SISTEM_REAL"
    # Override din param (ipoteză) are prioritate; altfel norma stocată în profil.
    norma_anuala = norma_override if norma_override is not None else profile.get("norma_venit_anuala")
    sim = simulare_regim(
        venit_brut=r.venit_brut,
        cheltuieli=r.cheltuieli,
        norma_anuala=norma_anuala,                        # override (ipoteză) sau stocată
        an=year,
        activity_code=profile.get("activity_code") or "",
        regim_curent=regim_curent,                        # RAW — gardianul îl aplică simulare_regim
        pensionar=bool(profile.get("is_pensionar")),
        asigurat_salariat=bool(profile.get("is_salariat")),
    )

    return jsonify({
        "an": year,
        "regim_curent": regim_curent,
        "judet": profile.get("judet"),                    # pentru norma-lookup live (A3.2)
        # Caz prezentare (NU eroare): fără venituri YTD → flag pentru UI ("înregistrează
        # venituri ca simularea să devină relevantă"). Funcția pură A1 rămâne neatinsă.
        "fara_venituri": (r.venit_brut or 0) <= 0,
        "real": sim.real,
        "norma": sim.norma,
        "recomandat": sim.recomandat,
        "diferenta": sim.diferenta,
        "avertismente_legale": sim.avertismente_legale,
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

    from app.domain.fiscal_profile import from_user_dict

    session = get_session()
    try:
        profile = users_repo.get_profile_dict(session, user_id) or {}
        totals = tax_engine.compute_period(
            session, user_id=user_id, year=year, month=month
        )
        vat_out = float(totals.get("vat_out_total") or 0.0)
        cota = float(totals.get("cota_tva") or cota_tva(date(year, month, 1)))  # cota perioadei (sursă unică)
        baza_intracom = round(vat_out / cota, 2) if vat_out > 0 else 0.0
        # D100 multi-brand (Uber sub-pas B): planul split per-platformă, calculat în
        # sesiune (vat_out_by_brand are nevoie de DB). Ignorat pentru D301/D390.
        d100_plan = tax_engine.compute_d100_plan(
            tax_engine.vat_out_by_brand(session, user_id=user_id, year=year, month=month),
            cota, from_user_dict(profile),
        ) if tip == "D100" else None
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
        # D100 → planul multi-brand (sursă unică); D301/D390 → baza_intracom (total).
        # Cota nerezident legacy păstrată ca fallback dacă planul lipsește.
        cota_nerez = from_user_dict(profile).cota_nerezident
        rez = decl.genereaza(tip, year, month, baza_intracom, firma=firma,
                             cota_nerezident=cota_nerez, d100_plan=d100_plan)
    except Exception as e:
        logger.error(f"API declaratie gen error {tip} {year}/{month} user={user_id}: {e}")
        return jsonify({"error": "internal error", "message": str(e)}), 500

    # D100 la cota 0 (scutit) / None (neconfigurat): rez.generat=False → NU
    # servim XML (ar fi gol). Întoarcem motivul + ghidul ca JSON (date la ANAF).
    if not rez.generat:
        return jsonify({
            "error": "negenerat",
            "motiv": rez.motiv_negenerat,        # "scutit" / "neconfigurat"
            "tip": rez.tip, "year": rez.an, "month": rez.luna,
            "ghid": rez.ghid_telegram,
            "ghid_plain": rez.ghid_plain,
        }), 400

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

        # A5 trust signals: status REAL integrări + last-synced (ZERO status inventat).
        from sqlalchemy import func
        from app.models import Document
        from app.integrations import bolt_sync
        bolt_st = bolt_sync.get_sync_status(user_id)
        last_doc = session.query(func.max(Document.created_at)).filter(
            Document.user_id == user_id
        ).scalar()
        last_doc_iso = (
            last_doc.isoformat() if hasattr(last_doc, "isoformat")
            else (str(last_doc) if last_doc else None)
        ) if last_doc else None
        integrari = {
            "telegram": {"connected": True},   # userul e în WebApp = adevărat
            "bolt": {
                "connected": bolt_st["connected"],
                "last_synced": bolt_st["last_synced"],
            },
            "documente": {"last_synced": last_doc_iso},
            "anaf": {"mode": "manual"},         # Contai pregătește, tu depui în SPV
        }

        return jsonify({
            "banca": profile.get("banca") or "",
            "iban": profile.get("iban") or "",
            "firma_nume": profile.get("firma_nume") or "",
            "firma_cui": profile.get("firma_cui") or "",
            "firma_forma_juridica": profile.get("firma_forma_juridica") or "PFA",
            "regim_impunere": profile.get("regim_impunere") or "",
            "norma_venit_anuala": profile.get("norma_venit_anuala"),
            "is_pensionar": bool(profile.get("is_pensionar")),
            "is_salariat": bool(profile.get("is_salariat")),
            # Activitate mixta (PAS 4b) — split temporal normă→real (afisare).
            "are_activitate_neeligibila_norma": bool(profile.get("are_activitate_neeligibila_norma")),
            "data_activitate_neeligibila": profile.get("data_activitate_neeligibila"),
            "cod_special_tva": profile.get("cod_special_tva") or "",
            # Regim nerezident D100 PER-PLATFORMĂ (#3 + Uber sub-pas C): "" = neconfigurat
            # → fără preselecție. Bolt cu fallback la deprecatul `regim_nerezident`.
            "regim_nerezident_bolt": (
                profile.get("regim_nerezident_bolt") or profile.get("regim_nerezident") or ""
            ),
            "regim_nerezident_uber": profile.get("regim_nerezident_uber") or "",
            "integrari": integrari,
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
    # Regim nerezident PER-PLATFORMĂ (Uber sub-pas C). Backward-compat: cheia veche
    # `regim_nerezident` (fără sufix) e tratată ca Bolt.
    regim_bolt = body.get("regim_nerezident_bolt") or body.get("regim_nerezident")
    regim_uber = body.get("regim_nerezident_uber")

    # validare minimala IBAN (RO + 22 caractere alfanumerice = 24 total)
    if iban:
        iban_clean = "".join(c for c in str(iban).upper() if c.isalnum())
        if iban_clean and not (iban_clean.startswith("RO") and len(iban_clean) == 24):
            return jsonify({
                "error": "invalid_iban",
                "message": "IBAN-ul pare invalid. Un IBAN romanesc are forma "
                           "RO + 22 caractere (24 in total).",
            }), 400

    # Regim nerezident D100 (#3 + sub-pas C): fiecare platformă validată cu
    # validatorul EI (seturi separate → codul Uber e respins pe Bolt și invers).
    # Gol → nu schimbăm (None); cod nevalid → respins (nu salvăm o rată greșită).
    if regim_bolt:
        if not users_repo.is_valid_regim_nerezident_bolt(regim_bolt):
            return jsonify({
                "error": "invalid_regim_nerezident",
                "message": "Regim nerezident Bolt invalid. Alege 2% (cu certificat) "
                           "sau 16% (fără). 0% e doar pentru Uber.",
            }), 400
    else:
        regim_bolt = None
    if regim_uber:
        if not users_repo.is_valid_regim_nerezident_uber(regim_uber):
            return jsonify({
                "error": "invalid_regim_nerezident",
                "message": "Regim nerezident Uber invalid. Alege 0% (cu certificat) "
                           "sau 16% (fără). 2% e doar pentru Bolt.",
            }), 400
    else:
        regim_uber = None

    session = get_session()
    try:
        user = users_repo.get_by_id(session, user_id)
        if user is None:
            return jsonify({"error": "user not found"}), 404
        users_repo.update_profile(
            session, user,
            banca=(banca if banca is not None else None),
            iban=(iban if iban is not None else None),
            regim_nerezident_bolt=regim_bolt,  # None → neschimbat (vezi update_profile)
            regim_nerezident_uber=regim_uber,
        )
        session.commit()
        profile = users_repo.get_profile_dict(session, user_id) or {}
        return jsonify({
            "ok": True,
            "banca": profile.get("banca") or "",
            "iban": profile.get("iban") or "",
            "regim_nerezident_bolt": (
                profile.get("regim_nerezident_bolt") or profile.get("regim_nerezident") or ""
            ),
            "regim_nerezident_uber": profile.get("regim_nerezident_uber") or "",
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
            "source_file_id": doc.source_file_id,
            "has_file": bool(doc.source_file_id),
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
