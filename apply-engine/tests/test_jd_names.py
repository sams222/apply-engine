from apply_engine.jd import _display_name


def test_display_name_prefers_posting_casing():
    assert _display_name("openai", "Join OpenAI. Apply at openai.com. OpenAI builds") == "OpenAI"
    assert _display_name("shieldai", "Shield AI builds autonomy") == "Shield AI"
    assert _display_name("ramp", "") == "Ramp"
    assert _display_name("Datadog", "") == "Datadog"
