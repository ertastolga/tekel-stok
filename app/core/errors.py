"""Kullanıcıya doğrudan gösterilebilen Türkçe hata sınıfları.

Kural: ``message`` dükkân sahibine gösterilir ve teknik terim İÇERMEZ.
``detail`` yalnızca log dosyasına yazılır. Ham ``sqlite3`` hataları, izler
(traceback) ve İngilizce metinler kullanıcıya ASLA ulaşmaz.
"""
from __future__ import annotations


class DomainError(Exception):
    """Mesajı doğrudan kullanıcıya gösterilebilen iş kuralı hatası."""

    def __init__(self, message: str, detail: str = "") -> None:
        super().__init__(message)
        self.message = message
        self.detail = detail


# --- Veritabanı / altyapı -------------------------------------------------
class VeritabaniHatasi(DomainError):
    def __init__(self, message: str = "", detail: str = "") -> None:
        super().__init__(
            message or "Veritabanı açılamadı. Dosya başka bir program tarafından "
            "kullanılıyor olabilir.",
            detail,
        )


class YeniSurumVeritabani(VeritabaniHatasi):
    """Veri, bu uygulamadan DAHA YENİ bir sürümle oluşturulmuş."""

    def __init__(self, detail: str = "") -> None:
        super().__init__(
            "Bu veri daha yeni bir TekelStok sürümüyle oluşturulmuş. "
            "Lütfen güncel sürümü kullanın; verileriniz değiştirilmedi.",
            detail,
        )


class GocOncesiYedekAlinamadi(VeritabaniHatasi):
    """Güncelleme öncesi zorunlu yedek alınamadı; güncelleme YAPILMADI."""

    def __init__(self, message: str, detail: str = "") -> None:
        super().__init__(message, detail)


class GocBasarisiz(VeritabaniHatasi):
    """Güncelleme yarıda kaldı ve TAMAMEN geri alındı."""

    def __init__(self, yedek_yolu: str | None = None, detail: str = "") -> None:
        ek = f" Güncelleme öncesi yedek: {yedek_yolu}" if yedek_yolu else ""
        super().__init__(
            "Veritabanı güncellenemedi. Verileriniz değiştirilmedi; önceki sürümü "
            "kullanmaya devam edebilirsiniz." + ek,
            detail,
        )
        self.yedek_yolu = yedek_yolu


class IslemTamamlanamadi(DomainError):
    """Çok adımlı bir işlem geri alındı: hiçbir veri değişmedi."""

    def __init__(self, detail: str = "") -> None:
        super().__init__(
            "İşlem tamamlanamadı. Stok ve satış bilgileri değiştirilmedi.", detail
        )


# --- Barkod ---------------------------------------------------------------
class BosBarkod(DomainError):
    def __init__(self) -> None:
        super().__init__("Barkod boş olamaz.")


class BarkodBulunamadi(DomainError):
    """Tanınmayan barkod. Satış ekranı bunu ürün tanımlama akışına çevirir."""

    def __init__(self, barkod: str = "") -> None:
        super().__init__("Ürün tanınmadı.", f"barkod={barkod}")
        self.barkod = barkod


class MukerrerBarkod(DomainError):
    def __init__(self, urun_adi: str = "", detail: str = "") -> None:
        mesaj = (
            f"Bu barkod zaten {urun_adi} ürününde kayıtlı."
            if urun_adi
            else "Bu barkod başka bir üründe kayıtlı."
        )
        super().__init__(mesaj, detail)
        self.urun_adi = urun_adi


class GecersizCarpan(DomainError):
    def __init__(self) -> None:
        super().__init__("Barkod adedi en az 1 olmalıdır.")


# --- Ürün / fiyat ---------------------------------------------------------
class GecersizFiyat(DomainError):
    def __init__(self, message: str = "") -> None:
        super().__init__(message or "Geçerli bir fiyat giriniz. Örnek: 80")


class FiyatiYokUrun(DomainError):
    """Satış fiyatı girilmemiş ürün satılamaz."""

    def __init__(self, urun_adi: str = "") -> None:
        ad = f"{urun_adi} ürününün" if urun_adi else "Bu ürünün"
        super().__init__(f"{ad} satış fiyatı girilmemiş. Önce fiyatı yazın.")


class PasifUrun(DomainError):
    def __init__(self, urun_adi: str = "") -> None:
        ad = urun_adi or "Bu ürün"
        super().__init__(f"{ad} kullanımdan kaldırılmış. Satılamaz.")


class GecersizUrunAdi(DomainError):
    def __init__(self) -> None:
        super().__init__("Ürün adı boş olamaz.")


