"""Kategoriler (V1.2 M4a) — servis.

Korunan sözler:
  * yeni kurulum §6.1 şablonuyla gelir (5 üst + 29 alt) ve şablon kendi içinde
    benzerlik uyarısı üretmez,
  * aynı üst altında aynı ad (Türkçe/aksan duyarsız) SERT engel; benzer adlar
    yalnızca uyarı ("biralar", "Viskiler", başka yerde aynı ad, 1–2 harf),
  * en çok iki düzey; kullanımdaki altı olan kategori kaldırılamaz;
    birleştirme ürünleri taşır ve kaynağı kaldırır,
  * mevcut kurulumda şablon yalnızca önizlemeyle ve isteğe bağlı adımlarla
    uygulanır; tekrar uygulamak hiçbir şey eklemez.
"""
from __future__ import annotations

import pytest

from app.core.db import open_database
from app.core.schema import KATEGORI_SABLONU
from app.services.category_service import (
    ADIM_EKLE,
    ADIM_TASI,
    ADIM_URUN_TASI,
    ADIM_YENIDEN_ADLANDIR,
    KategoriHatasi,
)
from app.services.container import build_services


def _kimlik(services, ad, ust=None):
    if ust is None:
        return services.db.scalar(
            "SELECT id FROM categories WHERE name = ? AND parent_id IS NULL", (ad,))
    return services.db.scalar(
        "SELECT c.id FROM categories c JOIN categories u ON u.id = c.parent_id "
        " WHERE c.name = ? AND u.name = ?", (ad, ust))


# ===================== Şablon ==============================================
def test_yeni_kurulum_sablonu_birebir(services):
    agac = services.categories.tree()
    assert [(d.name, [c.name for c in d.altlar]) for d in agac] == [
        (ust, list(altlar)) for ust, altlar in KATEGORI_SABLONU
    ]
    assert services.db.scalar("SELECT COUNT(*) FROM categories") == 34
    assert services.categories.template_preview() == [], "eksik yok"


def test_sablon_kendi_icinde_benzerlik_uyarisi_uretmez(services):
    for satir in services.db.query("SELECT * FROM categories"):
        uyarilar = services.categories.similar_names(
            satir["name"], satir["parent_id"], exclude_id=satir["id"]
        )
        assert uyarilar == [], (satir["name"], uyarilar)


# ===================== Ad kuralları ========================================
@pytest.mark.parametrize("ad", ["Bira", "BİRA", "bira ", "  Bira"])
def test_ayni_ustte_ayni_ad_engellenir(services, ad):
    ust = _kimlik(services, "Alkollü İçecekler")
    with pytest.raises(KategoriHatasi) as bilgi:
        services.categories.create(ad, ust)
    assert "zaten var" in bilgi.value.message


@pytest.mark.parametrize(
    "ad,ust,beklenen",
    [
        ("biralar", "Alkollü İçecekler", "Tekil/çoğul"),
        ("Viskiler", "Alkollü İçecekler", "Tekil/çoğul"),
        ("BİRA", "Soğuk İçecek", "Aynı ad başka yerde"),
        ("Bira ", "Atıştırmalık", "Aynı ad başka yerde"),
        ("Votkaa", "Alkollü İçecekler", "Çok benzer"),
    ],
)
def test_benzer_adlar_uyarir_ama_engellemez(services, ad, ust, beklenen):
    ust_id = _kimlik(services, ust)
    uyarilar = services.categories.similar_names(ad, ust_id)
    assert any(beklenen in u for u in uyarilar), uyarilar
    if ad.strip().lower() not in ("bira",) or ust != "Alkollü İçecekler":
        kimlik = services.categories.create(ad, ust_id)
        assert services.categories.get(kimlik)["name"] == ad.strip()


def test_kisa_adlarda_harf_farki_uyarisi_yok(services):
    assert services.categories.similar_names("Biraa", None) == []


# ===================== Düzey, kaldırma, taşıma ============================
def test_en_cok_iki_duzey(services):
    bira = _kimlik(services, "Bira", "Alkollü İçecekler")
    with pytest.raises(KategoriHatasi) as bilgi:
        services.categories.create("Fıçı", bira)
    assert "iki düzey" in bilgi.value.message
    tutun = _kimlik(services, "Tütün")
    with pytest.raises(KategoriHatasi):
        services.categories.move(tutun, _kimlik(services, "Diğer"))
    services.categories.move(bira, None)                   # alt → üst düzey: serbest
    assert services.categories.get(bira)["parent_id"] is None


def test_kullanimdaki_altlari_olan_kaldirilamaz(services):
    tutun = _kimlik(services, "Tütün")
    with pytest.raises(KategoriHatasi) as bilgi:
        services.categories.deactivate(tutun)
    assert "alt kategorileri" in bilgi.value.message
    for satir in services.db.query("SELECT id FROM categories WHERE parent_id = ?", (tutun,)):
        services.categories.deactivate(satir["id"])
    services.categories.deactivate(tutun)
    sigara = _kimlik(services, "Sigara", "Tütün")
    with pytest.raises(KategoriHatasi) as bilgi:
        services.categories.reactivate(sigara)
    assert "üst kategoriyi" in bilgi.value.message
    services.categories.reactivate(tutun)
    services.categories.reactivate(sigara)
    assert services.categories.get(sigara)["active"] == 1


def test_kaldirilan_ayni_ad_yeniden_kullanima_yonlendirilir(services):
    sakiz = _kimlik(services, "Sakız", "Atıştırmalık")
    services.categories.deactivate(sakiz)
    with pytest.raises(KategoriHatasi) as bilgi:
        services.categories.create("sakız", _kimlik(services, "Atıştırmalık"))
    assert "Yeniden kullanıma alabilirsiniz" in bilgi.value.message


