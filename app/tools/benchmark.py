"""Başarım ölçümü (V1.2 M11, plan §9).

Sentetik veri üzerinde (``app.tools.perf_dataset``) temsilî işlemleri ölçer ve
p50 / p95 / en kötü sürelerini raporlar. Yalnızca geliştirme ve dükkân
bilgisayarında DENEME aracıdır:

* ``TEKEL_DATA_DIR`` doğrulanmış bir karalama klasörü olmalıdır; gerçek veri
  klasörüyle çalışmayı REDDEDER (``veri_guvenligi``).
* Verilen veritabanı ASLA değiştirilmez: karalama klasörüne kopyalanır, her şey
  kopyada ölçülür (satış, içe aktarma gibi yazan işlemler dahil).
* "Bugün" veri setinin son günüdür (saat dikişi), böylece Bugün/Son 7 Gün gibi
  dönemler dolu ölçülür. Analiz ölçümleri önbelleği atlar (soğuk).

Kullanım::

    set TEKEL_DATA_DIR=C:\\karalama
    python -m app.tools.benchmark --veri C:\\karalama\\100k.db --cikti C:\\karalama\\rapor.json
    python -m app.tools.benchmark --veri ... --arayuz     (ana pencere kurulumu dahil)
    python -m app.tools.benchmark --veri ... --v1-bicimi  (V1.1 şemasından yükseltme dahil)
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import platform
import random
import shutil
import sqlite3
import statistics
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

#: Plan §9 hedefleri (p50 ile karşılaştırılır) + M11'de eklenen iki hedef:
#: açılıştaki sığ tutarlılık denetimi ve 30 günlük maliyet kapsamı.
HEDEFLER_MS: dict[str, float] = {
    "barkod_cozumle": 2, "urun_ara": 50, "sepete_ekle": 10, "odeme": 60,
    "fiyat_listesi": 400, "genel_bakis_bugun": 50, "egilim_30_gun": 150,
    "kategori_1_yil": 300, "urun_ciftleri_90_gun": 800, "ice_aktarma_onizleme_10k": 5000,
    "acilis_sig_denetim": 1000, "maliyet_kapsami_30_gun": 150,
}


class _Kayit(dict):
    """Her ölçüm bitince ilerlemeyi yazar (uzun ölçümlerde nerede olunduğu görünür)."""

    def __setitem__(self, anahtar, deger) -> None:
        super().__setitem__(anahtar, deger)
        print(f"  {anahtar}: p50 {deger['p50_ms']} ms (×{deger['tekrar']})",
              file=sys.stderr, flush=True)


def _olc(islev, tekrar: int, isinma: int = 2) -> dict:
    for _ in range(isinma):
        islev()
    sureler = []
    for _ in range(tekrar):
        bas = time.perf_counter_ns()
        islev()
        sureler.append((time.perf_counter_ns() - bas) / 1e6)
    sureler.sort()
    return {
        "tekrar": tekrar,
        "p50_ms": round(statistics.median(sureler), 3),
        "p95_ms": round(sureler[max(0, int(len(sureler) * 0.95) - 1)], 3),
        "en_kotu_ms": round(sureler[-1], 3),
    }


def _bir_kez(islev) -> dict:
    bas = time.perf_counter_ns()
    sonuc = islev()
    sure = (time.perf_counter_ns() - bas) / 1e6
    return {"tekrar": 1, "p50_ms": round(sure, 1), "p95_ms": round(sure, 1),
            "en_kotu_ms": round(sure, 1), "_sonuc": sonuc}


def v1_bicimine_indir(kaynak: Path, hedef: Path) -> None:
    """Ölçüm için: güncel şemadaki veriyi İLK şemaya (v1 = V1.1) taşır.

    Yalnızca v1 tablolarının v1 sütunları kopyalanır; sonraki sürümlerin
    sütun ve tabloları düşer, sürüm damgası 1 olur. Böylece "V1.1 verisi →
    güncel sürüm" yükseltmesi (göç öncesi yedek + bütün göçler) büyük veride
    ölçülebilir (plan §9). Kaynak salt okunur açılır.
    """
    from app.core import schema as sema

    hedef.unlink(missing_ok=True)
    conn = sqlite3.connect(Path(hedef).resolve().as_uri(), uri=True)
    try:
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute("ATTACH DATABASE ? AS kaynak", (f"{Path(kaynak).resolve().as_uri()}?mode=ro",))
        for adim in sema._V1_TABLES:
            conn.execute(adim)
        tablolar = [r[0] for r in conn.execute(
            "SELECT name FROM main.sqlite_master WHERE type = 'table' "
            "AND name NOT LIKE 'sqlite_%'")]
        for tablo in tablolar:
            # Üretilmiş (GENERATED) sütunlar yazılamaz: table_xinfo "hidden" ≠ 0.
            sutunlar = [r[1] for r in conn.execute(f'PRAGMA main.table_xinfo("{tablo}")')
                        if r[6] == 0]
            liste = ", ".join(f'"{s}"' for s in sutunlar)
            conn.execute(f'INSERT INTO main."{tablo}" ({liste}) '
                         f'SELECT {liste} FROM kaynak."{tablo}"')
        for adim in sema._V1_INDEXES:
            conn.execute(adim)
        conn.execute("UPDATE schema_meta SET value = '1' WHERE key = 'schema_version'")
        conn.commit()
        conn.execute("DETACH DATABASE kaynak")
    finally:
        conn.close()


def olc(veri: Path, calisma: Path, arayuz: bool = False, tekrar: int = 30,
        v1_bicimi: bool = False) -> dict:
    from app.analytics import donemler as dn
    from app.analytics import egilimler, kar, ozet, sepetler
    from app.analytics import urunler as ua
    from app.core import clock
    from app.core.db import open_database
    from app.services.cart_service import Cart
    from app.services.container import build_services

    kopya = calisma / "olcum.db"
    calisma.mkdir(parents=True, exist_ok=True)
    for son_ek in ("", "-wal", "-shm"):
        Path(str(kopya) + son_ek).unlink(missing_ok=True)
    if v1_bicimi:
        v1_bicimine_indir(veri, kopya)
    else:
        shutil.copyfile(veri, kopya)
    sonuc: dict = {"veri": veri.name, "ortam": {
        "python": sys.version.split()[0], "sqlite": sqlite3.sqlite_version,
        "isletim_sistemi": f"{platform.system()} {platform.release()}",
        "islemci": platform.processor(), "veri_bayt": veri.stat().st_size,
    }, "olcumler": _Kayit()}
    o = sonuc["olcumler"]
    rng = random.Random(7)

    ro = sqlite3.connect(f"file:{kopya}?mode=ro", uri=True)
    try:
        son_gun = ro.execute("SELECT MAX(business_date) FROM sales").fetchone()[0]
        sema = ro.execute("SELECT value FROM schema_meta WHERE key = 'schema_version'").fetchone()
        sonuc["sema_once"] = int(sema[0]) if sema else 0
    finally:
        ro.close()
    bugun = datetime.fromisoformat(son_gun).replace(hour=18)
    an = {"t": bugun}
    with clock.use_clock(yerel=lambda: an["t"], tekduze=lambda: an["t"].timestamp()):
        # İlk açılış: veri eski şemadaysa güncelleme (yedek + göç) dahildir.
        o["acilis_ilk"] = _bir_kez(lambda: open_database(kopya).close())
        o["acilis_veritabani"] = _bir_kez(lambda: open_database(kopya).close())
        db = open_database(kopya)
        svc = build_services(db)
        sonuc["sema_sonra"] = db.schema_version()
        try:
            o["acilis_sig_denetim"] = _bir_kez(lambda: len(db.check_invariants()))
            o["derin_denetim"] = _bir_kez(lambda: len(db.check_invariants(deep=True)))
            o["quick_check"] = _bir_kez(lambda: db.query_one("PRAGMA quick_check")[0])

            barkodlar = [r[0] for r in db.query(
                "SELECT barcode_norm FROM product_barcodes WHERE active = 1")]
            urunler = [dict(r) for r in db.query(
                "SELECT id, name FROM products WHERE is_active = 1 AND sale_price IS NOT NULL")]
            o["barkod_cozumle"] = _olc(lambda: svc.barcodes.resolve(rng.choice(barkodlar)),
                                       max(200, tekrar))
            kelimeler = [u["name"].split()[0][:4] for u in urunler[:200]]
            o["urun_ara"] = _olc(lambda: svc.products.search_for_sale(rng.choice(kelimeler)),
                                 tekrar)
            sepet = Cart()
            o["sepete_ekle"] = _olc(
                lambda: svc.cart.add_product(sepet, rng.choice(urunler)["id"]), tekrar)

            def odeme():
                s = Cart()
                for _ in range(rng.randint(1, 3)):
                    svc.cart.add_product(s, rng.choice(urunler)["id"])
                svc.cart.checkout(s, payment_method="NAKIT")
            o["odeme"] = _olc(odeme, max(200, tekrar))

            o["urun_listesi"] = _olc(lambda: svc.products.search(limit=100), tekrar)
            o["urun_listesi_metin"] = _olc(
                lambda: svc.products.search(text=rng.choice(kelimeler), limit=100), tekrar)
            o["fiyat_listesi"] = _olc(lambda: svc.pricing.listele(limit=500), max(10, tekrar // 3))
            o["kategori_agaci"] = _olc(lambda: svc.categories.tree(), tekrar)
            o["gecmis_satislar"] = _olc(lambda: db.query(
                "SELECT s.*, (SELECT i.product_name_snapshot FROM sale_items i "
                " WHERE i.sale_id = s.id ORDER BY i.line_no LIMIT 1) AS ilk FROM sales s "
                "WHERE s.entry_type = 'SALE' ORDER BY s.id DESC LIMIT 100 OFFSET 0"), tekrar)

            gun = son_gun
            bugun_d = dn.hazir(dn.BUGUN, gun)
            son30 = dn.ozel((bugun.date() - timedelta(days=29)).isoformat(), gun)
            son90 = dn.ozel((bugun.date() - timedelta(days=89)).isoformat(), gun)
            yil = dn.ozel((bugun.date() - timedelta(days=364)).isoformat(), gun)
            az = max(5, tekrar // 3)
            o["genel_bakis_bugun"] = _olc(lambda: ozet.genel_bakis(db, bugun_d), tekrar)
            o["genel_bakis_bu_ay"] = _olc(lambda: ozet.genel_bakis(db, dn.hazir(dn.BU_AY, gun)),
                                          tekrar)
            o["egilim_saatlik_bugun"] = _olc(lambda: egilimler.saatlik(db, bugun_d), tekrar)
            o["egilim_30_gun"] = _olc(lambda: egilimler.gunluk(db, son30), tekrar)
            o["egilim_1_yil_aylik"] = _olc(lambda: egilimler.aylik(db, yil), az)
            o["en_cok_satanlar_30_gun"] = _olc(lambda: ua.en_cok_adet(db, son30), az)
            o["kategori_1_yil"] = _olc(lambda: ua.kategoriler(db, yil), az)
            o["urun_ciftleri_90_gun"] = _olc(lambda: sepetler.urun_ciftleri(db, son90), az)
            o["kategori_ciftleri_90_gun"] = _olc(
                lambda: sepetler.kategori_ciftleri(db, son90), az)
            o["maliyet_kapsami_30_gun"] = _olc(lambda: kar.maliyet_kapsami(db, son30), az)
            o["maliyet_kapsami_1_yil"] = _olc(lambda: kar.maliyet_kapsami(db, yil), 3, 1)
            o["analiz_onbellekli_genel"] = _olc(lambda: svc.analytics.genel(bugun_d), tekrar)

            def bekletme():
                s = Cart()
                svc.cart.add_product(s, rng.choice(urunler)["id"])
                kimlik = svc.cart.park(s)
                svc.cart.resume_parked(kimlik)
            o["bekleyen_sepet_ac"] = _olc(bekletme, az)

            yedekler = calisma / "yedekler"
            svc.settings.set("manual_backup_dir", str(yedekler))
            o["yedek_al"] = _olc(lambda: svc.backup.create_manual(), 3, 0)
            an["t"] += timedelta(days=1)
            svc.sales.quick_sale(urunler[0]["id"])
            o["gunluk_yedek"] = _bir_kez(lambda: str(svc.backup.create_daily()))

            # İçe aktarma: mevcut 10 000 (ya da daha az) ürünün fiyatı %1 artmış liste.
            liste = calisma / "ice_aktarma.csv"
            satirlar = db.query(
                "SELECT b.barcode_norm, p.name, p.sale_price FROM products p JOIN "
                "product_barcodes b ON b.product_id = p.id AND b.active = 1 "
                "WHERE p.is_active = 1 AND p.sale_price IS NOT NULL GROUP BY p.id LIMIT 10000")
            with open(liste, "w", encoding="utf-8-sig", newline="") as dosya:
                yazici = csv.writer(dosya, delimiter=";")
                yazici.writerow(["Barkod", "Ürün adı", "Satış fiyatı"])
                for r in satirlar:
                    yazici.writerow([r[0], r[1], f"{r[2] * 101 // 100 / 100:.2f}".replace(".", ",")])
            from app.importers import alanlar as al
            from app.importers.okuyucu import oku

            tablo = oku(liste)
            esleme = al.otomatik_esle(tablo.basliklar)
            o["ice_aktarma_onizleme_10k"] = _bir_kez(
                lambda: svc.imports.onizle(tablo, esleme).sayilar()["guncellenecek"])
            plan = svc.imports.onizle(tablo, esleme)
            o["ice_aktarma_uygula_10k"] = _bir_kez(
                lambda: svc.imports.uygula(plan, liste.name, "0" * 64).guncellenen)
            o["destek_paketi"] = _bir_kez(lambda: str(svc.support.olustur(
                calisma / "destek.zip", self_test=lambda: "atlandı (ölçüm)")))

            if arayuz:
                os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
                from PySide6.QtWidgets import QApplication

                from app.ui import theme
                from app.ui.main_window import MainWindow

                from PySide6.QtWidgets import QDialog, QMessageBox

                uyg = QApplication.instance() or QApplication([])
                theme.apply_theme(uyg)
                # Ölçümde açılış soruları (taslak kurtarma vb.) beklemesin.
                QMessageBox.exec = lambda self: QMessageBox.StandardButton.Ok
                QDialog.exec = lambda self: QDialog.DialogCode.Rejected
                pencere = {}
                o["ana_pencere_kurulum"] = _bir_kez(
                    lambda: pencere.setdefault("p", MainWindow(svc)) and None)
                o["ana_pencere_ilk_tazeleme"] = _bir_kez(
                    lambda: (pencere["p"].show(), pencere["p"].refresh_today(),
                             uyg.processEvents()) and None)
                o["analiz_sayfasi_ilk_acilis"] = _bir_kez(
                    lambda: (pencere["p"].go_to("panel"), uyg.processEvents()) and None)
                pencere["p"].close()
        finally:
            svc.close()
    sonuc["sig_denetim_sorun"] = o["acilis_sig_denetim"].get("_sonuc")
    sonuc["derin_denetim_sorun"] = o["derin_denetim"].get("_sonuc")
    for olcum in o.values():
        olcum.pop("_sonuc", None)
    sonuc["hedefler_ms"] = HEDEFLER_MS
    return sonuc


def hedef_disi(sonuc: dict) -> dict[str, tuple[float, float]]:
    """Hedefini (p50) aşan ölçümler: ``{ad: (p50, hedef)}``."""
    return {ad: (s["p50_ms"], sonuc["hedefler_ms"][ad])
            for ad, s in sonuc["olcumler"].items()
            if ad in sonuc["hedefler_ms"] and s["p50_ms"] > sonuc["hedefler_ms"][ad]}


def markdown(sonuc: dict) -> str:
    satirlar = [f"### {sonuc['veri']} (şema v{sonuc.get('sema_once')} -> "
                f"v{sonuc.get('sema_sonra')})", "",
                "| İşlem | Tekrar | p50 (ms) | p95 (ms) | En kötü (ms) | Hedef (ms) |",
                "|---|---:|---:|---:|---:|---:|"]
    for ad, s in sonuc["olcumler"].items():
        hedef = sonuc["hedefler_ms"].get(ad, "")
        satirlar.append(f"| {ad} | {s['tekrar']} | {s['p50_ms']} | {s['p95_ms']} | "
                        f"{s['en_kotu_ms']} | {hedef} |")
    return "\n".join(satirlar)


def main(argv: list[str] | None = None) -> int:
    from app.tools import veri_guvenligi

    ayr = argparse.ArgumentParser(description="TekelStok başarım ölçümü")
    ayr.add_argument("--veri", required=True)
    ayr.add_argument("--cikti")
    ayr.add_argument("--arayuz", action="store_true")
    ayr.add_argument("--tekrar", type=int, default=30)
    ayr.add_argument("--v1-bicimi", action="store_true",
                     help="kopyayı önce V1.1 şemasına indir (yükseltme süresi ölçülür)")
    args = ayr.parse_args(argv)
    try:
        karalama = veri_guvenligi.karalama_klasoru()
        veri = Path(args.veri).resolve()
        gercek = veri_guvenligi.gercek_veri_klasoru()
        if gercek is not None and (veri == gercek or gercek in veri.parents):
            raise veri_guvenligi.GercekVeriKlasoruHatasi(
                "Gerçek veri ölçülmez; kopyasını karalama klasörüne alıp onu verin.")
    except veri_guvenligi.GercekVeriKlasoruHatasi as hata:
        print(f"REDDEDİLDİ: {hata}", file=sys.stderr)
        return 2
    sonuc = olc(veri, karalama / "olcum", arayuz=args.arayuz, tekrar=args.tekrar,
                v1_bicimi=args.v1_bicimi)
    if args.cikti:
        Path(args.cikti).write_text(json.dumps(sonuc, ensure_ascii=False, indent=1),
                                    encoding="utf-8")
    # Konsol kod sayfası (cp1254) her karakteri yazamayabilir: rapor yine basılsın.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    print(markdown(sonuc))
    return 0


if __name__ == "__main__":
    sys.exit(main())