class DesteklenmeyenOlcuTuru(DomainError):
    """V1 yalnızca tam sayı adet/paket ürünleri destekler."""

    def __init__(self, detail: str = "") -> None:
        super().__init__(
            "Bu sürüm yalnızca adetle satılan ürünleri destekler.", detail
        )


class GecersizMiktar(DomainError):
    def __init__(self, message: str = "") -> None:
        super().__init__(message or "Geçerli bir adet giriniz.")


# --- Satış / geri alma ----------------------------------------------------
class SatisBulunamadi(DomainError):
    def __init__(self) -> None:
        super().__init__("Geri alınacak satış bulunamadı.")


class ZatenGeriAlinmis(DomainError):
    def __init__(self) -> None:
        super().__init__("Bu satış daha önce geri alınmış.")


class BosSepet(DomainError):
    def __init__(self) -> None:
        super().__init__("Sepet boş. Önce ürün okutun.")


class FiyatDegisti(DomainError):
    """Sepetteki bir ürünün fiyatı sepete eklendikten SONRA değişti.

    Ekranda görünen, ödemesi alınan ve kaydedilen tutar AYNI olmalıdır; bu
    yüzden satış yazılmaz ve kullanıcıdan açık bir karar beklenir.
    """

    def __init__(self, sorunlar: list | None = None) -> None:
        super().__init__(
            "Sepetteki bazı ürünlerin fiyatı değişti. Güncel fiyatları uygulayın "
            "ya da ürünü sepetten çıkarın.",
            "; ".join(getattr(s, "message", str(s)) for s in (sorunlar or [])),
        )
        self.sorunlar = list(sorunlar or [])


class EskiOturumSepeti(DomainError):
    """Sepet, veritabanı yeniden açılmadan (ör. yedek geri yüklenmeden) önceye ait."""

    def __init__(self) -> None:
        super().__init__(
            "Bu sepet, geri yüklenen veriden önceye ait olduğu için kaydedilmedi."
        )


# --- Alış / stok ----------------------------------------------------------
class FisBulunamadi(DomainError):
    def __init__(self) -> None:
        super().__init__("Stok girişi bulunamadı.")


class FisZatenTamamlanmis(DomainError):
    def __init__(self) -> None:
        super().__init__("Bu stok girişi zaten tamamlanmış.")


class BosFis(DomainError):
    def __init__(self) -> None:
        super().__init__("Stok girişinde hiç ürün yok. Önce ürün okutun.")


class GeriAlmaKanitlanamaz(DomainError):
    """Fişten sonra başka hareket olmuşsa otomatik geri alma yapılmaz.

    Sebebi maliyet doğruluğudur: araya giren satış ve alışlardan sonra eski bir
    fişi geri almak ortalama maliyeti bozar. Kullanıcıya "Düzeltme Girişi"
    önerilir.
    """

    def __init__(self, urun_adlari: list[str] | None = None) -> None:
        adlar = urun_adlari or []
        liste = ", ".join(adlar[:3])
        if len(adlar) > 3:
            liste += f" ve {len(adlar) - 3} ürün daha"
        mesaj = "Bu stok girişi geri alınamıyor: bu ürünlerden sonra işlem yapılmış."
        if liste:
            mesaj = (
                "Bu stok girişi geri alınamıyor. Şu ürünlerden sonra satış veya "
                f"giriş yapılmış: {liste}."
            )
        super().__init__(mesaj)
        self.urun_adlari = adlar


class FisGeriAlinamaz(DomainError):
    """Fiş yapısı gereği geri alınamaz (taslak, ters fiş, zaten geri alınmış)."""

    def __init__(self, message: str) -> None:
        super().__init__(message)


# --- Sayım ----------------------------------------------------------------
class SayimBulunamadi(DomainError):
    def __init__(self) -> None:
        super().__init__("Sayım bulunamadı.")


class SayimZatenTamamlanmis(DomainError):
    def __init__(self) -> None:
        super().__init__("Bu sayım zaten tamamlanmış.")


class AcikSayimVar(DomainError):
    def __init__(self) -> None:
        super().__init__(
            "Tamamlanmamış bir sayım var. Önce onu bitirin ya da iptal edin."
        )


# --- Yedekleme ------------------------------------------------------------
class YedekHatasi(DomainError):
    def __init__(self, message: str = "", detail: str = "") -> None:
        super().__init__(message or "Yedekleme işlemi tamamlanamadı.", detail)


class YedekOkunamadi(DomainError):
    def __init__(self, detail: str = "") -> None:
        super().__init__(
            "Seçilen dosya geçerli bir yedek değil ya da bozulmuş.", detail
        )
