"""Fiyat Yönetimi: fiyat aritmetiği, şema v4 ve PricingService (V1.2 M5a).

Korunan sözler:
  * yuvarlama YÖN KORUR (artış asla ucuzlatmaz, düşüş asla pahalılaştırmaz);
    "fiyatı X yap" tam X'tir; değişmeyen / ters yöndeki satırlar işaretlenir,
  * toplu değişiklik tek işlemde, grup + geçmiş satırı + denetim kaydıyla yazılır;
    önizlemeden sonra fiyatı değişen ürün varsa HİÇBİR ŞEY yazılmaz,
  * geri alma saklanan eski fiyatı koyar, sonradan değişen ürüne dokunmaz, bir
    grup yalnızca bir kez geri alınır (şemada benzersiz indeks),
  * marj yalnızca bilinen gerçek alışla hesaplanır; referans alış ayrı durur,
  * ilk fiyat için yapay geçmiş satırı yazılmaz.
"""
from __future__ import annotations

import sqlite3

import pytest

from app.core import pricing_math as pm
from app.core.db import open_database
from app.core.errors import FiyatlarDegisti, GecersizFiyat, TopluFiyatHatasi
from app.services.pricing_service import (
    GERI_ALMA,
    TOPLU,
    FiyatDegisikligi,
    FiyatFiltresi,
)


def _islem(tur, deger, adim=1):
    return pm.FiyatIslemi(tur, deger, adim)


# ===================== Fiyat aritmetiği ====================================
def test_adima_yuvarlama_yonu():
    assert pm.adima_yuvarla(8050, 100, pm.YUKARI) == 8100
    assert pm.adima_yuvarla(8050, 100, pm.ASAGI) == 8000
    assert pm.adima_yuvarla(8000, 100, pm.YUKARI) == 8000
    assert pm.adima_yuvarla(8049, 50, pm.ASAGI) == 8000
    assert pm.adima_yuvarla(8051, 1, pm.ASAGI) == 8051
    assert pm.adima_yuvarla(8051, 500, pm.YONSUZ) == 8051


def test_yuzde_ve_tutar_islemleri():
    assert pm.hesapla(_islem(pm.YUZDE_ARTIR, 500, 100), 8000).yeni == 8400
    assert pm.hesapla(_islem(pm.YUZDE_ARTIR, 500, 100), 8050).yeni == 8500   # 84,525 → 85
    assert pm.hesapla(_islem(pm.YUZDE_ARTIR, 500, 1), 8050).yeni == 8453     # 84,525 → 84,53
    assert pm.hesapla(_islem(pm.YUZDE_AZALT, 500, 100), 8050).yeni == 7600   # 76,475 → 76
    assert pm.hesapla(_islem(pm.TUTAR_ARTIR, 250, 100), 8000).yeni == 8300   # 82,50 → 83
    assert pm.hesapla(_islem(pm.TUTAR_AZALT, 250, 100), 8000).yeni == 7700   # 77,50 → 77
    sonuc = pm.hesapla(_islem(pm.SABIT, 7999, 500), 8000)
    assert (sonuc.yeni, sonuc.durum) == (7999, pm.DEGISIR), "sabit tutar yuvarlanmaz"


@pytest.mark.parametrize("adim", list(pm.YUVARLAMA_ADIMLARI))
def test_yuvarlama_hicbir_fiyatta_yonu_bozmaz(adim):
    for eski in range(1, 3001, 7):
        for bp in (1, 50, 333, 500, 1000, 2500, 9999):
            artis = pm.hesapla(_islem(pm.YUZDE_ARTIR, bp, adim), eski)
            assert artis.yeni > eski and artis.durum == pm.DEGISIR, (eski, bp, adim)
            azalis = pm.hesapla(_islem(pm.YUZDE_AZALT, bp, adim), eski)
            if azalis.durum != pm.GECERSIZ:
                assert azalis.yeni < eski, (eski, bp, adim)


