"""Ürün listesi içe aktarma (V1.2 M7a).

Korunan sözler:
  * CSV: utf-8-sig / utf-8 / cp1254 ve ; , TAB ayırıcıları; hücreler metin
    kalır (baştaki sıfır kaybolmaz). XLSX yalnızca openpyxl ile okunur;
    sayı hücresi barkod işaretlenir; .xls reddedilir,
  * başlıklar Türkçe eş anlamlılarla otomatik eşlenir,
  * önizleme yazmaz; satır durumları YENI / GUNCELLE / AYNI / CAKISMA /
    GECERSIZ / ATLANDI ve plan §6.2 sayıları doğru,
  * barkod ASLA kendiliğinden düzeltilmez; sıfırla tamamlama yalnızca kabul
    edilen satırda uygulanır,
  * uygulama: önce güvenlik yedeği, sonra TEK işlem; hata olursa hiçbiri,
    fiyatlar "İçe aktarma" grubu (geri alınabilir), alış sütunu yalnızca
    referans alış, boş hücre üzerine yazmaz, yalnızca seçilen alanlar
    güncellenir, denetim kaydı dosya adı + SHA-256 taşır.
"""
from __future__ import annotations

import csv
import io
import json
from pathlib import Path

import pytest

from app.core import barcode_text as bt
from app.core.errors import DomainError, YedekHatasi
from app.importers import alanlar as al
from app.importers.okuyucu import XLSX_KULLANILABILIR, DosyaOkunamadi, dosya_ozeti, oku
from app.services import import_service as ims

from conftest import BIRA_BARKOD

pytestmark = pytest.mark.skipif(not XLSX_KULLANILABILIR, reason="openpyxl yok")

BASLIK = "Barkod;Ürün Adı;Satış Fiyatı;Kategori;Marka;Tedarikçi;Alış Fiyatı;KDV"


def _csv(tmp_path: Path, satirlar: list[str], ad="liste.csv", kodlama="utf-8-sig",
         baslik=BASLIK) -> Path:
    yol = tmp_path / ad
    yol.write_bytes(("\r\n".join([baslik, *satirlar]) + "\r\n").encode(kodlama))
    return yol


def _gtin13(govde12: str) -> str:
    return govde12 + str(bt.gtin_check_digit(govde12))


def _plan(services, yol, politika=ims.EKLE_VE_GUNCELLE, varsayilan=None, kabul=frozenset()):
    tablo = oku(yol)
    return services.imports.onizle(tablo, al.otomatik_esle(tablo.basliklar), politika,
                                   varsayilan, kabul)


def _kategori(services, ad):
    return services.db.scalar("SELECT id FROM categories WHERE name = ? "
                              "ORDER BY parent_id IS NULL LIMIT 1", (ad,))


# ===================== Okuma ===============================================
def test_csv_kodlama_ve_ayiricilar(tmp_path):
    for kodlama, ayirici in (("utf-8-sig", ";"), ("utf-8", ","), ("cp1254", "\t")):
        yol = tmp_path / f"{kodlama}.csv"
        tampon = io.StringIO()
        yazici = csv.writer(tampon, delimiter=ayirici, lineterminator="\r\n")
        yazici.writerows([["Barkod", "Ürün Adı", "Satış"],
                          ["0012345", "Şarap Çeşit", "80,50"]])
        yol.write_bytes(tampon.getvalue().encode(kodlama))
        tablo = oku(yol)
        assert tablo.basliklar == ["Barkod", "Ürün Adı", "Satış"], kodlama
        assert tablo.satirlar == [["0012345", "Şarap Çeşit", "80,50"]], kodlama
        assert tablo.ayirici == ayirici


