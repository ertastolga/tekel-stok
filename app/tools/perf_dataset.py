"""Başarım ölçümü için tohumlu, gerçekçi SENTETİK veri üretici.

Yalnızca geliştirme aracıdır; ürün davranışını değiştirmez ve gerçek dükkân
verisine ASLA dokunmaz:

* ``TEKEL_DATA_DIR`` doğrulanmış bir karalama klasörü olmalıdır
  (``veri_guvenligi.karalama_klasoru``); çıktı dosyası da sahibin gerçek veri
  klasörünün içinde olamaz.
* Veri GERÇEK servislerle yazılır (satış, sepet, geri alma, mal kabul, sayım,
  fiyat değişikliği): şema ve değişmezler üretim koduyla aynı yoldan geçer.
* Zaman, saat dikişiyle (``app.core.clock.use_clock``) simüle edilir; her gün
  TEK bir dış işlemde yazılır (fsync gün başına bir kez) — 100 bin satış
  dakikalar içinde üretilir.
* Aynı tohum + aynı parametreler = aynı veri (``parmak_izi`` ile doğrulanır).

Kullanım::

    set TEKEL_DATA_DIR=C:\\karalama
    python -m app.tools.perf_dataset --hazir 10k
    python -m app.tools.perf_dataset --urun 2000 --gun 90 --satis 5000 --cikti C:\\karalama\\x.db
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path

#: Üretim kuralları değiştiğinde artırılır (önbelleklenmiş şablonları geçersiz kılar).
URETICI_SURUMU = 1

#: Sabit bitiş günü: "bugün"e bağlı olsaydı aynı tohum farklı veri üretirdi.
BITIS_GUNU = datetime(2026, 9, 30)


@dataclass(frozen=True)
class VeriParametreleri:
    urun: int
    gun: int
    satis: int
    tohum: int = 20261007
    geri_alma_orani: float = 0.01
    gunler_arasi_geri_alma_payi: float = 0.3
    sepet_orani: float = 0.6

    def anahtar(self) -> str:
        """Önbellek anahtarı: parametreler + üretici sürümü + şema sürümü."""
        from app.core.db import hedef_sema_surumu

        kaynak = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()[:12]
        metin = json.dumps(
            {
                **asdict(self), "uretici": URETICI_SURUMU, "kaynak": kaynak,
                "sema": hedef_sema_surumu(),
            },
            sort_keys=True,
        )
        return hashlib.sha256(metin.encode("utf-8")).hexdigest()[:16]


#: Hazır boyutlar (plan §9): ``10k`` ve ``100k`` satış.
HAZIR = {
    "kucuk": VeriParametreleri(urun=40, gun=12, satis=240),
    "10k": VeriParametreleri(urun=10_000, gun=365, satis=10_000),
    "100k": VeriParametreleri(urun=10_000, gun=1095, satis=100_000),
}


class _SimuleSaat:
    """``use_clock`` sağlayıcısı: üretici zamanı kendisi ilerletir."""

    def __init__(self, an: datetime) -> None:
        self.an = an

    def __call__(self) -> datetime:
        return self.an

    def tekduze(self) -> float:
        return self.an.timestamp()


def _ean13(govde12: str) -> str:
    toplam = sum(int(c) * (3 if i % 2 else 1) for i, c in enumerate(govde12))
    return govde12 + str((10 - toplam % 10) % 10)


@dataclass
class UretimSonucu:
    yol: Path
    parametreler: VeriParametreleri
    sure_sn: float
    sayimlar: dict

    def meta(self) -> dict:
        return {
            "parametreler": asdict(self.parametreler),
            "uretici_surumu": URETICI_SURUMU,
            "sure_sn": round(self.sure_sn, 1),
            "sayimlar": self.sayimlar,
        }


def _guvenli_cikti(cikti: Path) -> Path:
    """Çıktı yolu sahibin gerçek veri klasöründe OLAMAZ."""
    from app.tools import veri_guvenligi

    veri_guvenligi.karalama_klasoru()          # TEKEL_DATA_DIR denetimi
    yol = Path(cikti).expanduser().resolve()
    gercek = veri_guvenligi.gercek_veri_klasoru()
    if gercek is not None and (yol == gercek or gercek in yol.parents):
        raise veri_guvenligi.GercekVeriKlasoruHatasi(
            "Çıktı sahibin gerçek veri klasörüne yazılamaz."
        )
    return yol


def uret(parametreler: VeriParametreleri, cikti: Path) -> UretimSonucu:
    """Veritabanını üretir ve kapatır (yan dosya bırakmaz)."""
    yol = _guvenli_cikti(cikti)
    if yol.exists():
        raise FileExistsError(f"Çıktı zaten var: {yol}")
    yol.parent.mkdir(parents=True, exist_ok=True)

    from app.core import clock
    from app.core.db import open_database
    from app.services.container import build_services

    rng = random.Random(parametreler.tohum)
    baslangic = BITIS_GUNU - timedelta(days=parametreler.gun - 1)
    saat = _SimuleSaat(baslangic.replace(hour=8))
    t0 = time.perf_counter()
    with clock.use_clock(yerel=saat, tekduze=saat.tekduze):
        svc = build_services(open_database(yol))
        try:
            _doldur(svc, parametreler, rng, saat, baslangic)
            sayimlar = _sayimlar(svc)
        finally:
            svc.close()
    for ek in ("-wal", "-shm"):
        Path(str(yol) + ek).unlink(missing_ok=True)
    sonuc = UretimSonucu(yol, parametreler, time.perf_counter() - t0, sayimlar)
    Path(str(yol) + ".meta.json").write_text(
        json.dumps(sonuc.meta(), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return sonuc


def _doldur(svc, p: VeriParametreleri, rng: random.Random, saat, baslangic) -> None:
    from app.core.models import BarcodeType, PaymentMethod
    from app.services.cart_service import Cart

    kategoriler = [r["id"] for r in svc.catalog.categories()]
    markalar = [f"Marka {i:02d}" for i in range(1, 41)]
    tedarikciler = [svc.suppliers.create(f"Tedarikçi {i}") for i in range(1, 6)]

    # --- Katalog (ilk gün, tek işlem) -----------------------------------
    urunler: list[int] = []
    fiyat: dict[int, int] = {}
    with svc.db.transaction():
        for i in range(1, p.urun + 1):
            maliyet = rng.randint(5, 400) * 100
            satis_fiyati = int(maliyet * rng.uniform(1.15, 1.6)) // 50 * 50 or 50
            pid = svc.products.quick_create(
                f"Ürün {i:05d} {rng.choice(['Kutu', 'Şişe', 'Paket', 'Adet'])}",
                sale_price=satis_fiyati,
                barcode=_ean13(f"869{i:09d}"),
                initial_stock=rng.randint(0, 60),
                purchase_cost=maliyet,
                category_id=rng.choice(kategoriler),
                brand_name=rng.choice(markalar),
                location_id=rng.randint(1, 8),
            )
            if rng.random() < 0.05:
                svc.barcodes.add_barcode(
                    pid, _ean13(f"868{i:09d}"), BarcodeType.CASE, 24
                )
            urunler.append(pid)
            fiyat[pid] = satis_fiyati

    # Popülerlik: az sayıda ürün satışların çoğunu alır (gerçekçi dağılım).
    agirlik = [1.0 / (sira + 1) ** 0.8 for sira in range(len(urunler))]
    rng.shuffle(agirlik)

    gunluk = [p.satis // p.gun] * p.gun
    for i in range(p.satis - sum(gunluk)):
        gunluk[i % p.gun] += 1

    # Geri alınabilir satışlar İKİ ayrı havuzda: bugünkü ve önceki günler.
    # Bir satış yalnızca birinde bulunur; böylece iki kez geri alınmaz.
    eski: list[int] = []
    # Küçük veri setlerinde de her tür kayıt oluşsun diye takvim boyuta göre kayar.
    fiyat_gunleri = set(range(min(15, p.gun // 2), p.gun, 30))
    sayim_gunleri = set(range(min(45, max(0, p.gun - 2)), p.gun, 90))
    for g in range(p.gun):
        gun = baslangic + timedelta(days=g)
        anlar = sorted(
            gun.replace(hour=9) + timedelta(seconds=rng.randint(0, 14 * 3600 - 1))
            for _ in range(gunluk[g])
        )
        with svc.db.transaction():
            saat.an = gun.replace(hour=8, minute=30)
            if g % 7 == 0:
                _mal_kabul(svc, rng, urunler, tedarikciler, p)
            if g in fiyat_gunleri:
                for pid in rng.sample(urunler, min(5, len(urunler))):
                    yeni = max(50, fiyat[pid] + rng.choice([-1, 1, 2]) * 250)
                    svc.products.set_price(pid, yeni)
                    fiyat[pid] = yeni
            if g in sayim_gunleri:
                _sayim(svc, rng)

            bugunku: list[int] = []
            for an in anlar:
                saat.an = an
                if (bugunku or eski) and rng.random() < p.geri_alma_orani:
                    gunler_arasi = rng.random() < p.gunler_arasi_geri_alma_payi
                    havuz = eski if (gunler_arasi and eski) or not bugunku else bugunku
                    svc.sales.reverse_sale(havuz.pop(rng.randrange(len(havuz))))
                    continue
                # Sepet büyüklüğü: çoğu küçük, bazıları büyük (ortalama ~4 kalem);
                # Hızlı Satış tek kalemdir — genel ortalama ~3 kalem/satış.
                kalem = min(len(urunler), max(1, int(rng.expovariate(1 / 3.8)) + 1))
                secilen = list(dict.fromkeys(rng.choices(urunler, agirlik, k=kalem)))
                if rng.random() < p.sepet_orani:
                    sepet = Cart()
                    for pid in secilen:
                        svc.cart.add_product(sepet, pid, quantity=rng.choice([1, 1, 1, 2, 3]))
                    yontem = PaymentMethod.CASH if rng.random() < 0.58 else PaymentMethod.CARD
                    satis = svc.cart.checkout(sepet, payment_method=yontem)
                else:
                    satis = svc.sales.quick_sale(secilen[0], rng.choice([1, 1, 2]))
                bugunku.append(satis.sale_id)
        eski.extend(bugunku)
        # Eski satış havuzu sınırlı tutulur (bellek); son ~5000 satış yeter.
        if len(eski) > 5000:
            del eski[: len(eski) - 5000]


def _mal_kabul(svc, rng, urunler, tedarikciler, p) -> None:
    fis = svc.purchases.start_draft(
        supplier_id=rng.choice(tedarikciler), invoice_no=f"F{rng.randint(1, 999999):06d}"
    )
    for pid in rng.sample(urunler, min(len(urunler), rng.randint(5, 25))):
        maliyet = rng.randint(5, 400) * 100
        svc.purchases.add_line(fis, pid, rng.choice([6, 12, 24, 48]), unit_cost=maliyet)
    svc.purchases.commit(fis)
    # Arada başka hareket yoksa (kanıtlanabilir) ara sıra hemen geri alınır.
    if rng.random() < 0.05 and svc.purchases.reversal_preview(fis).allowed:
        svc.purchases.reverse(fis)


def _sayim(svc, rng) -> None:
    konum = rng.randint(1, 8)
    oturum = svc.counts.start([konum])
    satirlar = svc.counts.lines(oturum)
    for satir in rng.sample(list(satirlar), min(20, len(satirlar))):
        svc.counts.set_counted(oturum, satir["product_id"], konum, rng.randint(0, 40))
    svc.counts.commit(oturum)


def _sayimlar(svc) -> dict:
    tablolar = (
        "products", "product_barcodes", "sales", "sale_items", "stock_movements",
        "purchase_receipts", "purchase_receipt_lines", "count_sessions",
        "price_history", "daily_sales_rollup",
    )
    sayim = {t: svc.db.scalar(f"SELECT COUNT(*) FROM {t}") for t in tablolar}
    sayim["geri_alma"] = svc.db.scalar(
        "SELECT COUNT(*) FROM sales WHERE entry_type='SALE_REVERSAL'"
    )
    sayim["gunler_arasi_geri_alma"] = svc.db.scalar(
        "SELECT COUNT(*) FROM sales r JOIN sales o ON o.id = r.reverses_sale_id "
        " WHERE r.business_date <> o.business_date"
    )
    return sayim


def parmak_izi(yol: Path) -> str:
    """Verinin özeti: aynı tohum aynı izi vermelidir (zaman damgaları dahil)."""
    import sqlite3

    conn = sqlite3.connect(f"{Path(yol).resolve().as_uri()}?mode=ro", uri=True)
    try:
        ozet = hashlib.sha256()
        for sql in (
            "SELECT id, entry_type, sale_mode, payment_method, business_date, "
            "       total_amount, total_cost, item_count, created_at_utc FROM sales ORDER BY id",
            "SELECT product_id, quantity_delta, value_delta, balance_after "
            "  FROM stock_movements ORDER BY id",
            "SELECT id, sale_price, current_stock, stock_value FROM products ORDER BY id",
        ):
            for satir in conn.execute(sql):
                ozet.update(repr(tuple(satir)).encode("utf-8"))
        return ozet.hexdigest()
    finally:
        conn.close()


def main(argv: list[str] | None = None) -> int:
    ayristirici = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ayristirici.add_argument("--hazir", choices=sorted(HAZIR))
    ayristirici.add_argument("--urun", type=int)
    ayristirici.add_argument("--gun", type=int)
    ayristirici.add_argument("--satis", type=int)
    ayristirici.add_argument("--tohum", type=int, default=20261007)
    ayristirici.add_argument("--cikti")
    args = ayristirici.parse_args(argv)

    from app.tools import veri_guvenligi

    try:
        karalama = veri_guvenligi.karalama_klasoru()
    except veri_guvenligi.GercekVeriKlasoruHatasi as hata:
        print(f"REDDEDİLDİ: {hata}", file=sys.stderr)
        return 2

    if args.hazir:
        parametreler = HAZIR[args.hazir]
    elif args.urun and args.gun and args.satis:
        parametreler = VeriParametreleri(args.urun, args.gun, args.satis, args.tohum)
    else:
        ayristirici.error("--hazir ya da --urun/--gun/--satis gerekli")
    cikti = Path(args.cikti) if args.cikti else karalama / f"perf_{parametreler.anahtar()}.db"
    try:
        sonuc = uret(parametreler, cikti)
    except veri_guvenligi.GercekVeriKlasoruHatasi as hata:
        print(f"REDDEDİLDİ: {hata}", file=sys.stderr)
        return 2
    print(json.dumps({"yol": str(sonuc.yol), **sonuc.meta()}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