def test_durumlar():
    assert pm.hesapla(_islem(pm.YUZDE_ARTIR, 500), None).durum == pm.FIYATSIZ
    assert pm.hesapla(_islem(pm.SABIT, 8000), None).durum == pm.DEGISIR
    assert pm.hesapla(_islem(pm.SABIT, 8000), 8000).durum == pm.AYNI
    assert pm.hesapla(_islem(pm.YUZDE_ARTIR, 0), 8000).durum == pm.AYNI
    assert pm.hesapla(_islem(pm.TUTAR_AZALT, 9000), 8000).durum == pm.GECERSIZ
    assert pm.hesapla(_islem(pm.YUZDE_AZALT, 10000), 8000).durum == pm.GECERSIZ
    assert pm.hesapla(_islem(pm.MARJ, 3000), 8000, None).durum == pm.MALIYETSIZ
    ters = pm.hesapla(_islem(pm.MARJ, 3000, 100), 9000, 5000)
    assert (ters.yeni, ters.durum) == (7200, pm.TERS_YON)
    assert not ters.varsayilan_secili
    assert pm.hesapla(_islem(pm.SABIT, pm.EN_YUKSEK_FIYAT + 1), 8000).durum == pm.GECERSIZ
    with pytest.raises(GecersizFiyat):
        _islem(pm.MARJ, 10000)
    with pytest.raises(ValueError):
        _islem(pm.SABIT, 100, 7)


def test_marj_hesaplari():
    assert pm.marj_fiyati(5000, 3000, 100) == 7200            # 71,43 → 72
    assert pm.marj_bp(7200, 5000) >= 3000
    assert pm.marj_bp(8000, 5000) == 3750
    assert pm.marj_bp(4000, 5000) == -2500
    assert pm.marj_bp(8000, None) is None and pm.marj_bp(8000, 0) is None
    assert pm.degisim_bp(8000, 8400) == 500
    assert pm.degisim_bp(None, 8400) is None
    assert pm.marji_koruyan_fiyat(8000, 5000, 5500, 100) == 8800
    assert pm.marji_koruyan_fiyat(8000, 5000, 4510, 100) == 7200   # 72,16 → 72 (aşağı)
    assert pm.marji_koruyan_fiyat(8000, 5000, 5010, 100) == 8100   # 80,16 → 81 (yukarı)


def test_yuzde_metni():
    assert pm.yuzde_metninden_bp("7,5") == 750
    assert pm.yuzde_metninden_bp("%12.25") == 1225
    assert pm.yuzde_metninden_bp(" 5 ") == 500
    for kotu in ("1,234", "-3", "abc", ""):
        with pytest.raises(GecersizFiyat):
            pm.yuzde_metninden_bp(kotu)
    assert pm.bp_metni(1250) == "%12,5"
    assert pm.bp_metni(1205) == "%12,05"
    assert pm.bp_metni(-300) == "−%3"


# ===================== Şema v4 =============================================
def test_v11_verisi_v4e_yukselir(v1_1_kopya):
    db = open_database(v1_1_kopya)
    try:
        assert db.schema_version() >= 4
        assert db.scalar("SELECT COUNT(*) FROM price_history WHERE batch_id IS NOT NULL") == 0
        assert db.scalar("SELECT COUNT(*) FROM price_history") > 0
        assert db.check_invariants(deep=True) == []
    finally:
        db.close()


def test_grup_yalnizca_bir_kez_geri_alinir_semada(services):
    with services.db.transaction() as conn:
        conn.execute("INSERT INTO price_change_batches(id, created_at_utc, kind) "
                     "VALUES(1, 0, 'TOPLU')")
        conn.execute("INSERT INTO price_change_batches(created_at_utc, kind, "
                     "reverses_batch_id) VALUES(0, 'GERI_ALMA', 1)")
    with pytest.raises(sqlite3.IntegrityError):
        with services.db.transaction() as conn:
            conn.execute("INSERT INTO price_change_batches(created_at_utc, kind, "
                         "reverses_batch_id) VALUES(0, 'GERI_ALMA', 1)")
    with pytest.raises(sqlite3.IntegrityError):
        with services.db.transaction() as conn:
            conn.execute("INSERT INTO price_change_batches(created_at_utc, kind) "
                         "VALUES(0, 'YANLIS')")


