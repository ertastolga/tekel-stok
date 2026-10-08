"""Alış maliyeti anlamı (V1.2 M6a — D-06, D-20, plan §5.8).

Korunan sözler:
  * ``last_purchase_cost`` / ``last_purchase_at_utc`` yalnızca GERÇEK, bilinen
    bir alışla değişir; maliyeti bilinmeyen (tahmini) ve bedelsiz (0) giriş
    bunları DAMGALAMAZ,
  * maliyeti bilinmeyen giriş tahmini kuralla değerlenir (havuz ortalaması →
    son ortalama → bilinen son alış → 0), "tahmini" diye işaretlenir ve havuz
    ortalamasını 1 kuruştan fazla kaydırmaz,
  * fiş satırı birleştirme anahtarı (ürün, tahmini mi, maliyet),
  * fiş geri alması son alış fiyatını, son ortalamayı VE son alış zamanını
    fiş öncesine döndürür (D-20),
  * başlangıç stoğu maliyetsizse tahmini kural; açık maliyet V1.1 gibi damgalar,
  * "alış fiyatı hiç girilmemiş" uyarısı eski 0 damgalarını da yakalar.
"""
from __future__ import annotations

import pytest

from app.core.db import open_database
from app.core.errors import FisZatenTamamlanmis


def _fis(services, *satirlar, tamamla=True):
    fis = services.purchases.start_draft()
    for urun, adet, maliyet in satirlar:
        services.purchases.add_line(fis, urun, adet, maliyet)
    if tamamla:
        services.purchases.commit(fis)
    return fis


def _urun(services, pid):
    return services.products.get(pid)


def _son_hareket(services, pid):
    return services.db.query_one(
        "SELECT * FROM stock_movements WHERE product_id = ? ORDER BY id DESC LIMIT 1", (pid,)
    )


# ===================== D-06 ================================================
def test_ayni_fiste_maliyetsiz_satir_ortalamayi_yariya_indirmez(services, bira):
    """V1.1 kanıtı (D-06): aynı fişte 10@50 + 10 maliyetsiz ⇒ maliyetsiz satır 0
    kaydediliyor, ortalama 50 → 25 TL, son alış 0, sonraki satış 25 TL'den
    KESİN diye maliyetleniyordu."""
    _fis(services, (bira, 10, 5000), (bira, 10, None))
    urun = _urun(services, bira)
    assert services.inventory.average_cost(bira) == 5000
    assert urun["last_purchase_cost"] == 5000
    hareket = _son_hareket(services, bira)
    assert (hareket["unit_cost"], hareket["is_estimated_cost"]) == (5000, 1)
    assert services.db.check_invariants(deep=True) == []


def test_maliyetsiz_giris_ortalamayi_bozmaz_ve_damgalamaz(services, bira):
    """Ayrı fişlerde de: maliyetsiz giriş tahminidir ve son alışı damgalamaz."""
    _fis(services, (bira, 10, 5000))
    fis = _fis(services, (bira, 10, None))
    urun = _urun(services, bira)
    assert services.inventory.average_cost(bira) == 5000, "ortalama korunur"
    assert urun["last_purchase_cost"] == 5000, "tahmini giriş son alışı damgalamaz"
    satir = services.purchases.lines(fis)[0]
    assert (satir["cost_is_estimated"], satir["unit_cost"]) == (1, 5000)
    assert _son_hareket(services, bira)["is_estimated_cost"] == 1
    assert services.db.check_invariants(deep=True) == []


def test_tahmini_maliyet_sirasi(services, bira, cips_urunu):
    # Hiç bilgi yok → 0, tahmini.
    _fis(services, (cips_urunu, 5, None))
    assert _son_hareket(services, cips_urunu)["unit_cost"] == 0
    assert _urun(services, cips_urunu)["last_purchase_cost"] is None
    # Stok yok, son ortalama var → son ortalama.
    _fis(services, (bira, 4, 6000))
    services.inventory.manual_adjustment(bira, -4, 6000, "fire")
    _fis(services, (bira, 2, None))
    hareket = _son_hareket(services, bira)
    assert (hareket["unit_cost"], hareket["is_estimated_cost"]) == (6000, 1)


