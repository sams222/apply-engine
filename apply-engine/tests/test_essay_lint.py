from apply_engine.essay_lint import problems

FACTS = ("- Software Engineering Intern at Brightwork (2025) (experience)\n"
         "- Relay (project)\n- Cragline (project)\n"
         "Relay: Local orchestration for Claude + Codex CLIs. SSE live dashboard.")


def test_clean_specific_answer_passes():
    text = (
        "My side project Relay runs Claude and Codex side by side and streams each lane's state to a live "
        "dashboard. Datadog does that for production fleets. I'd want to work on the alerting side."
    )
    assert problems(text, posting="Datadog observability", question="Why Datadog?", facts=FACTS) == []


def test_slop_is_flagged():
    text = (
        "Datadog's innovative platform aligns with my passion for backend systems — I am confident I would be "
        "a great fit and I'm excited to contribute!"
    )
    found = " | ".join(problems(text, question="Why Datadog?", facts=FACTS))
    for needle in ("dash", "innovative", "align", "passion", "confident", "great fit", "excited to contribute", "exclamation"):
        assert needle in found


def test_invented_anecdotes_are_flagged_unless_in_notes():
    text = "The hard part was the data, and it taught me patience. I built the map layer."
    assert len(problems(text, facts=FACTS)) == 3
    notes = FACTS + " PROJECT NOTES: the hard part was the data and it taught me patience; i built the map layer"
    assert problems(text, facts=notes) == []


def test_team_and_hard_parts_need_note_evidence():
    text = "My team built MetroMap at HackCity. The hardest part was a cluttered map."
    assert len(problems(text, facts=FACTS)) == 2
    notes = FACTS + " MetroMap: Five-person team project at HackCity. Hard parts: a cluttered map."
    assert problems(text, facts=notes) == []
    notes_line = "\n- Relay: Team hackathon project (Devpost)."
    solo = problems("I built Relay to run two agents. It made me want to work on tooling.", facts=FACTS + notes_line)
    assert any("team project" in p for p in solo) and any("made me want" in p for p in solo)


def test_resume_dump_is_flagged_but_allowed_when_asked():
    text = "I used Python, Pandas, NumPy, PyTorch and FastAPI at Brightwork, Relay, and Cragline."
    assert any("technologies" in p for p in problems(text, question="Why us?", facts=FACTS))
    assert any("experiences" in p for p in problems(text, question="Why us?", facts=FACTS))
    assert problems(text, question="What technologies are you comfortable with?", facts=FACTS) == []


def test_posting_words_are_allowed():
    text = "The posting says the team works in a fast-paced environment on end-to-end ownership."
    assert problems(text, posting="a fast-paced team with end-to-end ownership", facts=FACTS) == []