def test_yuvarlama_ayari(services):
    assert services.settings.price_rounding() == 100
    services.settings.set("price_rounding", 7)
    assert services.settings.price_rounding() == 100
    services.settings.set("price_rounding", 50)
    assert services.settings.price_rounding() == 50


# ===================== Servis ==============================================
def _alis(services, pid, adet, maliyet):
    fis = services.purchases.start_draft()
    services.purchases.add_line(fis, pid, adet, maliyet)
    services.purchases.commit(fis)


def test_liste_bilinen_ve_referans_maliyet(services, bira, cips_urunu):
    _alis(services, bira, 24, 5000)
    services.products.set_reference_cost(cips_urunu, 3100)
    services.products.set_price(bira, 8500)
    satirlar = {s.product_id: s for s in services.pricing.listele()}
    assert satirlar[bira].bilinen_maliyet == 5000
    assert (satirlar[bira].marka, satirlar[cips_urunu].marka) == ("Tuborg", "")
    assert satirlar[bira].marj_bp == pm.marj_bp(8500, 5000)
    assert satirlar[bira].son_fiyat_degisimi_utc is not None
    assert satirlar[bira].son_alis_utc is not None
    assert satirlar[cips_urunu].bilinen_maliyet is None, "referans alış bilinen maliyet değil"
    assert satirlar[cips_urunu].referans_maliyet == 3100
    assert satirlar[cips_urunu].marj_bp is None

    yalniz = services.pricing.listele(FiyatFiltresi(yalniz_maliyetsiz=True))
    assert [s.product_id for s in yalniz] == [cips_urunu]
    assert services.pricing.listele(FiyatFiltresi(yalniz_fiyatsiz=True)) == []


def test_onizleme_yazmaz_ve_uygulama_tek_grup(services, bira, cips_urunu):
    once = services.db.scalar("SELECT COUNT(*) FROM price_history")
    onizleme = services.pricing.onizle([bira, cips_urunu], _islem(pm.YUZDE_ARTIR, 1000, 100))
    assert [(s.eski, s.yeni, s.durum) for s in onizleme] == [
        (8000, 8800, pm.DEGISIR), (5000, 5500, pm.DEGISIR)]
    assert services.db.scalar("SELECT COUNT(*) FROM price_history") == once

    grup = services.pricing.uygula(
        [FiyatDegisikligi(s.product_id, s.eski, s.yeni) for s in onizleme],
        aciklama="Zam %10",
    )
    assert services.products.get(bira)["sale_price"] == 8800
    satir = services.pricing.grup(grup)
    assert (satir["kind"], satir["product_count"], satir["geri_alan"]) == (TOPLU, 2, None)
    gecmis = services.db.query("SELECT * FROM price_history WHERE batch_id = ?", (grup,))
    assert {(g["old_price"], g["new_price"], g["source"]) for g in gecmis} == {
        (8000, 8800, "BULK"), (5000, 5500, "BULK")}
    assert services.db.scalar(
        "SELECT COUNT(*) FROM audit_log WHERE action = 'TOPLU_FIYAT' AND entity_id = ?",
        (grup,)) == 1
    assert services.db.check_invariants(deep=True) == []


def test_onizlemeden_sonra_degisen_fiyat_hicbir_seyi_yazdirmaz(services, bira, cips_urunu):
    onizleme = services.pricing.onizle([bira, cips_urunu], _islem(pm.SABIT, 9900))
    services.products.set_price(cips_urunu, 5200)                # araya giren değişiklik
    with pytest.raises(FiyatlarDegisti):
        services.pricing.uygula(
            [FiyatDegisikligi(s.product_id, s.eski, s.yeni) for s in onizleme])
    assert services.products.get(bira)["sale_price"] == 8000, "hiçbiri yazılmadı"
    assert services.db.scalar("SELECT COUNT(*) FROM price_change_batches") == 0


