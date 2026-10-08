"""Başarım ve uzun ömür (V1.2 M11, plan §9).

Varsayılan süit (belirlenimci):
  * maliyet katmanı sorgusu (şema v6 kısmi indeksleri) ilk sürümdeki pencere
    fonksiyonlu sorguyla — burada KÂHİN olarak duruyor — rastgele defterlerde
    BİREBİR aynı sonucu verir,
  * ölçüm aracı küçük veride uçtan uca çalışır ve gerçek veri klasörünü
    REDDEDER.

``-m perf``: 10k ve 100k satışlık şablonlarda plan §9 hedefleri (p50). Bir
hedef kaçarsa ölçüm BİR KEZ yinelenir (dizüstü bilgisayarda arka plan yükü);
ikinci kez de kaçarsa test düşer — hedef sessizce gevşetilmez.
"""
from __future__ import annotations

import random
from dataclasses import replace

import pytest

from app.analytics import donemler as dn
from app.analytics import kar
from app.core.db import open_database
from app.core.errors import DomainError
from app.services.cart_service import Cart
from app.services.container import build_services
from app.tools import benchmark, perf_dataset, veri_guvenligi

#: V1.2 M8a'daki ilk sorgu: satılan ürünlerin TÜM hareket geçmişini pencere
#: fonksiyonlarıyla tarar (doğru ama 100k veride 30 gün 2,2 s). Kâhin.
PENCERE_KAHINI = """
WITH urunler AS (
    SELECT DISTINCT i.product_id FROM sale_items i JOIN sales s ON s.id = i.sale_id
     WHERE s.entry_type = 'SALE' AND s.is_reversed = 0 AND s.business_date BETWEEN ? AND ?
), mv AS (
    SELECT m.id, m.product_id, m.ref_type, m.ref_id, m.ref_line_id,
           COALESCE(SUM(CASE WHEN m.balance_after <= 0 THEN 1 ELSE 0 END) OVER (
               PARTITION BY m.product_id ORDER BY m.id
               ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING), 0) AS grup,
           CASE WHEN m.quantity_delta > m.fill_quantity
                 AND (m.is_estimated_cost = 1 OR COALESCE(m.unit_cost, 0) = 0)
                THEN 1 ELSE 0 END AS kirli
      FROM stock_movements m JOIN urunler u ON u.product_id = m.product_id
), gk AS (
    SELECT id, ref_type, ref_id, ref_line_id,
           COALESCE(MAX(kirli) OVER (
               PARTITION BY product_id, grup ORDER BY id
               ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING), 0) AS once_kirli
      FROM mv
)
SELECT CASE
         WHEN i.is_estimated_cost = 0 AND i.cost_total > 0
              AND COALESCE(gk.once_kirli, 0) = 0 THEN 'GUVENILIR'
         WHEN i.cost_total > 0 THEN 'TAHMINI'
         ELSE 'BILINMIYOR' END AS katman,
       SUM(i.line_total) AS ciro, SUM(i.cost_total) AS maliyet, COUNT(*) AS satir
  FROM sale_items i JOIN sales s ON s.id = i.sale_id
  LEFT JOIN gk ON gk.ref_type = 'SALE' AND gk.ref_id = s.id AND gk.ref_line_id = i.id
 WHERE s.entry_type = 'SALE' AND s.is_reversed = 0 AND s.business_date BETWEEN ? AND ?
 GROUP BY katman
"""


def _kahin(db, donem) -> dict[str, kar.Katman]:
    p = (donem.baslangic, donem.bitis)
    return {r["katman"]: kar.Katman(r["ciro"], r["maliyet"], r["satir"])
            for r in db.query(PENCERE_KAHINI, (*p, *p))}


def _hizli(db, donem) -> dict[str, kar.Katman]:
    k = kar.maliyet_kapsami(db, donem)
    return {ad: katman for ad, katman in ((kar.GUVENILIR, k.guvenilir),
                                          (kar.TAHMINI, k.tahmini),
                                          (kar.BILINMIYOR, k.bilinmiyor)) if katman.satir}


def _karsilastir(db, gunler: list[str], rng: random.Random) -> set[str]:
    """Her gün, tüm aralık ve rastgele alt aralıklarda iki sorgu aynı mı."""
    donemler = [dn.ozel(g, g) for g in gunler] + [dn.ozel(gunler[0], gunler[-1])]
    for _ in range(6):
        a, b = sorted(rng.sample(range(len(gunler)), 2))
        donemler.append(dn.ozel(gunler[a], gunler[b]))
    gorulen: set[str] = set()
    for donem in donemler:
        beklenen = _kahin(db, donem)
        assert _hizli(db, donem) == beklenen, donem
        gorulen |= set(beklenen)
    return gorulen


