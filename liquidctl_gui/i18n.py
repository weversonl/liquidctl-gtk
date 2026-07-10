"""Locale selection: pt_BR gets Portuguese, everything else gets English (en_US).

English is the gettext source language, so it needs no .po/.mo files at all -
gettext falls back to the msgid text whenever no matching catalog is installed.
"""

from __future__ import annotations

import gettext
import locale
import os
from typing import Callable

DOMAIN = "liquidctl-gui"
_LOCALE_DIR = os.path.join(os.path.dirname(__file__), "..", "po", "locale")


def _detect_language() -> str:
    for env_var in ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
        value = os.environ.get(env_var)
        if value:
            if value.split(".")[0].split(":")[0].lower().startswith("pt_br"):
                return "pt_BR"
            return "en_US"
    try:
        lang, _ = locale.getlocale()
    except Exception:
        lang = None
    if lang and lang.lower().startswith("pt_br"):
        return "pt_BR"
    return "en_US"


def install() -> Callable[[str], str]:
    language = _detect_language()
    translation = gettext.translation(
        DOMAIN, localedir=_LOCALE_DIR, languages=[language], fallback=True
    )
    translation.install()
    return translation.gettext