def test_xlsx_hucre_turleri(tmp_path):
    import openpyxl

    kitap = openpyxl.Workbook()
    sayfa = kitap.active
    sayfa.append(["Barkod", "Ürün adı", "Satış fiyatı", "KDV"])
    sayfa.append(["0012345678905", "Metin Barkod", 80.5, 0.2])
    sayfa.append([8690504001492, "Sayı Barkod", 75, 20])
    sayfa.append([None, None, None, None])
    yol = tmp_path / "liste.xlsx"
    kitap.save(yol)
    tablo = oku(yol)
    assert tablo.bicim == "XLSX" and len(tablo.satirlar) == 2
    metin = al.barkod_hucresi(tablo.satirlar[0][0])
    sayi = al.barkod_hucresi(tablo.satirlar[1][0])
    assert (metin.metin, metin.sayisal) == ("0012345678905", False), "sıfırlar korunur"
    assert (sayi.metin, sayi.sayisal) == ("8690504001492", True)
    assert al.fiyat_hucresi(tablo.satirlar[0][2]) == 8050
    assert al.kdv_hucresi(tablo.satirlar[0][3]) == 20


def test_reddedilen_dosyalar(tmp_path):
    (tmp_path / "eski.xls").write_bytes(b"\xd0\xcf\x11\xe0")
    with pytest.raises(DosyaOkunamadi, match="xlsx"):
        oku(tmp_path / "eski.xls")
    (tmp_path / "bos.csv").write_bytes(b"\r\n\r\n")
    with pytest.raises(DosyaOkunamadi, match="boş"):
        oku(tmp_path / "bos.csv")
    (tmp_path / "bozuk.xlsx").write_bytes(b"bu bir excel degil")
    with pytest.raises(DosyaOkunamadi):
        oku(tmp_path / "bozuk.xlsx")


def test_otomatik_esleme():
    esleme = al.otomatik_esle(["ÜRÜN ADI", "barkod_no", "Fiyat", "Marka", "Maliyet",
                               "Grup", "KDV Oranı", "Toptancı", "Not"])
    assert esleme == {al.AD: 0, al.BARKOD: 1, al.SATIS: 2, al.MARKA: 3, al.ALIS: 4,
                      al.KATEGORI: 5, al.KDV: 6, al.TEDARIKCI: 7}
    assert al.otomatik_esle(["Not", "Açıklama 2"]) == {}
    assert al.otomatik_esle(["Barkod No"])[al.BARKOD] == 0


def test_barkod_hucresi_kurallari():
    assert al.barkod_hucresi("8,69E+12").hata, "bilimsel gösterim geçersiz"
    assert al.barkod_hucresi(8.5).hata
    eksik = _gtin13("001234567890")[2:]                  # Excel iki sıfırı silmiş
    hucre = al.barkod_hucresi(eksik)
    assert hucre.metin == eksik and hucre.oneri == "0" + eksik.zfill(12)
    assert al.barkod_hucresi("ABC-123").metin == "ABC123", "opak kod kabul edilir"


# ===================== Önizleme ============================================
def test_onizleme_durumlari_ve_sayilar(tmp_path, services, bira):
    services.products.set_reference_cost(bira, 4000)
    yeni = _gtin13("869000000101")
    yol = _csv(tmp_path, [
        f"{yeni};Yeni Kola 1 L;45;Soğuk İçecek > Kola;Coca-Cola;Anadolu;30;20",
        f"{BIRA_BARKOD};Tuborg Gold 50 cl Kutu;85;;;;;",          # fiyat değişti
        f"{BIRA_BARKOD};Tuborg;80;;;;;",                           # dosyada tekrar
        "8690000000777;;45;Kola;;;;",                              # ad eksik
        "8690000000778;Bozuk Fiyat;on lira;Kola;;;;",
        "8,69E+12;Bilimsel;10;Kola;;;;",
        f"{_gtin13('869000000102')};Kategorisiz;10;Bilinmeyen Raf;;;;",
    ])
    once = services.db.scalar("SELECT COUNT(*) FROM products")
    plan = _plan(services, yol)
    assert services.db.scalar("SELECT COUNT(*) FROM products") == once, "önizleme yazmaz"
    durumlar = [s.durum for s in plan.satirlar]
    assert durumlar == [ims.YENI, ims.GUNCELLE, ims.CAKISMA, ims.GECERSIZ, ims.GECERSIZ,
                        ims.GECERSIZ, ims.GECERSIZ]
    assert plan.satirlar[1].farklar == {al.SATIS: (8000, 8500)}
    assert plan.satirlar[0].alanlar[al.KATEGORI] == _kategori(services, "Kola")
    assert "kategorisi bulunamadı" in plan.satirlar[6].uyarilar[0]
    assert plan.sayilar() == {
        "toplam": 7, "yeni": 1, "eslesen": 1, "guncellenecek": 1, "ayni": 0,
        "cakisma": 1, "gecersiz_barkod": 1, "eksik_zorunlu": 2, "gecersiz_fiyat": 1,
        "gecersiz": 4, "atlanan": 0,
    }
    rapor = ims.hata_raporu_satirlari(plan)
    assert rapor[0][0] == "Satır" and len(rapor) == 1 + 5


