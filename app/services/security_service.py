"""Yönetici PIN'i: isteğe bağlı, yerel, kazara değişikliklere karşı koruma.

Tehdit modeli (README ve Ayarlar > Güvenlik'te sade Türkçeyle anlatılır)
-----------------------------------------------------------------------
* AMAÇ: dükkânda kasaya geçen birinin ayarları, toplu fiyatları, geçmiş
  satışları vb. KAZARA ya da gelişigüzel değiştirmesini önlemek.
* Windows hesabına ya da veri dosyasına erişebilen birine karşı bir savunma
  DEĞİLDİR. Yedekler PIN'in özetini (hash) içerir; eski bir yedeği geri
  yüklemek o yedeğin PIN durumunu geri getirir.
* Satış, Kasa'da aynı iş gününün son satışını geri alma, sepet bekletme, fiyat
  görme, arama, hızlı ürün ekleme ve gezinme ASLA PIN istemez.

Saklama: ``scrypt(n=2**14, r=8, p=1, dklen=32)``, 16 baytlık rastgele tuz,
``scrypt$16384$8$1$<tuz>$<özet>`` biçiminde ``guvenlik_pin_hash`` ayarında.
Karşılaştırma ``hmac.compare_digest`` ile yapılır. Tüm ``guvenlik_*`` ayarları
destek paketinden ÇIKARILIR (M10d).

Kilit: art arda 5 hatalı deneme → 1 dk; sonraki her kilit iki katı, en çok
30 dk. Kilitliyken deneme SAYILMAZ ve PIN hiç denetlenmez. Kalan süre tekdüze
saatle ölçülür (saat dikişi); kalıcı kayıt duvar saatiyle tutulur ama hiçbir
zaman 30 dakikadan uzun bir kilit üretemez (saat oynatma kilidi uzatamaz).
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
from dataclasses import dataclass

from app.core.clock import monotonic, now_utc
from app.core.errors import DomainError

log = logging.getLogger(__name__)

# --- Ayar anahtarları (iç; Ayarlar ekranında görünmez) -------------------
PIN_HASH = "guvenlik_pin_hash"
KURTARMA_HASH = "guvenlik_kurtarma_hash"
HATALI_DENEME = "guvenlik_hatali_deneme"
KILIT_SEVIYESI = "guvenlik_kilit_seviyesi"
KILIT_BITIS_UTC = "guvenlik_kilit_bitis_utc"
SIFIRLAMA_BILDIRIMI = "guvenlik_sifirlama_bildirimi"
SIFIRLAMA_UTC = "guvenlik_sifirlama_utc"
SIFIRLAMA_SONRASI_KURULDU = "guvenlik_sifirlama_sonrasi_kuruldu"
ANAHTAR_ONEKI = "guvenlik_"

#: ``--yonetici-pin-sifirla`` onay metni.
ONAY_METNI = "SIFIRLA"

AZAMI_DENEME = 5
ILK_KILIT_SN = 60
AZAMI_KILIT_SN = 30 * 60

PIN_EN_KISA = 4
PIN_EN_UZUN = 8
KURTARMA_HANE = 12

_SCRYPT_N = 2 ** 14
_SCRYPT_R = 8
_SCRYPT_P = 1
_SCRYPT_UZUNLUK = 32

#: Tahmini kolay PIN'ler (sıralı ve tek rakamlı olanlar ayrıca reddedilir).
_KOLAY = frozenset({
    "1212", "2121", "1122", "2580", "0852", "1004", "2000", "6969", "0101",
    "1010", "1313", "4545", "123123", "112233", "121212",
})


class ProtectedAction:
    """PIN isteyebilen eylemler (Türkçe tanımlayıcılar)."""

    AYARLAR = "AYARLAR"
    GERI_YUKLE = "GERI_YUKLE"
    TOPLU_FIYAT = "TOPLU_FIYAT"
    ICE_AKTAR = "ICE_AKTAR"
    URUN_PASIF = "URUN_PASIF"
    KATEGORI_PASIF_BIRLESTIR = "KATEGORI_PASIF_BIRLESTIR"
    GECMIS_SATIS_GERI_AL = "GECMIS_SATIS_GERI_AL"
    FIS_GERI_AL = "FIS_GERI_AL"
    STOK_YENIDEN_HESAPLA = "STOK_YENIDEN_HESAPLA"
    PIN_DEGISTIR = "PIN_DEGISTIR"

    ETIKETLER = {
        AYARLAR: "Ayarlar",
        GERI_YUKLE: "Yedekten geri yükleme",
        TOPLU_FIYAT: "Toplu fiyat değişikliği",
        ICE_AKTAR: "Ürün içe aktarma",
        URUN_PASIF: "Ürünü kullanımdan kaldırma",
        KATEGORI_PASIF_BIRLESTIR: "Kategori kaldırma / birleştirme",
        GECMIS_SATIS_GERI_AL: "Geçmiş satışı geri alma",
        FIS_GERI_AL: "Stok girişini geri alma",
        STOK_YENIDEN_HESAPLA: "Stok bilgisini yeniden hesaplama",
        PIN_DEGISTIR: "Yönetici PIN'ini değiştirme",
    }


class GecersizPin(DomainError):
    """Yeni PIN kurallara uymuyor."""


@dataclass(frozen=True, slots=True)
class PinSonucu:
    dogru: bool
    kalan_deneme: int = AZAMI_DENEME
    kilit_sn: int = 0

    @property
    def kilitli(self) -> bool:
        return self.kilit_sn > 0

    @property
    def mesaj(self) -> str:
        if self.dogru:
            return ""
        if self.kilitli:
            dakika, saniye = divmod(self.kilit_sn, 60)
            sure = f"{dakika} dk {saniye} sn" if dakika else f"{saniye} sn"
            return f"Çok fazla hatalı deneme. {sure} sonra tekrar deneyin."
        return f"Hatalı PIN. {self.kalan_deneme} deneme hakkınız kaldı."


def _ozet(sir: str, tuz: bytes | None = None) -> str:
    tuz = tuz or secrets.token_bytes(16)
    deger = hashlib.scrypt(
        sir.encode("utf-8"), salt=tuz, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P,
        dklen=_SCRYPT_UZUNLUK, maxmem=64 * 1024 * 1024,
    )
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${tuz.hex()}${deger.hex()}"


def _ozet_dogru(sir: str, kayit: str) -> bool:
    try:
        tur, n, r, p, tuz_hex, ozet_hex = kayit.split("$")
        if tur != "scrypt":
            return False
        beklenen = bytes.fromhex(ozet_hex)
        deger = hashlib.scrypt(
            sir.encode("utf-8"), salt=bytes.fromhex(tuz_hex), n=int(n), r=int(r),
            p=int(p), dklen=len(beklenen), maxmem=64 * 1024 * 1024,
        )
    except (ValueError, TypeError):
        log.warning("PIN kaydı okunamadı (biçim bozuk)")
        return False
    return hmac.compare_digest(deger, beklenen)


def pin_kurallari(pin: str) -> None:
    """Yeni PIN'i denetler; uymuyorsa ``GecersizPin``."""
    if not pin.isdigit() or not PIN_EN_KISA <= len(pin) <= PIN_EN_UZUN:
        raise GecersizPin(f"PIN {PIN_EN_KISA}–{PIN_EN_UZUN} haneli bir sayı olmalı.")
    if len(set(pin)) == 1:
        raise GecersizPin("Aynı rakamın tekrarı tahmin edilmesi kolay bir PIN'dir.")
    farklar = {int(b) - int(a) for a, b in zip(pin, pin[1:])}
    if farklar in ({1}, {-1}):
        raise GecersizPin("Sıralı rakamlar (1234 gibi) tahmin edilmesi kolay bir PIN'dir.")
    if pin in _KOLAY:
        raise GecersizPin("Bu PIN çok yaygın; lütfen başka bir PIN seçin.")