@pytest.mark.parametrize("onceki", [(7, 4999), (3, 5001), (13, 7777), (1, 1)])
def test_tahmini_giris_havuz_ortalamasini_bir_kurustan_fazla_kaydirmaz(
    services, bira, onceki
):
    adet, maliyet = onceki
    _fis(services, (bira, adet, maliyet))
    once = services.inventory.average_cost(bira)
    for eklenen in (1, 2, 5, 11, 24):
        _fis(services, (bira, eklenen, None))
        assert abs(services.inventory.average_cost(bira) - once) <= 1


def test_bedelsiz_giris_damgalamaz(services, bira):
    _fis(services, (bira, 10, 5000))
    _fis(services, (bira, 10, 0))                      # açıkça 0: bedelsiz mal
    urun = _urun(services, bira)
    assert urun["last_purchase_cost"] == 5000
    assert services.inventory.average_cost(bira) == 2500, "bedelsiz mal ortalamayı düşürür"
    assert _son_hareket(services, bira)["is_estimated_cost"] == 0


def test_birlestirme_anahtari(services, bira):
    fis = _fis(services, (bira, 2, None), (bira, 3, None), (bira, 4, 5000),
               (bira, 1, 5000), (bira, 6, 0), tamamla=False)
    satirlar = [(s["quantity"], s["unit_cost"], s["cost_is_estimated"])
                for s in services.purchases.lines(fis)]
    assert satirlar == [(5, 0, 1), (5, 5000, 0), (6, 0, 0)]


def test_maliyet_girilince_tahmin_isareti_kalkar(services, bira):
    fis = _fis(services, (bira, 2, None), tamamla=False)
    satir = services.purchases.lines(fis)[0]
    services.purchases.set_line_cost(satir["id"], 5500)
    satir = services.purchases.lines(fis)[0]
    assert (satir["unit_cost"], satir["cost_is_estimated"]) == (5500, 0)
    services.purchases.commit(fis)
    assert _urun(services, bira)["last_purchase_cost"] == 5500
    with pytest.raises(FisZatenTamamlanmis):
        services.purchases.set_line_cost(satir["id"], 1)


def test_tahmini_satir_maliyet_degisimi_sayilmaz(services, bira):
    _fis(services, (bira, 10, 5000))
    fis = _fis(services, (bira, 10, None), tamamla=False)
    assert services.purchases.changed_cost_lines(fis) == []


def test_on_doldurma_bilinen_son_alistir(services, bira):
    """Arayüz son BİLİNEN alışı açıkça geçirir; ``None`` = maliyet bilinmiyor."""
    _fis(services, (bira, 24, 5000))
    _fis(services, (bira, 24, 5400))
    _fis(services, (bira, 24, None))
    _fis(services, (bira, 24, 0))
    assert services.products.known_cost(bira) == 5400
    assert services.purchases.last_purchase_cost(bira) == 5400
    fis = _fis(services, (bira, 24, services.products.known_cost(bira)), tamamla=False)
    satir = services.purchases.lines(fis)[0]
    assert (satir["unit_cost"], satir["cost_is_estimated"]) == (5400, 0)


# ===================== D-20 ================================================
def test_fis_geri_almasi_damgalarin_hepsini_dondurur(duvar_saati, services, bira):
    _fis(services, (bira, 10, 5000))
    once = _urun(services, bira)
    duvar_saati.ilerle(1800)
    fis = _fis(services, (bira, 10, 7000))
    sonra = _urun(services, bira)
    assert sonra["last_avg_cost"] == 6000
    assert sonra["last_purchase_at_utc"] > once["last_purchase_at_utc"]

    services.purchases.reverse(fis)
    urun = _urun(services, bira)
    assert urun["last_purchase_cost"] == once["last_purchase_cost"] == 5000
    assert urun["last_avg_cost"] == once["last_avg_cost"] == 5000, "V1.1: 6000 kalıyordu"
    assert urun["last_purchase_at_utc"] == once["last_purchase_at_utc"], \
        "V1.1: geri alınan fişin zamanı kalıyordu"
    assert services.db.check_invariants(deep=True) == []


