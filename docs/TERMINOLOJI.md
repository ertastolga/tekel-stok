# TekelStok — Terimler ve yazım kuralları (V1.2)

Bu belge arayüzde kullanılan sözcükleri TEK anlamda tutmak içindir. Yeni bir
ekran, düğme ya da ileti yazılırken buradaki karşılık kullanılır; yoksa önce
buraya eklenir. Kullanıcı 55–75 yaş aralığındaki bir dükkân sahibidir: sade
Türkçe, kısa cümle, İngilizce ya da teknik sözcük yok.

## 1. Bölümler ve ekranlar

| Terim | Anlamı | Kullanılmayan |
|---|---|---|
| **KASA** | Satış ekranları grubu (Sepetli Satış, Hızlı Satış, Fiyat Gör) | POS, satış modülü |
| **STOK** | Mal girişi, sayım, stok durumu | envanter |
| **YÖNETİM** | Analiz, ürünler, fiyatlar, ayarlar, yedek, sistem | admin, yönetici paneli |
| **Ana Ekran** | Kutucuklu başlangıç ekranı | dashboard, anasayfa |
| **Sepetli Satış** | Ürünler sepete okutulur, NAKİT/KART ile tamamlanır | satış ekranı |
| **Hızlı Satış** | Her okutma anında satış | tek ürün satış |
| **Fiyat Gör** | Satış yapmadan fiyat gösterir (F11) | fiyat kontrol ekranı (yalnızca şerit metninde "FİYAT KONTROL — SATIŞ YAPILMAZ") |
| **Hızlı Stok Girişi** | Tek ürünlük, tedarikçisiz giriş | hızlı alış |
| **Mal Kabul** | Faturalı/irsaliyeli çok kalemli giriş (F3) | stok girişi (menüde), alış fişi |
| **Stok Sayımı** / **Stok Durumu** | Sayım / azalan-kritik ürünler | — |
| **Analiz** | Ciro, eğilim, ürün, sepet, ödeme, kâr sekmeleri (F7) | rapor, panel |
| **Fiyat Yönetimi** | Tek ve toplu fiyat değişikliği | fiyat merkezi |
| **Ürün İçe Aktar** | Excel/CSV listeden ürün ekleme/güncelleme | import |
| **Geçmiş** | Satış, giriş, sayım ve işlem günlüğü | log, kayıtlar |
| **Sistem Durumu** | Uygulama, veri, yedek ve cihaz durumu | sağlık, diagnostik |
| **Destek paketi** | Sorun bildirimi için tek ZIP dosyası | log paketi |

## 2. Eylemler (düğme sözcükleri)

| Sözcük | Ne zaman | Not |
|---|---|---|
| **Kaydet** | Girileni yazar, pencereyi kapatır | "Tamam" kaydetmez |
| **Vazgeç** | Hiçbir şey değişmeden çıkar | "İptal" yalnızca bir kaydı iptal etmek için (Sayımı İptal Et, Girişi İptal Et) |
| **Tamam** | Yalnızca bilgi penceresini kapatır | — |
| **Geri Al** | Ters kayıt yazar (satış, giriş, toplu fiyat). Kayıt SİLİNMEZ | "Sil" denmez |
| **Kullanımdan Kaldır** / **Yeniden Kullanıma Al** | Ürün, barkod, kategori. Geçmiş korunur. Listede durum etiketi: "(kullanımdan kaldırıldı)" | "Pasife Al", "Sil", "(pasif)" (M12b'de birleştirildi; kalan etiketler M12d'de) |
| **Beklet** / **Bekleyenler** | Sepeti kenara koy / bekleyen sepetler | park, askı |
| **Önizle** → **Uygula** | Toplu işler önce gösterilir, sonra uygulanır | — |
| **Güncel fiyatları uygula** | Sepetteki değişen fiyatı açıkça kabul | — |
| **Tamamla** | Satışı/girişi/sayımı bitirir (F10) | "Bitir" yalnızca "SAYIMI BİTİR" |

## 3. Ödeme ve durum sözcükleri

* Ödeme düğmeleri büyük harfle: **NAKİT**, **KART**. Liste ve tablolarda: **Nakit**, **Kart**,
  **Kaydedilmemiş** (ödeme seçimi eklenmeden önceki satışlar). Veresiye/Diğer gösterilmez.
* Satış durumu: **Tamam** / **Geri alındı**. Geçmiş süzgecinde: **Tamamlanan** / **Geri alınan**.
* Satış kipi: **Sepetli** / **Hızlı**.
* Maliyet: **Alış fiyatı** (gerçek alış), **Referans alış (katalog)** (listeden gelen bilgi,
  "son alış" DEĞİL), **Güvenilir maliyet** / **Tahmini maliyet** / **Maliyeti bilinmiyor**.
* Stok durumu: **Normal**, **Düşük**, **Kritik**, **Stok Kontrolü Gerekli** (eksi stok),
  **Henüz Sayılmadı**.

## 4. Biçimler

| Ne | Biçim | Örnek |
|---|---|---|
| Para | binlik nokta, kuruş virgül, sonda TL; tam liraysa kuruşsuz | 1.250 TL · 51,84 TL |
| Tarih | gün.ay.yıl | 08.10.2026 |
| Saat | 24 saat | 19:05 |
| Tarih + saat | | 08.10.2026 19:05 |
| Yüzde | işaret önde, virgül | %12,5 |
| Adet | sayı + "adet"; kalem = satır sayısı | 5 adet, 2 kalem |
| Klavye kısayolu | parantez içinde, düğme metninin sonunda | GİRİŞİ TAMAMLA (F10) |

ISO tarih (2026-10-08) arayüzde gösterilmez (M12b'de Analiz alt başlığı düzeltildi).

## 5. İleti kuralları

* **Başarı**: modal pencere AÇILMAZ; yeşil şerit ("✓ SATIŞ TAMAMLANDI").
* **Hata**: ne oldu + ne yapılacak, iki kısa cümle ("Ödeme alınmadı: sepette değişen
  ürün var." / "İşaretli satırlar için ... dokunun ya da ürünü sepetten çıkarın.").
  Teknik ayrıntı kullanıcıya değil kayıt dosyasına.
* **Boş liste**: her boş liste NEDENİNİ ve ne yapılacağını söyler ("Bu süzgeçle satış yok —
  Dönemi ya da süzgeçleri değiştirip yeniden bakın."). Açıklamasız boş tablo yoktur.
* **Uzun süren işlem** (yedek, denetim, geri yükleme): kum saati imleci.
* **Yıkıcı eylem**: kırmızı (`danger`) düğme, satırın SAĞINDA ve diğerlerinden ayrı; onay
  penceresi neyin değişeceğini ve geri dönüş yolunu söyler. Satış onayı ASLA kırmızı değildir.
* Renk tek başına anlam taşımaz: durum her zaman yazıyla da söylenir.

## 6. Dokunma ve yerleşim

* Kasa'daki her düğme en az **56 px**; NAKİT/KART en az **88 px**.
* Kasa ekranları kaydırılmaz, sayfa başlığı yoktur; 1000×600'de en az iki sepet satırı görünür.
* YÖNETİM/STOK sayfaları sığmazsa kaydırılır (üst üste binmez); süzgeç ve düğme dizileri dar
  pencerede alt satıra iner (yatay kaydırma yok).