def test_politikalar_ve_ayni_satir(tmp_path, services, bira):
    yeni = _gtin13("869000000103")
    yol = _csv(tmp_path, [f"{yeni};Yeni;10;Kola;;;;", f"{BIRA_BARKOD};;80;;;;;"])
    plan = _plan(services, yol, ims.YALNIZ_YENI)
    assert [s.durum for s in plan.satirlar] == [ims.YENI, ims.ATLANDI]
    plan = _plan(services, yol, ims.YALNIZ_GUNCELLE)
    assert [s.durum for s in plan.satirlar] == [ims.ATLANDI, ims.AYNI], \
        "boş ad karşılaştırılmaz; fiyat aynı"


def test_varsayilan_kategori_ve_belirsiz_ad(tmp_path, services):
    yol = _csv(tmp_path, [f"{_gtin13('869000000104')};Buz 2 kg;20;Diğer;;;;"])
    plan = _plan(services, yol)
    assert plan.satirlar[0].durum == ims.GECERSIZ, "'Diğer' iki yerde: belirsiz"
    varsayilan = _kategori(services, "Buz")
    plan = _plan(services, yol, varsayilan=varsayilan)
    assert plan.satirlar[0].alanlar[al.KATEGORI] == varsayilan
    yol = _csv(tmp_path, [f"{_gtin13('869000000104')};Buz 2 kg;20;Diğer > Diğer;;;;"],
               ad="yol.csv")
    plan = _plan(services, yol)
    assert plan.satirlar[0].durum == ims.YENI


def test_kaldirilmis_urunun_barkodu_cakismadir(tmp_path, services, bira):
    services.products.set_active(bira, False)
    yol = _csv(tmp_path, [f"{BIRA_BARKOD};Tuborg Yeni;90;Bira;;;;"])
    satir = _plan(services, yol).satirlar[0]
    assert satir.durum == ims.CAKISMA and "kullanımdan kaldırılmış" in satir.sorunlar[0]


def test_sifir_onerisi_yalnizca_kabulle(tmp_path, services):
    tam = _gtin13("001234567890")
    eksik = tam[2:]
    yol = _csv(tmp_path, [f"{eksik};Kısa Barkod;10;Kola;;;;"])
    satir = _plan(services, yol).satirlar[0]
    assert (satir.barkod, satir.sifir_onerisi) == (eksik, tam)
    satir = _plan(services, yol, kabul=frozenset({2})).satirlar[0]
    assert satir.barkod == tam and satir.sifir_onerisi is None