# ===================== Kâhin eşdeğerliği ===================================
@pytest.mark.parametrize("tohum", [3, 11, 29])
def test_maliyet_katmani_rastgele_defterde_kahinle_ayni(duvar_saati, services, tohum):
    """Tahmini maliyetli / bedelsiz / maliyetli alış, sayım (sıfırlama ve
    maliyetsiz giriş), sepet ve hızlı satış, aynı ve farklı gün geri almalar."""
    rng = random.Random(tohum)
    urunler = [services.products.quick_create(f"Ürün {i}", 1000 + 250 * i, location_id=1)
               for i in range(4)]
    satislar: list[int] = []
    fisler: list[int] = []
    gunler = []
    for gun in range(1, 7):
        duvar_saati.git(2026, 9, gun, 9)
        gunler.append(f"2026-09-{gun:02d}")
        for _ in range(14):
            duvar_saati.ilerle(600)
            pid = rng.choice(urunler)
            islem = rng.random()
            try:
                if islem < 0.25:
                    fis = services.purchases.start_draft()
                    # Çoğu alışın maliyeti bilinir; arada tahmini ve bedelsiz.
                    services.purchases.add_line(fis, pid, rng.randint(1, 8), rng.choice(
                        [None, 0, 300, 450, 600, 380, 520, 410, 330]))
                    services.purchases.commit(fis)
                    fisler.append(fis)
                elif islem < 0.35:
                    oturum = services.counts.start([1])
                    services.counts.set_counted(oturum, pid, 1, rng.choice([0, 0, 0, 4]))
                    services.counts.commit(oturum)
                elif islem < 0.75:
                    sepet = Cart()
                    for urun in rng.sample(urunler, rng.randint(1, 3)):
                        services.cart.add_product(sepet, urun, quantity=rng.randint(1, 3))
                    satislar.append(services.cart.checkout(sepet, payment_method="NAKIT").sale_id)
                elif islem < 0.9:
                    satislar.append(services.sales.quick_sale(pid, rng.randint(1, 2)).sale_id)
                elif islem < 0.96 and satislar:
                    services.sales.reverse_sale(satislar.pop(rng.randrange(len(satislar))))
                elif fisler:
                    services.purchases.reverse(fisler.pop(rng.randrange(len(fisler))))
            except DomainError:
                pass                       # ör. kanıtlanamayan fiş geri alması: atlanır
    assert services.db.check_invariants(deep=True) == []
    gorulen = _karsilastir(services.db, gunler, rng)
    assert {kar.GUVENILIR, kar.TAHMINI} <= gorulen, gorulen


@pytest.mark.parametrize("tohum", [5, 17])
def test_maliyet_katmani_uretilmis_veride_kahinle_ayni(tmp_path, monkeypatch, tohum):
    monkeypatch.setenv("TEKEL_DATA_DIR", str(tmp_path / "karalama"))
    parametreler = perf_dataset.VeriParametreleri(urun=25, gun=8, satis=240, tohum=tohum,
                                                  geri_alma_orani=0.05)
    sonuc = perf_dataset.uret(parametreler, tmp_path / "karalama" / "veri.db")
    db = open_database(sonuc.yol)
    try:
        gunler = [r[0] for r in db.query(
            "SELECT DISTINCT business_date FROM sales ORDER BY 1")]
        assert len(gunler) == parametreler.gun
        _karsilastir(db, gunler, random.Random(tohum))
    finally:
        db.close()


# ===================== Ölçüm aracı ==========================================
@pytest.fixture
def kucuk_veri(tmp_path, monkeypatch):
    monkeypatch.setenv("TEKEL_DATA_DIR", str(tmp_path / "karalama"))
    sonuc = perf_dataset.uret(replace(perf_dataset.HAZIR["kucuk"], bekletme_orani=0.1),
                              tmp_path / "karalama" / "kucuk.db")
    return sonuc.yol


def test_olcum_araci_kucuk_veride_uctan_uca(kucuk_veri, tmp_path):
    once = kucuk_veri.read_bytes()
    sonuc = benchmark.olc(kucuk_veri, tmp_path / "karalama" / "olcum", tekrar=1)
    assert kucuk_veri.read_bytes() == once, "verilen veritabanı DEĞİŞMEZ (kopyada ölçülür)"
    olcumler = sonuc["olcumler"]
    for ad in (*benchmark.HEDEFLER_MS, "acilis_ilk", "derin_denetim", "maliyet_kapsami_1_yil",
               "bekleyen_sepet_ac", "gunluk_yedek", "destek_paketi"):
        assert ad in olcumler, ad
        assert olcumler[ad]["p50_ms"] >= 0 and "_sonuc" not in olcumler[ad]
    assert sonuc["sema_once"] == sonuc["sema_sonra"]
    assert sonuc["sig_denetim_sorun"] == 0 and sonuc["derin_denetim_sorun"] == 0
    assert isinstance(benchmark.hedef_disi(sonuc), dict)
    tablo = benchmark.markdown(sonuc)
    assert "| barkod_cozumle |" in tablo and "kucuk.db" in tablo


