from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def no_real_llm(monkeypatch):
    for var in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "DEEPSEEK_API_KEY", "GROK_API_KEY", "XAI_API_KEY", "OPENAI_API_KEY",
                "APPLY_ENGINE_LLM"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr("apply_engine.llm.KEY_DIR", Path("/nonexistent-apply-engine-keys"))
