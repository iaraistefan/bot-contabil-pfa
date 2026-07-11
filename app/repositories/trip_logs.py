"""
Pas A.3 - Repository pentru foaia de parcurs (trip_logs).

Operatii pe jurnalul de km auto: pornire/inchidere tura, listare lunara.
"""

from datetime import date

from app.models import TripLog, TRIP_STATUS_OPEN, TRIP_STATUS_CLOSED


# ============================================================
#       TURA DESCHISA
# ============================================================

def get_open_trip(session, user_id: int):
    """
    Returneaza tura deschisa (status=open) a user-ului, daca exista.
    Un user poate avea maxim o tura deschisa la un moment dat.
    """
    return (
        session.query(TripLog)
        .filter(
            TripLog.user_id == user_id,
            TripLog.status == TRIP_STATUS_OPEN,
        )
        .order_by(TripLog.id.desc())
        .first()
    )


# ============================================================
#       CREARE
# ============================================================

def create_open(session, user_id: int, vehicul_id: int,
                 odometer_start: int, trip_date: date,
                 ora_start: str = None, purpose: str = None) -> TripLog:
    """Creeaza o tura deschisa (start dat, stop urmeaza)."""
    t = TripLog(
        user_id=user_id,
        vehicul_id=vehicul_id,
        trip_date=trip_date,
        km=0.0,
        odometer_start=odometer_start,
        odometer_end=None,
        status=TRIP_STATUS_OPEN,
        ora_start=ora_start,
        ora_stop=None,
        purpose=purpose,
        period_year=trip_date.year,
        period_month=trip_date.month,
    )
    session.add(t)
    session.flush()
    return t


def create_complete(session, user_id: int, vehicul_id: int,
                     odometer_start: int, odometer_end: int,
                     trip_date: date, ora_start: str = None,
                     ora_stop: str = None, purpose: str = None) -> TripLog:
    """Creeaza o tura completa intr-un singur pas (start + stop deodata)."""
    km = float(odometer_end - odometer_start)
    t = TripLog(
        user_id=user_id,
        vehicul_id=vehicul_id,
        trip_date=trip_date,
        km=km,
        odometer_start=odometer_start,
        odometer_end=odometer_end,
        status=TRIP_STATUS_CLOSED,
        ora_start=ora_start,
        ora_stop=ora_stop,
        purpose=purpose,
        period_year=trip_date.year,
        period_month=trip_date.month,
    )
    session.add(t)
    session.flush()
    return t


# ============================================================
#       INCHIDERE
# ============================================================

def close_trip(session, trip: TripLog, odometer_end: int,
               ora_stop: str = None) -> TripLog:
    """Inchide o tura deschisa - completeaza odometrul final si km."""
    start = trip.odometer_start if trip.odometer_start is not None else odometer_end
    trip.odometer_end = odometer_end
    trip.km = float(odometer_end - start)
    trip.ora_stop = ora_stop
    trip.status = TRIP_STATUS_CLOSED
    session.flush()
    return trip


# ============================================================
#       LISTARE & INTEROGARI
# ============================================================

def get_by_id(session, trip_id: int, user_id: int):
    """Returneaza o tura a user-ului (user_id verificat - securitate)."""
    return (
        session.query(TripLog)
        .filter(TripLog.id == trip_id, TripLog.user_id == user_id)
        .first()
    )


def list_for_month(session, user_id: int, year: int, month: int):
    """Toate turele dintr-o luna, ordonate cronologic."""
    return (
        session.query(TripLog)
        .filter(
            TripLog.user_id == user_id,
            TripLog.period_year == year,
            TripLog.period_month == month,
        )
        .order_by(TripLog.trip_date, TripLog.id)
        .all()
    )


def list_closed_for_month(session, user_id: int, year: int, month: int):
    """Doar turele inchise dintr-o luna."""
    return (
        session.query(TripLog)
        .filter(
            TripLog.user_id == user_id,
            TripLog.period_year == year,
            TripLog.period_month == month,
            TripLog.status == TRIP_STATUS_CLOSED,
        )
        .order_by(TripLog.trip_date, TripLog.id)
        .all()
    )


def count_closed(session, user_id: int) -> int:
    """Numarul de ture inchise ale userului (pentru detectia 'prima tura')."""
    return (
        session.query(TripLog)
        .filter(
            TripLog.user_id == user_id,
            TripLog.status == TRIP_STATUS_CLOSED,
        )
        .count()
    )


def available_months(session, user_id: int):
    """Lista (an, luna) pentru care exista ture, descrescator."""
    rows = (
        session.query(TripLog.period_year, TripLog.period_month)
        .filter(TripLog.user_id == user_id)
        .distinct()
        .all()
    )
    return sorted({(r[0], r[1]) for r in rows}, reverse=True)


def delete(session, trip: TripLog) -> None:
    """Sterge definitiv o tura."""
    session.delete(trip)
    session.flush()


def to_dict(trip: TripLog) -> dict:
    """Serializare pentru audit log."""
    return {
        "id": trip.id,
        "trip_date": trip.trip_date.isoformat() if trip.trip_date else None,
        "km": trip.km,
        "odometer_start": trip.odometer_start,
        "odometer_end": trip.odometer_end,
        "status": trip.status,
        "purpose": trip.purpose,
    }