def test_v1_bicimine_indirilen_veri_yukseltilir_ve_tutarlidir(kucuk_veri, tmp_path):
    """Ölçüm aracının "V1.1 şeklindeki veri" kopyası gerçekten v1'dir ve güncel
    sürüme göç öncesi yedekle, değişmezleri bozmadan yükseltilir."""
    import sqlite3

    from app.core.schema import SCHEMA_VERSION

    hedef = tmp_path / "karalama" / "v1" / "eski.db"
    hedef.parent.mkdir(parents=True)
    benchmark.v1_bicimine_indir(kucuk_veri, hedef)
    ham = sqlite3.connect(hedef)
    try:
        assert ham.execute("SELECT value FROM schema_meta WHERE key = 'schema_version'"
                           ).fetchone()[0] == "1"
        sutunlar = {r[1] for r in ham.execute("PRAGMA table_info(products)")}
        assert "reference_cost" not in sutunlar, "v3 sütunu yok"
        assert ham.execute("SELECT COUNT(*) FROM sqlite_master WHERE name = "
                           "'price_change_batches'").fetchone()[0] == 0, "v4 tablosu yok"
        sayilar = {t: ham.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                   for t in ("sales", "sale_items", "stock_movements", "products")}
    finally:
        ham.close()

    db = open_database(hedef)
    try:
        assert db.schema_version() == SCHEMA_VERSION
        for tablo, sayi in sayilar.items():
            assert db.scalar(f"SELECT COUNT(*) FROM {tablo}") == sayi, tablo
        assert db.check_invariants(deep=True) == []
    finally:
        db.close()
    yedekler = hedef.parent / "backups"
    assert list(yedekler.glob(f"guncelleme_oncesi_v1_v{SCHEMA_VERSION}_*.db"))
    assert not [p for p in yedekler.iterdir() if p.name.endswith(("-wal", "-shm"))],         "doğrulanan göç öncesi yedek yan dosya bırakmaz (D-25)"


def test_olcum_araci_karalama_klasoru_olmadan_calismaz(monkeypatch, tmp_path, capsys):
    monkeypatch.delenv("TEKEL_DATA_DIR", raising=False)
    assert benchmark.main(["--veri", str(tmp_path / "x.db")]) == 2
    assert "REDDEDİLDİ" in capsys.readouterr().err


def test_olcum_araci_gercek_veriyi_olcmez(monkeypatch, tmp_path, capsys):
    sahte_yerel = tmp_path / "LocalAppData"
    gercek = sahte_yerel / "TekelStok" / "tekelstok.db"
    gercek.parent.mkdir(parents=True)
    gercek.write_bytes(b"dokunma")
    monkeypatch.setenv("LOCALAPPDATA", str(sahte_yerel))
    monkeypatch.setenv("TEKEL_DATA_DIR", str(tmp_path / "karalama"))
    assert benchmark.main(["--veri", str(gercek)]) == 2
    assert "REDDEDİLDİ" in capsys.readouterr().err
    assert gercek.read_bytes() == b"dokunma"
    assert not (tmp_path / "karalama").exists(), "hiçbir şey kopyalanmadı"
    assert veri_guvenligi.gercek_veri_klasoru() == gercek.parent.resolve()


# ===================== Duvar saati hedefleri (yalnızca -m perf) ============
@pytest.mark.perf
@pytest.mark.parametrize("ad", ["10k", "100k"])
def test_plan_hedefleri(perf_sablonu, tmp_path, ad):
    sablon = perf_sablonu(ad)
    sonuc = benchmark.olc(sablon, tmp_path / "olcum", tekrar=30)
    kacan = benchmark.hedef_disi(sonuc)
    if kacan:                                   # belgelenmiş TEK yineleme
        sonuc = benchmark.olc(sablon, tmp_path / "olcum2", tekrar=30)
        kacan = benchmark.hedef_disi(sonuc)
    assert kacan == {}, benchmark.markdown(sonuc)


@pytest.mark.perf
def test_sablon_servislerle_acilir_ve_sig_denetim_temiz(perf_kopya):
    db = open_database(perf_kopya("100k"))
    try:
        svc = build_services(db)
        assert db.check_invariants() == []
        assert svc.cart.parked_count() == 0
    finally:
        db.close()
