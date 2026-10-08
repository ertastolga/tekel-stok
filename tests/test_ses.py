"""WAV ses motoru (V1.2 M9b).

Korunan sözler:
  * sesler (işaret, seviye) başına geçerli WAV dosyası olarak üretilir; içerik
    aynıysa dosya yeniden yazılmaz,
  * çalma EŞZAMANSIZDIR (SND_ASYNC | SND_FILENAME | SND_NODEFAULT) — arayüz
    beklemez; dosya çalınamazsa Beep yedeği,
  * tür başına kapatma ve genel kapatma çalmayı tamamen durdurur,
  * seviye genliği değiştirir; sessizlik bölümleri sıfırdır, tonlar yumuşak
    başlar (tık sesi yok).
"""
from __future__ import annotations

import os
import struct

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app.ui import sound  # noqa: E402


@pytest.fixture(autouse=True)
def ses_durumu_temiz():
    yield
    sound.yapilandir(True, 2, None)
    sound._DOSYALAR.clear()


def _ornekler(wav: bytes) -> list[int]:
    n = struct.unpack("<I", wav[40:44])[0] // 2
    return list(struct.unpack(f"<{n}h", wav[44:44 + 2 * n]))


def test_wav_bicimi_ve_suresi():
    wav = sound.wav_bayt([(1200, 45)], 2)
    assert wav[:4] == b"RIFF" and wav[8:16] == b"WAVEfmt "
    bicim, kanal, oran, _bps, _blok, bit = struct.unpack("<HHIIHH", wav[20:36])
    assert (bicim, kanal, oran, bit) == (1, 1, sound.ORNEKLEME, 16)
    ornekler = _ornekler(wav)
    assert len(ornekler) == int(sound.ORNEKLEME * 0.045)
    assert ornekler[0] == 0, "yumuşak başlangıç: tık sesi yok"


def test_seviye_ve_sessizlik():
    tepe = {s: max(abs(o) for o in _ornekler(sound.wav_bayt([(800, 50)], s)))
            for s in sound.SEVIYELER}
    assert tepe[1] < tepe[2] < tepe[3] <= 32767
    sessiz = _ornekler(sound.wav_bayt([(0, 20)], 3))
    assert sessiz and set(sessiz) == {0}


def test_dosyalar_bir_kez_yazilir(tmp_path):
    dosyalar = sound.hazirla(tmp_path / "sounds", 3)
    assert set(dosyalar) == set(sound.ISARETLER)
    assert all(y.name.endswith("_3.wav") and y.read_bytes()[:4] == b"RIFF"
               for y in dosyalar.values())
    zaman = {ad: y.stat().st_mtime_ns for ad, y in dosyalar.items()}
    sound.hazirla(tmp_path / "sounds", 3)
    assert {ad: y.stat().st_mtime_ns for ad, y in dosyalar.items()} == zaman


def test_yazilamayan_klasor_beep_yedegine_duser(tmp_path, monkeypatch):
    engel = tmp_path / "dosya"
    engel.write_text("klasör değil")
    sound.yapilandir(True, 2, None, engel / "sounds")
    assert sound._DOSYALAR == {}
    calinan = []
    monkeypatch.setattr(sound, "_beep", lambda frequency, duration_ms: calinan.append(
        (frequency, duration_ms)))
    sound.blocked()
    assert calinan == [(380, 70), (300, 70)]


class _SahteWinsound:
    SND_FILENAME, SND_ASYNC, SND_NODEFAULT = 0x20000, 0x1, 0x2

    def __init__(self):
        self.cagrilar = []

    def PlaySound(self, ad, bayrak):  # noqa: N802
        self.cagrilar.append((ad, bayrak))


def test_eszamansiz_calma_ve_tur_kapatma(tmp_path, monkeypatch):
    sahte = _SahteWinsound()
    monkeypatch.setattr(sound, "winsound", sahte)
    beep = []
    monkeypatch.setattr(sound, "_beep", lambda **k: beep.append(k))
    sound.yapilandir(True, 1, {"scan", "success", "warning", "error"}, tmp_path)
    sound.scan()
    ad, bayrak = sahte.cagrilar[-1]
    assert ad.endswith("scan_1.wav")
    assert bayrak == sahte.SND_FILENAME | sahte.SND_ASYNC | sahte.SND_NODEFAULT
    sound.yapilandir(True, 1, {"success", "warning", "error"}, tmp_path)
    once = len(sahte.cagrilar)
    sound.scan()
    sound.price_check()                                # aynı tür (okutma)
    assert len(sahte.cagrilar) == once, "okutma türü kapalı"
    sound.success()
    assert sahte.cagrilar[-1][0].endswith("success_1.wav")
    sound.yapilandir(False, 1, None, tmp_path)
    sound.error()
    assert len(sahte.cagrilar) == once + 1 and beep == [], "genel kapatma"
