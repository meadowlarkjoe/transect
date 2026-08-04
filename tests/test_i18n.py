"""i18n parity + missing-key gate. See scripts/i18n_check.py."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "scripts"))
import i18n_check


def test_i18n_parity_and_no_missing_keys():
    errors, _warnings, _stats = i18n_check.check()
    assert not errors, "\n".join(errors)
