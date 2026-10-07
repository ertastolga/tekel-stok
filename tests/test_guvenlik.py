"""Yönetici PIN'i servisi (V1.2 M2c).

Korunan sözler:
  * PIN isteğe bağlıdır; kurulmadan hiçbir ``guvenlik_*`` kaydı yoktur,
  * PIN scrypt ile tuzlanıp saklanır; düz PIN hiçbir yere yazılmaz (denetim dahil),
  * 5 hatalı deneme → 1 dk kilit, her kilitte iki katı, en çok 30 dk; kilitliyken
    deneme sayılmaz; kilit yeniden başlatmaya dayanır ama saat oynatarak
    uzatılamaz,
  * kurtarma kodu bir kez verilir, aynı kilit kurallarına tabidir,
  * son çare sıfırlama: onay metni → ZORUNLU yedek → PIN silinir → kalıcı
    bildirim; bildirim yeni PIN + yeni kod kurulup onaylanana dek kalkmaz.
"""
from __future__ import annotations

import re

import pytest

from app.core.errors import DomainError, YedekHatasi
from app.services import security_service as g
from app.services.security_service import GecersizPin, SecurityService

GECERLI = "4826"


def _ayarlar(services) -> dict[str, str]:
    return {
        r["key"]: r["value"]
        for r in services.db.query("SELECT key, value FROM settings WHERE key LIKE 'guvenlik%'")
    }


def test_varsayilan_pin_yok_ve_iz_yok(services):
    assert not services.security.has_pin()
    assert _ayarlar(services) == {}
    assert services.security.lock_remaining() == 0


@pytest.mark.parametrize(
    "pin", ["123", "123456789", "12a4", "1111", "1234", "4321", "98765", "2580", ""]
)
def test_kolay_ya_da_gecersiz_pin_reddedilir(services, pin):
    with pytest.raises(GecersizPin):
        services.security.set_pin(pin)
    assert not services.security.has_pin()


@pytest.mark.parametrize("pin", ["4826", "73915", "90817263"])
def test_gecerli_pin_kurulur(services, pin):
    kod = services.security.set_pin(pin)
    assert re.fullmatch(r"\d{4}-\d{4}-\d{4}", kod)
    assert services.security.verify(pin).dogru


def test_pin_ozetle_saklanir_duz_pin_hicbir_yerde_yok(services):
    kod = services.security.set_pin(GECERLI)
    kayit = services.settings.get(g.PIN_HASH)
    assert kayit.startswith("scrypt$16384$8$1$")
    assert GECERLI not in kayit
    _, _, _, _, tuz, ozet = kayit.split("$")
    assert len(bytes.fromhex(tuz)) == 16 and len(bytes.fromhex(ozet)) == 32
    rakam = kod.replace("-", "")
    for satir in services.db.query("SELECT summary_tr, details_json FROM audit_log"):
        metin = f"{satir['summary_tr']} {satir['details_json']}"
        assert GECERLI not in metin and rakam not in metin and "scrypt$" not in metin
    # Aynı PIN iki kez kurulsa da özet farklıdır (rastgele tuz).
    services.security.set_pin(GECERLI)
    assert services.settings.get(g.PIN_HASH) != kayit


def test_hatali_denemeler_kilitler_ve_kilit_ikiye_katlanir(duvar_saati, services):
    guv = services.security
    guv.set_pin(GECERLI)
    for kalan in (4, 3, 2, 1):
        sonuc = guv.verify("0000")
        assert not sonuc.dogru and sonuc.kalan_deneme == kalan
        assert f"{kalan} deneme" in sonuc.mesaj
    sonuc = guv.verify("0000")
    assert sonuc.kilitli and sonuc.kilit_sn == 60

    kilitli = guv.verify(GECERLI)                       # doğru PIN bile
    assert not kilitli.dogru and kilitli.kilitli, "kilitliyken denetlenmez"
    assert services.settings.get_int(g.HATALI_DENEME) == 0, "deneme sayılmadı"

    duvar_saati.ilerle(61)
    assert guv.lock_remaining() == 0
    for _ in range(5):
        guv.verify("0000")
    assert guv.lock_remaining() == 120, "ikinci kilit iki katı"
    duvar_saati.ilerle(121)
    assert guv.verify(GECERLI).dogru
    assert services.settings.get_int(g.KILIT_SEVIYESI) == 0, "başarı sıfırlar"