def test_gecersiz_uygulama(services, bira):
    with pytest.raises(TopluFiyatHatasi):
        services.pricing.uygula([])
    with pytest.raises(TopluFiyatHatasi):
        services.pricing.uygula([FiyatDegisikligi(bira, 8000, 8000)])
    with pytest.raises(TopluFiyatHatasi):
        services.pricing.uygula([FiyatDegisikligi(bira, 8000, 0)])
    with pytest.raises(TopluFiyatHatasi):
        services.pricing.uygula([FiyatDegisikligi(bira, 8000, 9000),
                                 FiyatDegisikligi(bira, 8000, 9100)])
    with pytest.raises(ValueError):
        services.pricing.uygula([FiyatDegisikligi(bira, 8000, 9000)], tur=GERI_ALMA)


def test_geri_alma_saklanan_eski_fiyati_koyar(services, bira, cips_urunu):
    grup = services.pricing.uygula([
        FiyatDegisikligi(bira, 8000, 8800), FiyatDegisikligi(cips_urunu, 5000, 5500)])
    services.products.set_price(cips_urunu, 6000)                 # sonradan elle
    onizleme = {s.product_id: s for s in services.pricing.geri_alma_onizle(grup)}
    assert onizleme[bira].uygun and onizleme[bira].geri_konacak == 8000
    assert not onizleme[cips_urunu].uygun

    geri, alinan, dokunulmayan = services.pricing.geri_al(grup)
    assert (alinan, dokunulmayan) == (1, 1)
    assert services.products.get(bira)["sale_price"] == 8000
    assert services.products.get(cips_urunu)["sale_price"] == 6000, "elle değişene dokunulmadı"
    assert services.pricing.grup(grup)["geri_alan"] == geri
    assert services.pricing.grup(geri)["reverses_batch_id"] == grup

    with pytest.raises(TopluFiyatHatasi, match="zaten geri alındı"):
        services.pricing.geri_al(grup)
    with pytest.raises(TopluFiyatHatasi, match="geri alınamaz"):
        services.pricing.geri_al(geri)
    assert services.db.check_invariants(deep=True) == []


def test_hepsi_sonradan_degismisse_geri_alma_reddedilir(services, bira):
    grup = services.pricing.uygula([FiyatDegisikligi(bira, 8000, 8800)])
    services.products.set_price(bira, 8800 + 100)
    services.products.set_price(bira, 8800)          # aynı fiyata dönse de SON kayıt değil
    with pytest.raises(TopluFiyatHatasi, match="kalmadı"):
        services.pricing.geri_al(grup)
    assert services.products.get(bira)["sale_price"] == 8800


def test_zaman_cizelgesi_yapay_satir_yazmaz(services, bira):
    services.products.set_price(bira, 8500, "zam")
    grup = services.pricing.uygula([FiyatDegisikligi(bira, 8500, 9000)], aciklama="Toplu")
    services.pricing.geri_al(grup)
    olaylar = services.pricing.zaman_cizelgesi(bira)
    assert [(o.kaynak, o.eski, o.yeni) for o in olaylar] == [
        ("Geri alma", 9000, 8500),
        ("Toplu değişiklik", 8500, 9000),
        ("Elle", 8000, 8500),
        ("ilk fiyat (kayıt yok)", None, 8000),
    ]
    assert olaylar[-1].zaman_utc is None
    assert services.db.scalar("SELECT COUNT(*) FROM price_history WHERE product_id = ?",
                              (bira,)) == 3


def test_i35_fiyat_gecmisi_disinda_degisen_fiyati_yakalar(services, bira):
    services.products.set_price(bira, 8500)
    with services.db.transaction() as conn:
        conn.execute("UPDATE products SET sale_price = 1 WHERE id = ?", (bira,))
    assert any(p.startswith("I35") for p in services.db.check_invariants(deep=True))