def test_yeniden_adlandirma_ve_kopya_engeli(services):
    cin = _kimlik(services, "Cin", "Alkollü İçecekler")
    with pytest.raises(KategoriHatasi):
        services.categories.rename(cin, "RAKI")
    services.categories.rename(cin, "Cin ve Votka Kokteyl")
    assert services.categories.path(cin) == "Alkollü İçecekler > Cin ve Votka Kokteyl"
    assert services.db.scalar(
        "SELECT COUNT(*) FROM audit_log WHERE action = 'KATEGORI_AD'") == 1


def test_birlestirme_urunleri_tasir_kaynagi_kaldirir(services):
    kola = _kimlik(services, "Kola", "Soğuk İçecek")
    gazoz = _kimlik(services, "Gazoz", "Soğuk İçecek")
    a = services.products.quick_create("Kola 1 L", 4000, category_id=kola)
    b = services.products.quick_create("Kola 2 L", 6000, category_id=kola)
    assert services.categories.merge(kola, gazoz) == 2
    assert {services.products.get(p)["category_id"] for p in (a, b)} == {gazoz}
    assert services.categories.get(kola)["active"] == 0
    with pytest.raises(KategoriHatasi):
        services.categories.merge(_kimlik(services, "Tütün"), _kimlik(services, "Diğer"))
    with pytest.raises(KategoriHatasi):
        services.categories.merge(gazoz, gazoz)


def test_agac_sayilari_ve_kategorisiz(services):
    bira = _kimlik(services, "Bira", "Alkollü İçecekler")
    services.products.quick_create("Efes", 7000, category_id=bira)
    pasif = services.products.quick_create("Eski Efes", 7000, category_id=bira)
    services.products.set_active(pasif, False)
    services.products.quick_create("Kategorisiz", 1000)
    alkol = next(d for d in services.categories.tree() if d.name == "Alkollü İçecekler")
    assert alkol.urun_sayisi == 0 and alkol.toplam_urun == 1
    assert next(c for c in alkol.altlar if c.name == "Bira").urun_sayisi == 1
    assert services.categories.uncategorized_count() == 1


def test_arama_yol_ile(services):
    bulunan = {yol for _, yol in services.categories.search("sigar")}
    assert bulunan == {"Tütün > Sigara", "Tütün > Puro / Sigarillo"}


# ===================== Mevcut kurulumda şablon ============================
@pytest.fixture
def v11(v1_1_kopya):
    svc = build_services(open_database(v1_1_kopya))
    yield svc
    svc.close()


def test_v11_kurulumu_kendiliginden_degismez_onizleme_istege_bagli(v11):
    assert v11.db.scalar("SELECT COUNT(*) FROM categories") == 20, "dokunulmadı"
    adimlar = v11.categories.template_preview()
    turler = {(a.tur, a.ad) for a in adimlar}
    assert (ADIM_YENIDEN_ADLANDIR, "Soğuk İçecek") in turler
    assert not next(a for a in adimlar if a.tur == ADIM_YENIDEN_ADLANDIR).secili
    assert (ADIM_EKLE, "Soda") in turler and (ADIM_EKLE, "Cin") in turler
    assert (ADIM_EKLE, "Soğuk İçecek") not in turler, "eşadlı İçecekler kullanılır"


def test_v11_sablon_uygulama_ve_tekrar(v11):
    adimlar = v11.categories.template_preview()
    uygulanan = v11.categories.apply_template(adimlar)
    assert uygulanan > 0
    assert v11.db.scalar(
        "SELECT COUNT(*) FROM categories WHERE parent_id = "
        "(SELECT id FROM categories WHERE name = 'İçecekler')") == 6, "Soda eklendi"
    kalan = v11.categories.template_preview()
    assert {a.tur for a in kalan} <= {ADIM_YENIDEN_ADLANDIR, ADIM_URUN_TASI}, kalan
    assert v11.categories.apply_template(
        [a for a in kalan if a.tur not in (ADIM_YENIDEN_ADLANDIR, ADIM_URUN_TASI)]) == 0
    assert v11.db.check_invariants(deep=True) == []


def test_istege_bagli_yeniden_adlandirma_ve_urun_tasima(v11):
    diger = v11.db.scalar("SELECT id FROM categories WHERE name='Diğer' AND parent_id IS NULL")
    urun = v11.products.quick_create("Islak Mendil", 1500, category_id=diger)
    adimlar = v11.categories.template_preview()
    for adim in adimlar:
        adim.secili = True
    v11.categories.apply_template(adimlar)
    assert v11.db.scalar(
        "SELECT COUNT(*) FROM categories WHERE name='Soğuk İçecek' AND parent_id IS NULL") == 1
    yeni = v11.products.get(urun)["category_id"]
    assert v11.categories.path(yeni) == "Diğer > Diğer"
    assert v11.categories.template_preview() == []


def test_yanlis_yerdeki_ayni_ad_kopyalanmaz_tasinir(services):
    services.categories.deactivate(_kimlik(services, "Buz", "Diğer"))
    services.db.execute("UPDATE categories SET name='Buzz', name_norm='buzz' "
                        "WHERE name='Buz'")                         # eski kaydı ayır
    yanlis = services.categories.create("Buz", _kimlik(services, "Atıştırmalık"))
    adimlar = services.categories.template_preview()
    tasi = [a for a in adimlar if a.tur == ADIM_TASI]
    assert len(tasi) == 1 and tasi[0].kategori_id == yanlis
    services.categories.apply_template(adimlar)
    assert services.categories.path(yanlis) == "Diğer > Buz"
