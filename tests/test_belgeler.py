"""Belgeler koddan kopmasın (V1.2 M12c).

README kullanıcıya kısayolları, komut satırı seçeneklerini, sürümü ve ekran
adlarını söyler; kod değişip README kalırsa dükkân sahibi yanlış yönlendirilir.
``verify_build.ps1`` ise UTF-8 BOM'suz kaydedilirse PowerShell 5.1'de Türkçe
karşılaştırmaları bozar ve V1.1 yükseltme adımını kaybetmemelidir.
"""
from __future__ import annotations

import inspect
import re
from pathlib import Path

from app import config, main
from app.ui.shortcuts import SHORTCUTS

KOK = Path(__file__).resolve().parent.parent
README = (KOK / "README.md").read_text(encoding="utf-8")


def _kisayol_satirlari() -> dict[str, str]:
    """README kısayol tablosu: ``| `F1` | Hızlı Satış |`` → {"F1": "Hızlı Satış"}."""
    bolum = README.split("## 13. Klavye kısayolları", 1)[1].split("\n## ", 1)[0]
    return {
        m.group(1): m.group(2).strip()
        for m in re.finditer(r"^\| `([^`]+)` \| (.+?) \|$", bolum, re.MULTILINE)
    }


def test_readme_kisayol_tablosu_kodla_ayni():
    satirlar = _kisayol_satirlari()
    assert set(satirlar) == {k.key for k in SHORTCUTS}, "eksik ya da fazla kısayol satırı"
    for kisayol in SHORTCUTS:
        assert satirlar[kisayol.key].startswith(kisayol.label), (
            f"{kisayol.key}: README '{satirlar[kisayol.key]}', kod '{kisayol.label}'"
        )


def test_readme_komut_satiri_seceneklerini_anlatir():
    secenekler = set(re.findall(r'"(--[a-z-]+)"', inspect.getsource(main.parse_args)))
    assert {"--data-dir", "--surum-geri-donus", "--yonetici-pin-sifirla"} <= secenekler
    for secenek in secenekler:
        assert secenek in README, f"README {secenek} seçeneğini anlatmıyor"


def test_readme_surumu_ve_menu_adlari_guncel():
    assert config.APP_VERSION in README
    basliklar = set()
    for yol in (KOK / "app" / "ui" / "pages").rglob("*.py"):
        for baslik in re.findall(r'nav_title = "([^"]+)"', yol.read_text(encoding="utf-8")):
            basliklar.add(baslik.split("  ", 1)[-1].strip())
    assert len(basliklar) >= 18
    eksik = sorted(b for b in basliklar if b not in README)
    assert not eksik, f"README'de anılmayan ekranlar: {eksik}"
    # Eski adlar kalmamalı (M12b terim birliği, V1.2 menüsü).
    for eski in ("Pasife Al", "📊 Bugün", "Stok Girişi (F3)", "2 saatte bir, yalnızca"):
        assert eski not in README, eski


def test_verify_build_bom_ve_yukseltme_adimi():
    ham = (KOK / "verify_build.ps1").read_bytes()
    assert ham.startswith(b"\xef\xbb\xbf"), "verify_build.ps1 UTF-8 BOM ile kaydedilmeli"
    metin = ham.decode("utf-8-sig")
    assert "tests\\fixtures\\v1_1_ornek.db" in metin
    assert "guncelleme_oncesi_v1_v" in metin
    # Veri güvenliği: betik canlı veri klasörüne hiç başvurmaz, her açılış
    # geçici --data-dir kullanır ve çalışan TekelStok varken başlamaz.
    assert "LOCALAPPDATA" not in metin
    assert metin.count('"--data-dir"') >= 3
    assert "exit 2" in metin