def kurtarma_kodu_bicimle(kod: str) -> str:
    rakam = "".join(ch for ch in kod if ch.isdigit())
    return "-".join(rakam[i:i + 4] for i in range(0, len(rakam), 4))


class SecurityService:
    def __init__(self, db, settings, audit) -> None:
        self.db = db
        self.settings = settings
        self.audit = audit
        #: Süreç içi kilit bitişi (tekdüze saat). ``None`` = kalıcı kayda bak.
        self._kilit_tekduze: float | None = None

    # ===================== Durum ========================================
    def has_pin(self) -> bool:
        return bool(self.settings.get(PIN_HASH, ""))

    def reset_notice_active(self) -> bool:
        return self.settings.get_bool(SIFIRLAMA_BILDIRIMI, False)

    def reset_notice_ackable(self) -> bool:
        """Bildirim ancak YENİ PIN ve YENİ kurtarma kodu kurulduktan sonra kapanır."""
        return (
            self.reset_notice_active()
            and self.has_pin()
            and self.settings.get_bool(SIFIRLAMA_SONRASI_KURULDU, False)
        )

    def reset_time_utc(self) -> int:
        return self.settings.get_int(SIFIRLAMA_UTC, 0)

    # ===================== PIN kurma / değiştirme ========================
    def set_pin(self, new_pin: str) -> str:
        """PIN'i kurar ya da değiştirir; YENİ kurtarma kodunu (bir kez) döner.

        Yetki çağıranın sorumluluğundadır (arayüz değiştirme için önce
        ``PIN_DEGISTIR`` korumasından geçer).
        """
        pin_kurallari(new_pin)
        kod = "".join(secrets.choice("0123456789") for _ in range(KURTARMA_HANE))
        degerler = {
            PIN_HASH: _ozet(new_pin),
            KURTARMA_HASH: _ozet(kod),
            HATALI_DENEME: 0,
            KILIT_SEVIYESI: 0,
            KILIT_BITIS_UTC: 0,
        }
        if self.reset_notice_active():
            degerler[SIFIRLAMA_SONRASI_KURULDU] = 1
        ilk = not self.has_pin()
        self.settings.set_many(degerler)
        self._kilit_tekduze = None
        self.audit.record(
            "PIN_KURULDU" if ilk else "PIN_DEGISTI",
            "Yönetici PIN'i kuruldu." if ilk else "Yönetici PIN'i değiştirildi.",
        )
        return kurtarma_kodu_bicimle(kod)

    def remove_pin(self) -> None:
        """PIN korumasını kapatır (yetki çağıranda)."""
        self.settings.set_many({PIN_HASH: "", KURTARMA_HASH: "", HATALI_DENEME: 0,
                                KILIT_SEVIYESI: 0, KILIT_BITIS_UTC: 0})
        self._kilit_tekduze = None
        self.audit.record("PIN_KALDIRILDI", "Yönetici PIN'i kaldırıldı.")

    # ===================== Doğrulama =====================================
    def lock_remaining(self) -> int:
        """Kilidin kalan süresi (sn); kilit yoksa 0."""
        if self._kilit_tekduze is None:
            bitis = self.settings.get_int(KILIT_BITIS_UTC, 0)
            kalan = min(bitis - now_utc(), AZAMI_KILIT_SN)
            if kalan <= 0:
                return 0
            self._kilit_tekduze = monotonic() + kalan
        kalan_f = self._kilit_tekduze - monotonic()
        if kalan_f <= 0:
            return 0
        return int(kalan_f + 0.999)

    def verify(self, pin: str) -> PinSonucu:
        return self._dene(pin, PIN_HASH)

    def verify_recovery(self, code: str) -> PinSonucu:
        rakam = "".join(ch for ch in code if ch.isdigit())
        return self._dene(rakam, KURTARMA_HASH)

    def _dene(self, sir: str, anahtar: str) -> PinSonucu:
        kalan = self.lock_remaining()
        if kalan:
            return PinSonucu(False, 0, kalan)
        kayit = self.settings.get(anahtar, "")
        if kayit and sir and _ozet_dogru(sir, kayit):
            self.settings.set_many_quiet({HATALI_DENEME: 0, KILIT_SEVIYESI: 0,
                                          KILIT_BITIS_UTC: 0})
            self._kilit_tekduze = None
            return PinSonucu(True)
        hatali = self.settings.get_int(HATALI_DENEME, 0) + 1
        if hatali < AZAMI_DENEME:
            self.settings.set_many_quiet({HATALI_DENEME: hatali})
            return PinSonucu(False, AZAMI_DENEME - hatali)
        seviye = self.settings.get_int(KILIT_SEVIYESI, 0) + 1
        sure = min(ILK_KILIT_SN * 2 ** (seviye - 1), AZAMI_KILIT_SN)
        self.settings.set_many_quiet({
            HATALI_DENEME: 0, KILIT_SEVIYESI: seviye, KILIT_BITIS_UTC: now_utc() + sure,
        })
        self._kilit_tekduze = monotonic() + sure
        log.warning("Yönetici PIN'i %s sn kilitlendi (seviye %s)", sure, seviye)
        return PinSonucu(False, 0, sure)

    # ===================== Sıfırlama (son çare) ==========================
    def clear_pin_for_reset(self) -> None:
        """``--yonetici-pin-sifirla``: PIN'i siler, KALICI bildirimi açar.

        Bildirim; yeni PIN ve yeni kurtarma kodu kurulup sahibi onaylayana dek
        her Yönetim sayfasında, Ana Ekran'da ve Sistem Durumu'nda görünür.
        """
        self.settings.set_many({
            PIN_HASH: "", KURTARMA_HASH: "", HATALI_DENEME: 0, KILIT_SEVIYESI: 0,
            KILIT_BITIS_UTC: 0, SIFIRLAMA_BILDIRIMI: 1, SIFIRLAMA_UTC: now_utc(),
            SIFIRLAMA_SONRASI_KURULDU: 0,
        })
        self._kilit_tekduze = None
        from app.services.audit_service import Actor

        self.audit.record(
            "PIN_SIFIRLANDI",
            "Yönetici PIN'i başlangıç seçeneğiyle sıfırlandı (--yonetici-pin-sifirla).",
            actor=Actor.SYSTEM,
        )

    def reset_with_backup(self, backup, confirmation: str):
        """Son çare sıfırlama: onay metni → ZORUNLU yedek → PIN silinir.

        Yedek alınamazsa (``YedekHatasi``) PIN'e DOKUNULMAZ.
        """
        from app import config
        from app.core.tr import tr_upper

        if tr_upper((confirmation or "").strip()) != ONAY_METNI:
            raise DomainError(f"Onay için {ONAY_METNI} yazılmadı. PIN sıfırlanmadı.")
        yol = backup.create_safety_backup(config.PRE_PIN_RESET_PREFIX)
        self.clear_pin_for_reset()
        log.warning("Yönetici PIN'i sıfırlandı; güvenlik yedeği: %s", yol)
        return yol

    def acknowledge_reset_notice(self) -> bool:
        if not self.reset_notice_ackable():
            return False
        self.settings.set_many({SIFIRLAMA_BILDIRIMI: 0, SIFIRLAMA_SONRASI_KURULDU: 0})
        self.audit.record(
            "PIN_SIFIRLAMA_ONAYLANDI", "PIN sıfırlama bildirimi sahibi tarafından onaylandı."
        )
        return True
