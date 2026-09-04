"""Para, Türkçe metin, miktar, barkod kimliği ve iş günü hesabı."""
from __future__ import annotations

from datetime import datetime

import pytest

from app.core import barcode_text as bt
from app.core import quantity as qty
from app.core import tr
from app.core.clock import BusinessCalendar
from app.core.errors import (
    BosBarkod,
    DesteklenmeyenOlcuTuru,
    GecersizFiyat,
    GecersizMiktar,
)
from app.core.money import format_tl, kurus_to_tl_text, net_amount, tl_to_kurus, vat_amount


# =========================== PARA =========================================
@pytest.mark.parametrize(
    "girdi, kurus",
    [
        ("80", 8000), ("80,50", 8050), ("1.250", 125000), ("1.250,50", 125050),
        ("80.50", 8050), ("80 TL", 8000), ("0", 0), (80, 8000),
    ],
)
def test_fiyat_okuma(girdi, kurus):
    assert tl_to_kurus(girdi) == kurus


@pytest.mark.parametrize("girdi", ["", "abc", "-5", "  ", "9999999"])
def test_gecersiz_fiyat_reddedilir(girdi):
    with pytest.raises(GecersizFiyat):
        tl_to_kurus(girdi)


@pytest.mark.parametrize(
    "kurus, metin",
    [(8000, "80 TL"), (8050, "80,50 TL"), (125000, "1.250 TL"), (0, "0 TL"),
     (-8000, "-80 TL"), (None, "-")],
)
def test_fiyat_gosterimi(kurus, metin):
    assert format_tl(kurus) == metin


def test_duzenleme_alani_bicimi():
    assert kurus_to_tl_text(8000) == "80"
    assert kurus_to_tl_text(8050) == "80,50"


def test_kdv_dahil_fiyattan_kdv_ayrilir():
    """Raf fiyatı 120 TL, KDV %20 -> KDV 20 TL, matrah 100 TL."""
    assert vat_amount(12000, 20, prices_include_vat=True) == 2000
    assert net_amount(12000, 20, prices_include_vat=True) == 10000


def test_kdv_haric_fiyatta_kdv_eklenir():
    assert vat_amount(10000, 20, prices_include_vat=False) == 2000


def test_kdv_orani_yoksa_sifir():
    assert vat_amount(12000, None, True) == 0


# =========================== TÜRKÇE METİN =================================
def test_turkce_buyutme_kucultme():
    assert tr.tr_upper("iğne şiş") == "İĞNE ŞİŞ"
    assert tr.tr_lower("IŞIK") == "ışık"
    assert tr.tr_upper("ıslak") == "ISLAK"


def test_aksansiz_arama_bulur():
    assert tr.search_matches("Şanslı Yonca", "sansli")
    assert tr.search_matches("Çaykur Rize", "caykur")
    assert tr.search_matches("Ülker Çikolata", "ulker")
    assert not tr.search_matches("Tuborg Gold", "efes")


def test_arama_bulanik_degildir():
    """Tahmin edilebilirlik için yalnızca alt dizi araması yapılır."""
    assert not tr.search_matches("Tuborg", "tubrog")


def test_normalize_name_tekillik_icin_kullanilir():
    assert tr.normalize_name("Bira") == tr.normalize_name("BİRA") == "bira"
    assert tr.normalize_name("  Enerji   İçeceği ") == "enerji icecegi"


def test_turkce_siralama():
    adlar = ["Zeytin", "Çilek", "Armut", "Işık", "İncir", "Öz"]
    assert sorted(adlar, key=tr.tr_sort_key) == [
        "Armut", "Çilek", "Işık", "İncir", "Öz", "Zeytin",
    ]


def test_tarih_ve_sayi_bicimleri():
    assert tr.fmt_date("2026-09-05") == "05.09.2026"
    assert tr.fmt_date_long("2026-09-05") == "5 Eylül 2026 Cumartesi"
    assert tr.fmt_int(1250) == "1.250"
    assert tr.fmt_decimal(1.5) == "1,5"
    assert tr.fmt_percent(12.5) == "%12,5"
    assert tr.fmt_signed_int(3) == "+3"
    assert tr.fmt_signed_int(-3) == "-3"


# =========================== MİKTAR =======================================
def test_v1_yalnizca_sayilabilir_urunu_kabul_eder():
    qty.ensure_v1_supported("COUNT", "ADET", "PER_UNIT")
    qty.ensure_v1_supported(None, None, None)          # varsayılanlar
    with pytest.raises(DesteklenmeyenOlcuTuru):
        qty.ensure_v1_supported("WEIGHT", "GRAM", "PER_1000_BASE")
    with pytest.raises(DesteklenmeyenOlcuTuru):
        qty.ensure_v1_supported("COUNT", "GRAM", "PER_UNIT")


def test_miktar_tam_sayidir():
    assert qty.parse_quantity("6") == 6
    assert qty.parse_quantity("1.250") == 1250
    assert qty.parse_positive_quantity(24) == 24


def test_kesirli_miktar_sessizce_yuvarlanmaz_reddedilir():
    with pytest.raises(GecersizMiktar):
        qty.parse_quantity("2,5")


@pytest.mark.parametrize("girdi", ["", "abc", "  "])
def test_gecersiz_miktar_reddedilir(girdi):
    with pytest.raises(GecersizMiktar):
        qty.parse_quantity(girdi)


def test_sifir_adet_satis_icin_reddedilir():
    with pytest.raises(GecersizMiktar):
        qty.parse_positive_quantity("0")


def test_carpan_tek_yerden_uygulanir():
    assert qty.to_base_units(1, 24) == 24
    assert qty.to_base_units(3, 6) == 18
    assert qty.to_base_units(5, 1) == 5


