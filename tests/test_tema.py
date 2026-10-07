"""Tema jeton katmanı (V1.2 M2a).

Korunan sözler:
  * renkler TEK kaynaktan (``ThemeTokens``) gelir; stil sayfasındaki her renk
    etkin temanın bir jetonudur,
  * sayfalar renk/ölçüyü MODÜL ÜZERİNDEN okur (``theme.DANGER``); adla içe
    aktarma, varsayılan argümanda ya da modül/sınıf düzeyinde yakalama yoktur —
    yoksa açılışta seçilen tema (M9a) bazı yerlerde uygulanmazdı,
  * ``app/ui`` içinde ``theme.py`` dışında renk sabiti yazılmaz,
  * yazı tipi ve stil sayfası ölçüleri ÇAĞRI ANINDA okunur.
"""
from __future__ import annotations

import ast
import dataclasses
import os
import re
from pathlib import Path

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app.ui import metrics, theme  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
UI = ROOT / "app" / "ui"
RENK = re.compile(r"#[0-9A-Fa-f]{6}\b|#[0-9A-Fa-f]{3}\b|rgba?\(")


@pytest.fixture
def acik_temaya_don():
    yield
    theme.set_tokens(theme.LIGHT)


def _ui_dosyalari(haric=("theme.py", "metrics.py")):
    for yol in UI.rglob("*.py"):
        if yol.name in haric:
            continue
        yield yol, ast.parse(yol.read_text(encoding="utf-8"), filename=str(yol))


def test_stil_sayfasindaki_her_renk_bir_jetondur():
    jetonlar = {
        deger for alan, deger in dataclasses.asdict(theme.LIGHT).items()
        if isinstance(deger, str) and alan != "ad"
    }
    stil = theme.build_stylesheet(theme.LIGHT)
    bulunan = set(re.findall(r"#[0-9A-Fa-f]{6}\b|rgba?\([^)]*\)", stil))
    assert bulunan and bulunan <= jetonlar, bulunan - jetonlar


def test_tema_secimi_modul_adlarini_ve_stil_sayfasini_degistirir(acik_temaya_don):
    deneme = dataclasses.replace(theme.LIGHT, ad="DENEME", danger="#123456", bg="#ABCDEF")
    theme.set_tokens(deneme)
    assert theme.tokens() is deneme
    assert theme.DANGER == "#123456"
    assert theme.level_colors(3)[0] == "#123456"
    stil = theme.build_stylesheet()
    assert "#123456" in stil and "#ABCDEF" in stil
    assert theme.LIGHT.danger not in stil
    renk = theme.build_palette().color(theme.build_palette().ColorRole.Window)
    assert renk.name().upper() == "#ABCDEF"


def test_olculer_cagri_aninda_okunur(monkeypatch):
    monkeypatch.setattr(metrics, "FONT_BASE_PT", 14.5)
    monkeypatch.setattr(metrics, "FONT_TOTAL_PT", 41.0)
    assert theme.base_font().pointSizeF() == 14.5
    assert "41.0pt" in theme.build_stylesheet()


def test_ui_tema_ve_olcu_sabitlerini_adla_ice_aktarmaz():
    ihlal = []
    for yol in (ROOT / "app").rglob("*.py"):
        agac = ast.parse(yol.read_text(encoding="utf-8"), filename=str(yol))
        for dugum in ast.walk(agac):
            if isinstance(dugum, ast.ImportFrom) and dugum.module in (
                "app.ui.theme", "app.ui.metrics"
            ):
                ihlal.append(f"{yol.relative_to(ROOT)}:{dugum.lineno}")
    assert ihlal == [], ihlal


def _tema_erisimi_var(dugum) -> bool:
    return any(
        isinstance(alt, ast.Attribute)
        and isinstance(alt.value, ast.Name)
        and alt.value.id in ("theme", "metrics")
        for alt in ast.walk(dugum)
    )


def test_tema_degerleri_ice_aktarma_aninda_yakalanmaz():
    """Varsayılan argüman, modül ya da sınıf düzeyi atama tema/ölçü okuyamaz."""
    ihlal = []
    for yol, agac in _ui_dosyalari():
        for dugum in ast.walk(agac):
            if isinstance(dugum, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for varsayilan in [*dugum.args.defaults, *dugum.args.kw_defaults]:
                    if varsayilan is not None and _tema_erisimi_var(varsayilan):
                        ihlal.append(f"{yol.name}:{dugum.lineno} varsayılan argüman")
        govdeler = [agac.body] + [
            d.body for d in ast.walk(agac) if isinstance(d, ast.ClassDef)
        ]
        for govde in govdeler:
            for dugum in govde:
                if isinstance(dugum, (ast.Assign, ast.AnnAssign)) and dugum.value is not None:
                    if _tema_erisimi_var(dugum.value):
                        ihlal.append(f"{yol.name}:{dugum.lineno} düzey ataması")
    assert ihlal == [], ihlal


def test_ui_icinde_tema_disinda_renk_sabiti_yoktur():
    ihlal = []
    for yol, agac in _ui_dosyalari(haric=("theme.py",)):
        for dugum in ast.walk(agac):
            if isinstance(dugum, ast.Constant) and isinstance(dugum.value, str):
                if RENK.search(dugum.value):
                    ihlal.append(f"{yol.relative_to(ROOT)}:{dugum.lineno}")
    assert ihlal == [], ihlal