def test_kilit_otuz_dakikayi_asmaz(duvar_saati, services):
    guv = services.security
    guv.set_pin(GECERLI)
    for tur in range(8):
        for _ in range(5):
            guv.verify("0000")
        assert guv.lock_remaining() <= g.AZAMI_KILIT_SN
        duvar_saati.ilerle(guv.lock_remaining() + 1)
    assert services.settings.get_int(g.KILIT_SEVIYESI) == 8


def test_kilit_yeniden_baslatmaya_dayanir_ama_saatle_uzatilamaz(
    duvar_saati, services, reopen
):
    services.security.set_pin(GECERLI)
    for _ in range(5):
        services.security.verify("0000")
    yeni = reopen(services)
    try:
        assert 0 < yeni.security.lock_remaining() <= 60
        assert not yeni.security.verify(GECERLI).dogru
        yeni.settings.set_many_quiet({g.KILIT_BITIS_UTC: 10**10})   # oynanmış kayıt
        taze = SecurityService(yeni.db, yeni.settings, yeni.audit)
        assert taze.lock_remaining() <= g.AZAMI_KILIT_SN
    finally:
        yeni.close()


def test_kurtarma_kodu_dogrular_ve_kilit_kurallarina_tabidir(services):
    kod = services.security.set_pin(GECERLI)
    assert services.security.verify_recovery(kod).dogru
    assert services.security.verify_recovery(kod.replace("-", "")).dogru
    for _ in range(5):
        services.security.verify_recovery("0000-0000-0000")
    assert services.security.lock_remaining() > 0
    assert not services.security.verify_recovery(kod).dogru


def test_pin_degisince_eski_pin_ve_kod_gecersiz(services):
    eski_kod = services.security.set_pin(GECERLI)
    services.security.set_pin("73915")
    assert not services.security.verify(GECERLI).dogru
    assert not services.security.verify_recovery(eski_kod).dogru
    assert services.security.verify("73915").dogru
    eylemler = [r["action"] for r in services.audit.recent()]
    assert "PIN_KURULDU" in eylemler and "PIN_DEGISTI" in eylemler


# ===================== Son çare sıfırlama ==================================
def test_sifirlama_yanlis_onayla_hicbir_sey_yapmaz(services):
    services.security.set_pin(GECERLI)
    with pytest.raises(DomainError):
        services.security.reset_with_backup(services.backup, "evet")
    assert services.security.has_pin()
    assert not services.security.reset_notice_active()
    assert not list(services.backup.manual_dir().glob("pin_sifirlama_oncesi_*"))


def test_sifirlama_yedek_alinamazsa_pin_degismez(services, monkeypatch):
    services.security.set_pin(GECERLI)

    def patla(prefix):
        raise YedekHatasi("Yedek alınamadı.")

    monkeypatch.setattr(services.backup, "create_safety_backup", patla)
    with pytest.raises(YedekHatasi):
        services.security.reset_with_backup(services.backup, "SIFIRLA")
    assert services.security.verify(GECERLI).dogru
    assert not services.security.reset_notice_active()


def test_sifirlama_yedekler_siler_ve_kalici_bildirim_acar(services, reopen):
    services.security.set_pin(GECERLI)
    yol = services.security.reset_with_backup(services.backup, " sıfırla ")
    assert yol.exists() and yol.name.startswith("pin_sifirlama_oncesi_")
    assert yol.parent == services.backup.manual_dir()
    assert not services.security.has_pin()
    assert services.security.reset_notice_active()
    assert not services.security.reset_notice_ackable()
    assert not services.security.acknowledge_reset_notice()
    satir = services.db.query_one(
        "SELECT actor FROM audit_log WHERE action = 'PIN_SIFIRLANDI'"
    )
    assert satir["actor"] == "SYSTEM"

    yeni = reopen(services)                              # yeniden başlatma
    try:
        assert yeni.security.reset_notice_active(), "bildirim kalıcı"
        yeni.security.set_pin("73915")
        assert yeni.security.reset_notice_ackable()
        assert yeni.security.acknowledge_reset_notice()
        assert not yeni.security.reset_notice_active()
    finally:
        yeni.close()


def test_korunan_eylemlerin_turkce_etiketi_var():
    adlar = [v for k, v in vars(g.ProtectedAction).items() if k.isupper() and k != "ETIKETLER"]
    assert len(adlar) == 10
    assert set(adlar) == set(g.ProtectedAction.ETIKETLER)
