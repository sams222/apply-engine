"""Offline regression for the 2026-10-12 misses: Google careers + Qualcomm (Eightfold) Jobright-only cards.

Run: python3 scripts/hunt/test_vendor_resolvers.py   (no network; exits 0 on success)
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ats_recover as a  # noqa: E402

GOOGLE_BODY = ('x["75665705386549958","Forward Deployed Engineering Intern, BS/MS, Summer 2027","https://..."'
               '["135156989620560582","Forward Deployed Engineering Intern, BS/MS, 2027","https://..."'
               '["88543982287495878","GenAI Forward Deployed Engineer, Google Cloud (English, Korean)",""')
QCOM_BODY = json.dumps({"status": 200, "data": {"positions": [
    {"id": 446720740529, "name": "Software Engineering Internship - Summer 2027", "postedTs": 1789689600,
     "locations": ["San Diego, California", "New York City, New York"]},
    {"id": 446720740530, "name": "Machine Learning & Artificial Intelligence Engineering Internship – Summer 2027"},
]}})


def fetcher(url):
    if url.startswith("https://www.google.com/about/careers/applications/jobs/results?q="):
        return 200, GOOGLE_BODY
    if url.startswith("https://careers.qualcomm.com/api/pcsx/search"):
        return 200, QCOM_BODY
    return 404, ""


def main():
    a.set_fetcher(fetcher)
    try:
        assert a.ats_of("https://careers.qualcomm.com/careers/job/446720740529") == "eightfold"
        assert a.ats_of("https://www.google.com/about/careers/applications/jobs/results/1-x") == "google"
        assert a.has_vendor_resolver("Google") and a.has_vendor_resolver("Qualcomm")
        assert not a.has_vendor_resolver("Stripe")

        r, why = a.recover("Google", "Forward Deployed Engineering Intern, BS/MS, Summer 2027", [], network=True)
        assert r, why
        assert "75665705386549958" in r["url"] and r["ats"] == "google", r  # not the sibling 2027 req

        r, why = a.recover("Qualcomm", "Software Engineering Internship - Summer 2027", [], network=True)
        assert r, why
        assert r["url"] == "https://careers.qualcomm.com/careers/job/446720740529" and r["ats"] == "eightfold", r
        assert "ATS posted 2026-09-18" in r["note"], r["note"]

        r, why = a.recover("Qualcomm", "Hardware Verification Intern", [], network=True)
        assert r is None, r

        r, why = a.recover("Qualcomm", "Software Engineering Internship - Summer 2027", [], network=False)
        assert r is None  # offline/no-network path unchanged
    finally:
        a.set_fetcher(None)
    print("OK test_vendor_resolvers")


if __name__ == "__main__":
    main()


def test_category_and_phd():
    import os
    os.environ.setdefault("HUNT_OFFLINE", "1")
    import run_hunt as r
    assert r.jobright_category("Forward Deployed Engineering Intern, BS/MS, Summer 2027", "", True) == "Software"
    assert r.PHD_ONLY.search("People Analytics Intern, PhD, Summer 2027")
    print("OK test_category_and_phd")


if __name__ == "__main__":
    test_category_and_phd()
