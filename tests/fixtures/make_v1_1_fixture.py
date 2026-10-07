"""V1.0 / V1.1 örnek veritabanı üretici (V1.2 göç testleri için).

Bu betik ÜRÜN KODUNA DOKUNMAZ; yalnızca belirtilen sürümün ``app`` paketini
kullanarak gerçekçi bir veritabanı üretir. Üretilen dosya, V1.2 göçlerinin
gerçek bir V1.1 (ve V1.0) veritabanını doğru yükselttiğini kanıtlamak için
``tests/fixtures`` altına işlenir.

KURALLAR
--------
* Yalnızca TAM OLARAK o sürümün kaynak ağacıyla çalışır: ``--kok`` altındaki
  ``app`` klasörünün git ağaç kimliği, ``--surum`` için beklenen kimlikle aynı
  olmalıdır. Aksi hâlde reddeder. Sonradan yeniden üretmek için:

      git worktree add <gecici> v1.1.0-rc1        (V1.1)
      git worktree add <gecici> 7013590           (V1.0)
      python tests/fixtures/make_v1_1_fixture.py --surum 1.1 --kok <gecici> --cikti <dosya>

* ``TEKEL_DATA_DIR`` mutlaka bir karalama klasörüne ayarlanmış olmalıdır ve
  sahibin gerçek veri klasörünü (%LOCALAPPDATA%\\TekelStok) göstermemelidir.
* Tarihler sabittir (2026-09-01..03); saat ``app.core.clock.local_now`` ve
  ``time.time`` yamalanarak sabitlenir. Ürün kodunda saat enjeksiyonu yoktur.
* Ham dosyada derin değişmez denetimi ÇALIŞTIRILMAZ: V1.1'de günler arası geri
  almadan sonra I23 ve fiş geri almasından sonra I31 yanlış alarm verir
  (D-04, D-17). Bunlar V1.2 M1'de kırmızı→yeşil kanıtı olarak kullanılır.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

BEKLENEN_KAYNAK = {"1.1": "v1.1.0-rc1", "1.0": "7013590"}


def _git(kok: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=kok, capture_output=True, text=True, check=True
    ).stdout.strip()


def _guvenli_veri_klasoru() -> Path:
    deger = os.environ.get("TEKEL_DATA_DIR", "").strip()
    if not deger:
        sys.exit("REDDEDILDI: TEKEL_DATA_DIR bir karalama klasörüne ayarlanmalı.")
    yol = Path(deger).expanduser().resolve()
    yerel = os.environ.get("LOCALAPPDATA")
    if yerel:
        gercek = (Path(yerel) / "TekelStok").resolve()
        if yol == gercek or gercek in yol.parents:
            sys.exit("REDDEDILDI: sahibin gerçek veri klasörü kullanılamaz.")
    return yol


def _kaynak_dogrula(kok: Path, surum: str) -> str:
    beklenen = _git(kok, "rev-parse", f"{BEKLENEN_KAYNAK[surum]}:app")
    mevcut = _git(kok, "rev-parse", "HEAD:app")
    durum = _git(kok, "status", "--porcelain", "--", "app")
    if mevcut != beklenen or durum:
        sys.exit(
            f"REDDEDILDI: {kok} altındaki app ağacı V{surum} değil "
            f"(beklenen {beklenen}, bulunan {mevcut}, değişiklik: {bool(durum)})."
        )
    return mevcut


class SabitSaat:
    """local_now ve time.time için ilerletilebilir sabit saat."""

    def __init__(self) -> None:
        self.an = datetime(2026, 9, 1, 9, 0, 0)

    def git(self, yil, ay, gun, saat, dakika=0) -> None:
        self.an = datetime(yil, ay, gun, saat, dakika, 0)

    def ilerle(self, saniye: int = 37) -> None:
        from datetime import timedelta

        self.an = self.an + timedelta(seconds=saniye)

    def local_now(self) -> datetime:
        return self.an

    def time(self) -> float:
        return self.an.timestamp()


def uret(kok: Path, surum: str, cikti: Path) -> dict:
    sys.path.insert(0, str(kok))
    saat = SabitSaat()
    import app.core.clock as clock  # noqa: E402  (yalnızca --kok altındaki kod)

    clock.local_now = saat.local_now
    time.time = saat.time

    from app.core.db import open_database
    from app.core.models import PaymentMethod
    from app.services.cart_service import Cart
    from app.services.container import build_services

    if cikti.exists():
        cikti.unlink()
    db = open_database(cikti)
    s = build_services(db)

    # --- 1 Eylül: katalog, başlangıç stoku, alış ------------------------------
    saat.git(2026, 9, 1, 8, 30)
    bira = s.products.quick_create(
        name="Tuborg Gold 50 cl Kutu", sale_price=8000, barcode="8690504001492",
        initial_stock=24, purchase_cost=5000, brand_name="Tuborg", location_id=1,
    )
    s.barcodes.add_barcode(bira, "8690504001508", barcode_type="CASE", multiplier=24)
    saat.ilerle()
    efes = s.products.quick_create(
        name="Efes Malt 50 cl Kutu", sale_price=7500, barcode="8690504001515",
        initial_stock=None, brand_name="Efes", location_id=1,
    )
    saat.ilerle()
    sifirli = s.products.quick_create(
        name="Dökme Leblebi 250 g", sale_price=4500, barcode="00123", initial_stock=0,
    )
    saat.ilerle()
    cips = s.products.quick_create(
        name="Ruffles Original 105 g", sale_price=5000, barcode="8690504002004",
        initial_stock=20, purchase_cost=3000, location_id=6,
    )
    saat.ilerle()
    pasif = s.products.quick_create(
        name="Eski Ürün (pasif)", sale_price=1000, barcode="8690504009991",
        initial_stock=None,
    )
    s.products.set_active(pasif, False)

    # Maliyetli alış fişi + aynı fişte iki satır (farklı maliyet).
    saat.git(2026, 9, 1, 9, 15)
    fis1 = s.purchases.start_draft(invoice_no="IRS-0901")
    s.purchases.add_line(fis1, bira, 24, unit_cost=5200, barcode_used="8690504001508", multiplier=24)
    s.purchases.add_line(fis1, cips, 10, unit_cost=3000)
    s.purchases.commit(fis1)

    # V1.1 kalıntısı: maliyetsiz satır (add_line 'last_purchase_cost or 0').
    saat.ilerle(120)
    fis2 = s.purchases.start_draft()
    s.purchases.add_line(fis2, efes, 12)
    s.purchases.commit(fis2)

    # Geri alınan fiş (hemen ardından — kanıtlanabilir).
    saat.ilerle(120)
    fis3 = s.purchases.start_draft(invoice_no="IRS-YANLIS")
    s.purchases.add_line(fis3, cips, 5, unit_cost=3100)
    s.purchases.commit(fis3)
    s.purchases.reverse(fis3)

    # --- 1 Eylül: satışlar ------------------------------------------------------
    saat.git(2026, 9, 1, 14, 0)
    for _ in range(3):
        s.sales.quick_sale(bira)           # HIZLI, ödeme NULL
        saat.ilerle(40)

    def sepet(urunler, yontem):
        c = Cart()
        for pid, adet in urunler:
            s.cart.add_product(c, pid, quantity=adet)
        saat.ilerle(90)
        return s.cart.checkout(c, payment_method=yontem)

    sepet([(bira, 2), (cips, 1)], PaymentMethod.CASH)
    kart_satis = sepet([(bira, 4), (cips, 2)], PaymentMethod.CARD)
    ayni_gun = sepet([(efes, 1)], PaymentMethod.CASH)
    saat.ilerle(300)
    s.sales.reverse_sale(ayni_gun.sale_id)              # aynı gün geri alma
    sepet([(sifirli, 3)], PaymentMethod.CASH)

    # --- 2 Eylül: günler arası geri alma, fiyat değişikliği -------------------
    saat.git(2026, 9, 2, 10, 0)
    s.sales.reverse_sale(kart_satis.sale_id)            # GÜNLER ARASI geri alma
    saat.ilerle(600)
    s.products.set_price(bira, 8500, "Zam")
    sepet([(bira, 1), (efes, 2)], PaymentMethod.CARD)
    s.sales.quick_sale(cips)

    # Sayım (Bira Dolabı) — başlangıç sayımı dahil.
    saat.git(2026, 9, 2, 18, 0)
    oturum = s.counts.start(location_ids=[1])
    s.counts.set_counted(oturum, bira, 1, 40)
    s.counts.set_counted(oturum, efes, 1, 9)
    s.counts.commit(oturum)

    # --- 3 Eylül: açık sepet taslağı, ayarlar --------------------------------
    saat.git(2026, 9, 3, 11, 0)
    sepet([(bira, 6)], PaymentMethod.CASH)
    taslak = Cart()
    s.cart.add_product(taslak, cips, quantity=2)
    s.cart.add_product(taslak, bira, quantity=1)
    s.cart.save_draft(taslak)
    s.settings.set_many({"duplicate_scan_ms": "150", "auto_backup_retention": "7"})

    sayimlar = {
        tablo: db.scalar(f"SELECT COUNT(*) FROM {tablo}")
        for tablo in (
            "products", "product_barcodes", "sales", "sale_items", "stock_movements",
            "purchase_receipts", "purchase_receipt_lines", "count_sessions",
            "cart_drafts", "cart_draft_lines", "price_history", "settings",
        )
    }
    ozet = {
        "schema_version": db.schema_version(),
        "toplam_ciro": db.scalar("SELECT COALESCE(SUM(total_amount),0) FROM sales"),
        "toplam_stok_degeri": db.scalar("SELECT COALESCE(SUM(stock_value),0) FROM products"),
    }
    db.close()
    for son_ek in ("-wal", "-shm"):
        yan = Path(str(cikti) + son_ek)
        if yan.exists():
            raise SystemExit(f"Yan dosya kaldı: {yan}")
    return {"satir_sayilari": sayimlar, **ozet}


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--surum", choices=sorted(BEKLENEN_KAYNAK), required=True)
    p.add_argument("--kok", type=Path, required=True, help="sürümün çalışma ağacı")
    p.add_argument("--cikti", type=Path, required=True)
    a = p.parse_args()

    _guvenli_veri_klasoru()
    kok = a.kok.resolve()
    agac = _kaynak_dogrula(kok, a.surum)
    bilgi = uret(kok, a.surum, a.cikti.resolve())
    veri = a.cikti.read_bytes()
    meta = {
        "surum": a.surum,
        "kaynak": BEKLENEN_KAYNAK[a.surum],
        "app_agaci": agac,
        "sha256": hashlib.sha256(veri).hexdigest(),
        "boyut": len(veri),
        **bilgi,
    }
    a.cikti.with_suffix(".meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(meta, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
