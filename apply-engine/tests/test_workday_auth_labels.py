
import re
from apply_engine.fill import AUTH_FIELD_LABELS

def test_auth_field_labels_match_motorola_create_account():
    for label in ("Password*", "Verify New Password*", "Email Address*", "Password", "Verify New Password"):
        clean = label.strip().rstrip("*").strip()
        assert AUTH_FIELD_LABELS.match(clean), label
