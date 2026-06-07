"""
Test pentru înregistrarea job-urilor în scheduler (Faza 3 PAS 4).

Verifică: jobul nou monthly_summary e înregistrat (day=2, hour=9) ȘI cele 5
joburi existente rămân neatinse. Scheduler-ul se pornește și se oprește imediat
(jobul nu se declanșează — e programat pe ziua 2).
"""

from app.services.scheduler import start_scheduler


def test_monthly_summary_inregistrat_si_cele_5_pastrate():
    sch = start_scheduler("test-token")
    try:
        ids = {j.id for j in sch.get_jobs()}

        # jobul nou
        assert "monthly_summary" in ids

        # cele 5 existente — neatinse
        for jid in (
            "weekly_reminder", "weekly_dashboard", "fiscal_deadline_alert",
            "fiscal_monitoring", "proactive_alerts",
        ):
            assert jid in ids, f"job existent lipsă: {jid}"

        # trigger corect: ziua 2, ora 9
        trig = str(sch.get_job("monthly_summary").trigger)
        assert "day='2'" in trig
        assert "hour='9'" in trig
    finally:
        sch.shutdown(wait=False)