# ===================== Uygulama ============================================
def test_uygulama_tek_islem_yedek_grup_denetim(tmp_path, services, bira, isolated_data_dir):
    yeni = _gtin13("869000000105")
    yol = _csv(tmp_path, [
        f"{yeni};Yeni Gazoz;25;Gazoz;Uludağ;Anadolu Dağıtım;14,50;10",
        f"{BIRA_BARKOD};Tuborg (dosyadaki ad);85;;;;52;",
    ])
    plan = _plan(services, yol)
    sha, _ = dosya_ozeti(yol)
    sonuc = services.imports.uygula(plan, yol.name, sha)
    assert (sonuc.yeni, sonuc.guncellenen) == (1, 1)
    assert Path(sonuc.yedek_yolu).exists()
    assert Path(sonuc.yedek_yolu).name.startswith(ims.ICE_AKTARMA_YEDEK_ONEKI)
    assert str(isolated_data_dir) in sonuc.yedek_yolu, "yedek geçici veri kökünde"

    pid = services.barcodes.resolve(yeni).product_id
    urun = services.products.get(pid)
    assert (urun["name"], urun["sale_price"], urun["vat_rate"], urun["reference_cost"]) == (
        "Yeni Gazoz", 2500, 10, 1450)
    assert urun["last_purchase_cost"] is None, "alış sütunu yalnızca referans alıştır"
    assert services.suppliers.get(urun["default_supplier_id"])["name"] == "Anadolu Dağıtım"
    bira_urun = services.products.get(bira)
    assert bira_urun["sale_price"] == 8500 and bira_urun["reference_cost"] == 5200
    assert bira_urun["name"] == "Tuborg Gold 50 cl Kutu", "ad seçilmedikçe güncellenmez"

    grup = services.pricing.grup(sonuc.fiyat_grubu)
    assert (grup["kind"], grup["product_count"]) == ("ICE_AKTARMA", 1)
    denetim = services.db.query_one("SELECT * FROM audit_log WHERE action = 'ICE_AKTARMA'")
    ayrinti = json.loads(denetim["details_json"])
    assert (ayrinti["dosya"], ayrinti["sha256"]) == ("liste.csv", sha)
    assert services.db.check_invariants(deep=True) == []

    services.pricing.geri_al(sonuc.fiyat_grubu)
    assert services.products.get(bira)["sale_price"] == 8000, "fiyatlar geri alınabilir"


def test_secilen_alanlar_ve_bos_hucre(tmp_path, services, bira):
    marka = services.products.get(bira)["brand_id"]
    yol = _csv(tmp_path, [f"{BIRA_BARKOD};Tuborg Gold 50cl;80;;;;;18"])
    plan = _plan(services, yol)
    assert set(plan.satirlar[0].farklar) == {al.AD, al.KDV}
    with pytest.raises(DomainError, match="değişiklik yok"):
        services.imports.uygula(plan, "x.csv", "0" * 64)       # varsayılan: fiyatlar
    services.imports.uygula(plan, "x.csv", "0" * 64, frozenset({al.AD, al.KDV, al.MARKA}))
    urun = services.products.get(bira)
    assert (urun["name"], urun["vat_rate"]) == ("Tuborg Gold 50cl", 18)
    assert urun["brand_id"] == marka, "boş hücre üzerine yazmaz"


def test_hata_olursa_hicbiri_yazilmaz(tmp_path, services, bira, monkeypatch):
    yol = _csv(tmp_path, [
        f"{_gtin13('869000000106')};Bir;10;Kola;;;;",
        f"{_gtin13('869000000107')};İki;10;Kola;;;;",
        f"{BIRA_BARKOD};;99;;;;;",
    ])
    plan = _plan(services, yol)
    gercek = services.products.add_product
    sayac = {"n": 0}

    def ikincide_patla(taslak):
        sayac["n"] += 1
        if sayac["n"] == 2:
            raise RuntimeError("disk dolu")
        return gercek(taslak)

    monkeypatch.setattr(services.products, "add_product", ikincide_patla)
    once = services.db.scalar("SELECT COUNT(*) FROM products")
    with pytest.raises(RuntimeError):
        services.imports.uygula(plan, "x.csv", "0" * 64)
    assert services.db.scalar("SELECT COUNT(*) FROM products") == once
    assert services.products.get(bira)["sale_price"] == 8000
    assert services.db.scalar("SELECT COUNT(*) FROM price_change_batches") == 0


def test_yedek_alinamazsa_yazilmaz(tmp_path, services, monkeypatch):
    yol = _csv(tmp_path, [f"{_gtin13('869000000108')};Bir;10;Kola;;;;"])
    plan = _plan(services, yol)

    def patla(onek):
        raise YedekHatasi("disk dolu")

    monkeypatch.setattr(services.backup, "create_safety_backup", patla)
    with pytest.raises(YedekHatasi):
        services.imports.uygula(plan, "x.csv", "0" * 64)
    assert services.barcodes.resolve(_gtin13("869000000108")) is None