def test_miktar_gosterimi_etiketi_urunden_alir():
    assert qty.format_quantity(24, {"unit_label": "Koli"}) == "24 Koli"
    assert qty.format_quantity(1250, None) == "1.250 Adet"
    assert qty.format_quantity_signed(-3, None) == "-3 Adet"
    assert qty.format_quantity(5, None, with_label=False) == "5"


# =========================== BARKOD KİMLİĞİ ===============================
def test_bastaki_sifirlar_korunur():
    """00123 ile 123 FARKLI barkodlardır — körü körüne sıfır atılmaz."""
    assert bt.normalize("00123") == "00123"
    assert bt.normalize("123") == "123"
    assert bt.normalize("00123") != bt.normalize("123")


def test_gtin_olmayan_kisa_kodlar_opaktir():
    assert bt.to_gtin14("00123") is None
    assert bt.to_gtin14("123") is None
    assert bt.to_gtin14("RAF-01") is None


def test_upc_a_ile_ean13_ayni_urune_cozulur():
    """Kontrol hanesi KANITLADIĞI için bu ikisi gerçekten aynı üründür."""
    upc = bt.to_gtin14("012345678905")
    ean = bt.to_gtin14("0012345678905")
    assert upc is not None and upc == ean == "00012345678905"


def test_ean8_kanonik_bicime_cevrilir():
    assert bt.to_gtin14("96385074") == "00000096385074"


def test_gecersiz_kontrol_hanesi_opak_kabul_edilir():
    """13 hane ama kontrol hanesi yanlış -> kanonikleştirilmez."""
    assert bt.is_valid_gtin("8690000000001") is False
    assert bt.to_gtin14("8690000000001") is None


def test_gercek_ean13_dogrulanir():
    assert bt.is_valid_gtin("8690504001492") is True
    assert bt.to_gtin14("8690504001492") == "08690504001492"


def test_ayraclar_ve_bosluklar_temizlenir():
    assert bt.normalize(" 8690 504-001 492 ") == "8690504001492"
    assert bt.normalize("869-050\t4001492") == "8690504001492"


def test_barkod_ascii_buyutulur_turkce_degil():
    """Barkodlar ASCII'dir: 'i' -> 'I' olmalı, 'İ' DEĞİL."""
    assert bt.normalize("abi123") == "ABI123"
    assert "İ" not in bt.normalize("abi123")


def test_bos_barkod_reddedilir():
    with pytest.raises(BosBarkod):
        bt.normalize("   ")
    with pytest.raises(BosBarkod):
        bt.normalize(None)


def test_okuyucu_onek_sonek_kirpma():
    assert bt.normalize("XX8690504001492", trim_prefix="XX") == "8690504001492"
    assert bt.normalize("8690504001492YY", trim_suffix="YY") == "8690504001492"


# =========================== İŞ GÜNÜ ======================================
def test_varsayilan_takvim_gunu():
    takvim = BusinessCalendar()
    damga = takvim.stamp(datetime(2026, 9, 5, 1, 30))
    assert damga.business_date == "2026-09-05"
    assert damga.local_date == "2026-09-05"
    assert damga.local_hour == 1


def test_gun_baslangici_04_gece_satisini_onceki_gune_yazar():
    takvim = BusinessCalendar([("2026-01-01", 4)])
    damga = takvim.stamp(datetime(2026, 9, 5, 1, 30))
    assert damga.business_date == "2026-09-04"
    assert damga.local_date == "2026-09-05", "gerçek zaman damgası DEĞİŞMEZ"
    assert damga.local_hour == 1, "gerçek saat DEĞİŞMEZ"


def test_gun_baslangicindan_sonra_ayni_gun():
    takvim = BusinessCalendar([("2026-01-01", 4)])
    assert takvim.stamp(datetime(2026, 9, 5, 4, 0)).business_date == "2026-09-05"
    assert takvim.stamp(datetime(2026, 9, 5, 23, 59)).business_date == "2026-09-05"


def test_kural_gecerlilik_tarihlidir_gecmisi_yeniden_yazmaz():
    """Ayarı bugün değiştirmek DÜNKÜ raporu değiştirmemeli."""
    takvim = BusinessCalendar([("2026-01-01", 0), ("2026-09-05", 4)])
    eski = takvim.stamp(datetime(2026, 8, 20, 1, 0))
    yeni = takvim.stamp(datetime(2026, 9, 6, 1, 0))
    assert eski.business_date == "2026-08-20", "kural öncesi gün etkilenmez"
    assert yeni.business_date == "2026-09-05", "kural sonrası gün kaydırılır"


def test_haftanin_gunu_is_gununden_turetilir():
    """Cumartesi gecesi 01:00 satışı, gün başlangıcı 04:00 ise CUMARTESİ'dir.

    (Takvimde pazardır; ham tarihten türetilseydi 'en yoğun gün' analizi tam da
    en önemli saatlerde yanlış sonuç verirdi.)
    """
    takvim = BusinessCalendar([("2026-01-01", 4)])
    damga = takvim.stamp(datetime(2026, 9, 6, 1, 0))     # Pazar 01:00
    assert damga.business_date == "2026-09-05"           # Cumartesi
    assert damga.local_dow == 5                          # 5 = Cumartesi
    assert tr.GUNLER[damga.local_dow] == "Cumartesi"


def test_kural_listesi_her_zaman_varsayilanla_baslar():
    takvim = BusinessCalendar([("2026-09-05", 4)])
    assert takvim.start_hour_for("2020-01-01") == 0
    assert takvim.start_hour_for("2026-09-05") == 4