def test_ayni_fiste_iki_satir_lifo_geri_alinir(services, bira):
    _fis(services, (bira, 10, 5000))
    once = _urun(services, bira)
    fis = services.purchases.start_draft()
    services.purchases.add_line(fis, bira, 5, 6000)
    services.purchases.add_line(fis, bira, 5, 6400)
    services.purchases.commit(fis)
    services.purchases.reverse(fis)
    urun = _urun(services, bira)
    for alan in ("last_purchase_cost", "last_avg_cost", "last_purchase_at_utc"):
        assert urun[alan] == once[alan], alan


def test_tahmini_satirli_fis_geri_alinir(services, bira):
    _fis(services, (bira, 10, 5000))
    once = _urun(services, bira)
    fis = _fis(services, (bira, 6, None), (bira, 2, 0))
    services.purchases.reverse(fis)
    urun = _urun(services, bira)
    for alan in ("last_purchase_cost", "last_avg_cost", "last_purchase_at_utc",
                 "current_stock", "stock_value"):
        assert urun[alan] == once[alan], alan
    ters = services.db.query(
        "SELECT cost_is_estimated FROM purchase_receipt_lines l JOIN purchase_receipts r "
        "  ON r.id = l.receipt_id WHERE r.reverses_receipt_id = ? ORDER BY l.line_no", (fis,))
    assert [t["cost_is_estimated"] for t in ters] == [1, 0], "ters satır işareti kopyalar"


def test_eski_fis_satiri_v11_gibi_geri_alinir(services, bira):
    """Göçten önce tamamlanmış satırın önceki damgaları yoktur: V1.1 davranışı."""
    _fis(services, (bira, 10, 5000))
    fis = _fis(services, (bira, 10, 7000))
    with services.db.transaction() as conn:            # V1.1'de tamamlanmış gibi
        conn.execute("UPDATE purchase_receipt_lines SET previous_stamps_captured = 0, "
                     "previous_avg_cost = NULL, previous_purchase_at_utc = NULL "
                     "WHERE receipt_id = ?", (fis,))
    sonra = _urun(services, bira)
    services.purchases.reverse(fis)
    urun = _urun(services, bira)
    assert urun["last_purchase_cost"] == 5000
    assert urun["last_avg_cost"] == sonra["last_avg_cost"], "bilinmeyen geçmiş uydurulmaz"


# ===================== Başlangıç stoğu =====================================
def test_maliyetsiz_baslangic_stogu_tahminidir(services):
    pid = services.products.quick_create("Maliyetsiz", 5000, initial_stock=12)
    urun = _urun(services, pid)
    assert urun["last_purchase_cost"] is None, "V1.1: 0 damgalanıyordu"
    assert _son_hareket(services, pid)["is_estimated_cost"] == 1
    assert any("alış fiyatı hiç girilmemiş" in u for u in services.db.advisories())


def test_maliyetli_baslangic_stogu_v11_gibi_damgalar(services):
    pid = services.products.quick_create("Maliyetli", 5000, initial_stock=12,
                                         purchase_cost=3000)
    urun = _urun(services, pid)
    assert (urun["last_purchase_cost"], urun["last_avg_cost"]) == (3000, 3000)
    assert _son_hareket(services, pid)["is_estimated_cost"] == 0


def test_set_initial_stock_maliyetsiz(services, cips_urunu):
    pid = services.products.quick_create("Sayılmamış", 4000)
    services.inventory.set_initial_stock(pid, 6, None)
    assert _urun(services, pid)["last_purchase_cost"] is None
    assert _son_hareket(services, pid)["is_estimated_cost"] == 1


def test_eski_sifir_damgasi_uyarida_gorunur(services):
    pid = services.products.quick_create("Eski Sıfır", 5000, initial_stock=None)
    services.inventory.set_initial_stock(pid, 6, None)
    with services.db.transaction() as conn:            # V1.1'in bıraktığı 0 damgası
        conn.execute("UPDATE products SET last_purchase_cost = 0 WHERE id = ?", (pid,))
    assert any("alış fiyatı hiç girilmemiş" in u for u in services.db.advisories())


# ===================== Şema v5 =============================================
def test_v11_verisi_v5e_yukselir(v1_1_kopya):
    db = open_database(v1_1_kopya)
    try:
        assert db.schema_version() >= 5
        assert db.scalar("SELECT COUNT(*) FROM purchase_receipt_lines "
                         "WHERE cost_is_estimated <> 0 OR previous_stamps_captured <> 0") == 0
        assert db.check_invariants(deep=True) == []
    finally:
        db.close()
