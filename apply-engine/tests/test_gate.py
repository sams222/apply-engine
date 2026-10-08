from datetime import date
import json

from apply_engine import fingerprint, gate
from apply_engine.cli import _answer_drift, _pre_submit_check
from apply_engine.queue import upsert_item

URL = "https://job-boards.greenhouse.io/acme/jobs/123"


def _setup(tmp_path):
    profile = tmp_path / "profile.json"
    profile.write_text('{"full_name": "Jordan Avery"}', encoding="utf-8")
    paths = {"queue_dir": tmp_path / "apply-engine-queue", "queue": tmp_path / "apply-queue.json", "profile": profile}
    item = {
        "id": "gh-acme-123", "status": "waiting_confirm", "url": URL, "company": "Acme", "job_title": "SWE Intern",
        "profile_path": str(profile), "profile_sha": gate.profile_sha(profile), "fingerprint": fingerprint.stamp(),
        "notes": ["hard-stop: submit not clicked"], "skipped": [],
        "filled": [
            {"label": "Resume", "mapped_to": "resume", "value": "Jordan.pdf", "method": "file"},
            {"label": "First Name*", "mapped_to": "first_name", "value": "Jordan", "method": "text"},
            {"label": "Are you authorized to work in the US?*", "mapped_to": "work_authorized_us", "value": "Yes",
             "method": "combobox"},
        ],
    }
    return paths, item


def test_clean_item_passes(tmp_path):
    paths, item = _setup(tmp_path)
    assert gate.blockers(item, paths) == []


def test_llm_guess_on_sensitive_question_blocks(tmp_path):
    paths, item = _setup(tmp_path)
    item["filled"].append({"label": "Are you legally authorized to work here?*", "value": "No", "method": "llm-pick"})
    assert any("sensitive" in b for b in gate.blockers(item, paths))


def test_essays_and_location_guesses_wait_for_approval_which_expires_on_change(tmp_path):
    paths, item = _setup(tmp_path)
    item["updated_at"] = "2026-09-27T18:00:00+00:00"
    item["filled"] += [{"label": "Why Acme?*", "value": "Acme builds maps.", "method": "llm-essay"},
                       {"label": "From where do you intend to work?*", "value": "SF office", "method": "llm-pick"}]
    assert len(gate.blockers(item, paths)) == 2
    item["approval"] = gate.approval_stamp(item)
    assert gate.blockers(item, paths) == []
    item["updated_at"] = "2026-09-28T09:00:00+00:00"
    assert gate.blockers(item, paths)


def test_flagged_essay_stale_build_changed_profile_and_missing_resume_block(tmp_path):
    paths, item = _setup(tmp_path)
    item["notes"].append("review essay: Why Acme?: stock phrase")
    item["fingerprint"] = {"tree": "old"}
    item["filled"] = [r for r in item["filled"] if r["method"] != "file"]
    paths["profile"].write_text('{"full_name": "Changed"}', encoding="utf-8")
    found = " | ".join(gate.blockers(item, paths))
    for needle in ("review essay", "older engine build", "profile changed", "resume"):
        assert needle in found


def test_record_submission_preserves_unknown_top_level_keys(tmp_path):
    paths, item = _setup(tmp_path)
    ledger = gate.ledger_path(paths)
    ledger.parent.mkdir(parents=True, exist_ok=True)
    ledger.write_text(json.dumps({
        "submitted": [{"queue_id": "meta-1", "url": "https://example.com/meta", "keys": ["url:example.com/meta"]}],
        "items": [{"company": "Figure", "note": "logged by hand"}],
        "owner": "sam",
    }), encoding="utf-8")
    gate.record_submission(paths, {"id": "first-run", "company": "Acme", "job_title": "SWE Intern", "url": URL})
    raw = json.loads(ledger.read_text(encoding="utf-8"))
    assert raw["items"] == [{"company": "Figure", "note": "logged by hand"}]
    assert raw["owner"] == "sam"
    assert any(r.get("queue_id") == "meta-1" for r in raw["submitted"])
    assert any(r.get("queue_id") == "first-run" for r in raw["submitted"])


def test_second_submission_of_same_posting_is_blocked(tmp_path):
    paths, item = _setup(tmp_path)
    gate.record_submission(paths, {"id": "first-run", "company": "Acme", "job_title": "SWE Intern",
                                   "url": URL + "?gh_src=abc"})
    assert gate.previous_submission(paths, URL, exclude_id=item["id"])["queue_id"] == "first-run"
    assert any("already submitted" in b for b in gate.blockers(item, paths))


def test_submitted_queue_item_counts_even_without_ledger(tmp_path):
    paths, item = _setup(tmp_path)
    upsert_item(paths["queue"], {**item, "id": "old", "status": "submitted"})
    assert gate.previous_submission(paths, URL, "Acme", "SWE Intern", exclude_id=item["id"])["queue_id"] == "old"


def test_daily_cap(tmp_path):
    paths, item = _setup(tmp_path)
    for i in range(2):
        gate.record_submission(paths, {"id": f"x{i}", "url": f"https://jobs.lever.co/other/{i}"})
    assert any("daily cap" in b for b in gate.blockers(item, paths, daily_cap=2, today=date.today()))


def test_confirm_refill_that_changed_an_answer_is_stopped(tmp_path):
    _, item = _setup(tmp_path)
    fresh = {**item, "filled": [dict(r) for r in item["filled"]]}
    fresh["filled"][2]["value"] = "No"
    assert _answer_drift(item, fresh)
    assert _pre_submit_check(item)(fresh)
    assert _pre_submit_check(item)({**item, "extra": {"readback_problems": []}}) == []


def test_reviewed_answers_include_required_radio_choices(tmp_path):
    from apply_engine.cli import _reviewed_answers

    review = tmp_path / "review.json"
    review.write_text(
        json.dumps({
            "filled": [
                {"label": "Which internship track are you applying for?*",
                 "value": "ML/AI Infrastructure", "method": "radio"},
                {"label": "Why Niantic?*", "value": "I build ML infra.", "method": "llm-essay"},
            ]
        }),
        encoding="utf-8",
    )
    got = _reviewed_answers(tmp_path)
    assert got["Which internship track are you applying for?*"] == "ML/AI Infrastructure"
    assert got["Why Niantic?*"] == "I build ML infra."


def test_digest_lists_waiting_items(tmp_path):
    paths, item = _setup(tmp_path)
    upsert_item(paths["queue"], {**item, "status": "needs_user", "notes": ["needs_user: posting is closed or removed"]})
    text = gate.digest(paths)
    assert "Waiting on you (1)" in text and "posting is closed" in text
