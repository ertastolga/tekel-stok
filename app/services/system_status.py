"""Sistem Durumu (V1.2 M10c, plan §6.5): uygulamanın sağlığı tek bakışta.

Gösterilenler: sürüm, şema, veri klasörü ve boyutu, hızlı bütünlük denetimi
(tam denetim ve derin tutarlılık denetimi İSTEK ÜZERİNE), uyarılar (göçten
önce de var olan ilişki ihlalleri dahil), son yedek / son yedek hatası,
toplam yedek boyutu, boş disk (veri + yedek), son okutma etkinliği, donanım
durumları, Python / Qt / SQLite / işletim sistemi ve paketli mi.

Her satır durumunu METİNLE de söyler (İyi / Uyarı / Hata / Bilgi); renk tek
başına anlam taşımaz. Qt bilmez: Qt sürümü arayüzden verilir.
"""
from __future__ import annotations

import platform
import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from app import config
from app.core.db import hedef_sema_surumu
from app.hardware.durum import CALISIYOR, DURUM_ADLARI, HATA as DONANIM_HATA

IYI = "IYI"
UYARI = "UYARI"
HATA = "HATA"
BILGI = "BILGI"
DURUMLAR = {IYI: "İyi", UYARI: "Uyarı", HATA: "Hata", BILGI: "Bilgi"}


@dataclass(frozen=True, slots=True)
class DurumSatiri:
    baslik: str
    deger: str
    durum: str = BILGI


def boyut_metni(bayt: int | None) -> str:
    if bayt is None:
        return "bilinmiyor"
    for birim, bolen in (("GB", 2**30), ("MB", 2**20), ("KB", 2**10)):
        if bayt >= bolen:
            return f"{bayt / bolen:.1f} {birim}".replace(".", ",")
    return f"{bayt} B"


def _zaman(utc: int | None) -> str:
    return datetime.fromtimestamp(utc).strftime("%d.%m.%Y %H:%M") if utc else "—"


class SystemStatusService:
    def __init__(self, db, settings, backup, hardware) -> None:
        self.db = db
        self.settings = settings
        self.backup = backup
        self.hardware = hardware

    def veri_boyutu(self) -> int:
        toplam = 0
        for son_ek in ("", "-wal", "-shm"):
            try:
                toplam += Path(str(self.db.path) + son_ek).stat().st_size
            except OSError:
                pass
        return toplam

    def hizli_denetim(self) -> DurumSatiri:
        try:
            sonuc = self.db.query_one("PRAGMA quick_check")
            metin = str(sonuc[0]) if sonuc else ""
        except sqlite3.Error as hata:
            return DurumSatiri("Hızlı bütünlük denetimi", f"yapılamadı: {hata}", HATA)
        if metin == "ok":
            return DurumSatiri("Hızlı bütünlük denetimi", "sorun yok", IYI)
        return DurumSatiri("Hızlı bütünlük denetimi", metin[:200], HATA)

    def derin_denetim(self) -> list[str]:
        """Tam bütünlük + derin tutarlılık denetimi (yavaş olabilir; istek üzerine)."""
        sorunlar = []
        butunluk = self.db.integrity_check()
        if butunluk != "ok":
            sorunlar.append(f"Bütünlük: {butunluk}")
        sorunlar.extend(self.db.check_invariants(deep=True))
        return sorunlar

    def uyarilar(self) -> list[str]:
        notlar = list(self.db.advisories())
        ihlaller = getattr(self.db, "preexisting_fk_violations", []) or []
        if ihlaller:
            tablolar = sorted({str(i[0]) for i in ihlaller})
            notlar.append(
                f"Güncellemeden önce de var olan {len(ihlaller)} ilişki ihlali bulundu "
                f"({', '.join(tablolar)}). Veri kaybı değildir; destek paketine eklenir.")
        return notlar

    def satirlar(self, qt_surumu: str = "") -> list[DurumSatiri]:
        durum = self.backup.status()
        surum = self.db.schema_version()
        hedef = hedef_sema_surumu()
        satirlar = [
            DurumSatiri("Sürüm", config.APP_VERSION),
            DurumSatiri("Veri şeması", f"v{surum}" + ("" if surum == hedef else f" (beklenen v{hedef})"),
                        IYI if surum == hedef else HATA),
            DurumSatiri("Veri klasörü", f"{config.data_dir()} · {boyut_metni(self.veri_boyutu())}"),
            self.hizli_denetim(),
        ]
        son = durum["son_yedek_utc"]
        hata = durum["son_hata"]
        if hata and hata[0] >= (son or 0):
            satirlar.append(DurumSatiri("Son yedek", f"{_zaman(son)} · SON DENEME BAŞARISIZ "
                                        f"({_zaman(hata[0])}): {hata[1]}", HATA))
        else:
            satirlar.append(DurumSatiri("Son yedek", _zaman(son), IYI if son else UYARI))
        satirlar.append(DurumSatiri(
            "Yedekler", f"{durum['otomatik_sayisi']} otomatik, {durum['gunluk_sayisi']} "
            f"günlük, {durum['elle_sayisi'] - durum['gunluk_sayisi']} diğer · toplam "
            f"{boyut_metni(durum['toplam_boyut'])} · {durum['otomatik_klasor']}"))
        en_az = 500 * 2**20
        for baslik, anahtar in (("Boş disk (veri)", "bos_alan_veri"),
                                ("Boş disk (yedek)", "bos_alan_yedek")):
            bos = durum[anahtar]
            satirlar.append(DurumSatiri(baslik, boyut_metni(bos),
                                        UYARI if bos is not None and bos < en_az else IYI))
        saniye = self.hardware.son_okutma_saniye()
        satirlar.append(DurumSatiri(
            "Son okutma", "bu oturumda okutma yok" if saniye is None
            else f"{int(saniye)} sn önce · bu oturumda {self.hardware.okutma_sayisi} okutma"))
        for d in self.hardware.durumlar():
            satirlar.append(DurumSatiri(
                d.ad, f"{DURUM_ADLARI[d.durum]} — {d.aciklama}",
                IYI if d.durum == CALISIYOR else (HATA if d.durum == DONANIM_HATA else BILGI)))
        satirlar.extend([
            DurumSatiri("Python", sys.version.split()[0]),
            DurumSatiri("Qt / PySide6", qt_surumu or "—"),
            DurumSatiri("SQLite", sqlite3.sqlite_version),
            DurumSatiri("İşletim sistemi", f"{platform.system()} {platform.release()} "
                                           f"({platform.version()})"),
            DurumSatiri("Paketli uygulama", "evet" if config.is_frozen() else "hayır "
                                                                           "(kaynak kod)"),
        ])
        return satirlar
