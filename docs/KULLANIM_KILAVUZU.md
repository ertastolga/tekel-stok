# Tekel Stok

Küçük bir tekel bayi için **barkodlu satış, stok, fiyat ve analiz** uygulaması.
Tamamen Türkçe, tamamen çevrimdışı, Windows masaüstü. Dokunmatik kasa
(ör. AVAPOS) ve normal bilgisayarda çalışır.

İnternet **gerekmez**. Veriler bilgisayarınızdan **dışarı çıkmaz**. Kurulum
gerektirmez.

Sürüm: **1.2.0b1** (V1.2 deneme sürümü).

---

## 1. Kurulum

1. `TekelStok-1.2.0b1_tasinabilir.zip` dosyasını bir klasöre çıkarın
   (örneğin `C:\TekelStok-1.2`).
2. İçindeki **`TekelStok.exe`** dosyasına çift tıklayın.
3. İsterseniz masaüstüne kısayol oluşturun: sağ tık → *Kısayol oluştur*.

Uygulama ilk açılışta gerekli her şeyi kendisi hazırlar. Yeni kurulumda hazır
bir kategori ağacı gelir (Alkollü İçecekler, Tütün, Soğuk İçecek, Atıştırmalık,
Diğer ve alt kategorileri).

> Uygulama zaten açıkken ikinci kez çalıştırırsanız yeni pencere açılmaz;
> açık pencere öne gelir. Böylece aynı veriye iki yerden yazılmaz.

---

## 2. V1.1'den V1.2'ye geçiş

V1.2, V1.1'in verisini **olduğu gibi** kullanır. Satışlarınız, ürünleriniz,
stoklarınız ve ayarlarınız korunur.

1. **V1.1'i kapatın.**
2. V1.2'yi **ayrı bir klasöre** çıkarın. V1.1 klasörünü silmeyin; geri dönmek
   isterseniz gerekecek.
3. V1.2'yi açın. İlk açılışta veriler yeni sürüme uyarlanır (birkaç saniye).

Uyarlamadan **önce** verinizin tam bir kopyası kendiliğinden alınır:

```
%LOCALAPPDATA%\TekelStok\backups\guncelleme_oncesi_v1_v6_<tarih>_<saat>.db
```

Bu kopya **asla kendiliğinden silinmez**. Diskte yer yoksa ya da kopya
alınamıyorsa uyarlama hiç yapılmaz; ekranda nedeni yazar ve verileriniz
değişmeden kalır.

### Önceki sürüme geri dönmek

> **V1.1'i, V1.2'nin açtığı veriyle ÇALIŞTIRMAYIN.** V1.1 yeni veri biçimini
> tanımaz ve bunu fark edemez.

Geri dönmek gerekirse:

1. V1.2'yi kapatın.
2. Komut satırından, **V1.2'nin** exe'siyle:

   ```
   TekelStok.exe --surum-geri-donus "%LOCALAPPDATA%\TekelStok\backups\guncelleme_oncesi_v1_v6_<tarih>_<saat>.db"
   ```

3. Onay penceresine "Evet" deyin. Mevcut veri önce
   `backups\geri_donus_oncesi_<tarih>.db` olarak saklanır, sonra güncelleme
   öncesi kopya yerine konur. Seçtiğiniz yedek dosyası değiştirilmez.
4. **Şimdi V1.1'i başlatın.**

Bilinmesi gereken: geri dönüşte **V1.2'ye geçtikten sonra yapılan satış ve
stok kayıtları V1.1 verisinde yoktur** (V1.1, güncelleme anındaki hâline
döner). Bu kayıtlar `geri_donus_oncesi_` kopyasında durur.

---

## 3. Ekran düzeni

Sol menüde üç bölüm vardır. Başlığa dokunarak bir bölümü açıp kapatabilirsiniz.

| Bölüm | Ekranlar |
|---|---|
| 🏠 **Ana Ekran** | Büyük kutucuklarla tüm ekranlara geçiş (`Ctrl+H`) |
| **KASA** | 🛒 Sepetli Satış (F2) · ⚡ Hızlı Satış (F1) · 🏷 Fiyat Gör (F11) |
| **STOK** | 📥 Hızlı Stok Girişi · 📦 Mal Kabul (F3) · 📋 Stok Sayımı (F9) · 📈 Stok Durumu |
| **YÖNETİM** | 📊 Analiz (F7) · 🏷️ Ürünler (F6) · 🗂 Kategoriler · 💲 Fiyat Yönetimi · 📄 Ürün İçe Aktar · 🚚 Tedarikçiler · 🕘 Geçmiş · ⚙️ Ayarlar · 🩺 Sistem Durumu · 🔎 Barkod Testi (F12) |

**KASA** ekranları bilerek sade tutulur: kaydırma yoktur, her düğme
parmakla rahat dokunulacak büyüklüktedir ve kasada hiçbir şey PIN sormaz.
**STOK** ve **YÖNETİM** ekranları daha ayrıntılıdır; pencereye sığmazsa
aşağı kaydırılır.

### Çalışma kipi

**Ayarlar → Kasa**'dan seçilir.

| Kip | Ne yapar |
|---|---|
| **Satış Önceliği** *(varsayılan)* | Uygulama doğrudan **Sepetli Satış**'a açılır. Stok bilgisi eksik ya da eksi olsa bile satış durmaz, kasada stok uyarısı çıkmaz. STOK bölümü menüde kapalı başlar. |
| **Stok Takibi** | Uygulama Ana Ekran'a açılır, satıştan sonra stok uyarıları görünür, Analiz'de kâr ve stok değeri öne çıkar. |

Kip yalnızca **ekranları ve uyarıları** değiştirir. Stok hareketleri,
maliyetler ve geçmiş her iki kipte de aynı tutulur; istediğiniz zaman
değiştirebilirsiniz. Açılış ekranı ayrıca **Ayarlar → Kasa → Uygulama açılınca
gelen ekran** ile seçilebilir. Kart kullanmıyorsanız KART düğmesi aynı yerden
gizlenebilir; NAKİT her zaman görünür.

---

## 4. KASA

### 🛒 Sepetli Satış (F2) — ana kasa ekranı

**Akış:** barkodu okut → sepet dolar → **NAKİT** ya da **KART**'a dokun → bitti.

- Aynı ürünü tekrar okutmak yeni satır açmaz, **adedi artırır**.
- Her satırda büyük **−**, **+** ve **✕** düğmeleri vardır.
- Sepetteyken hiçbir şey satılmış sayılmaz; stok ve ciro değişmez.
- NAKİT/KART'a tek dokunuş yeterlidir. İki kez dokunmak ikinci satış yazmaz.
- Satıştan sonra yeşil **✓ SATIŞ TAMAMLANDI** şeridi görünür ve ekran bir
  sonraki müşteriye hazırdır. Başarı için ayrıca pencere açılmaz.
- Uygulama ya da bilgisayar beklenmedik şekilde kapanırsa açık sepet
  kaybolmaz; bir dahaki açılışta geri gelir.

Üstteki araç çubuğu:

| Düğme | Ne yapar |
|---|---|
| **Ürün Ara** (`Ctrl+F`) | Barkodu okunmayan ürünü addan, markadan ya da barkodun bir kısmından bulur; dokununca sepete 1 adet ekler. Arama açıkken okutma yine sepete gider. |
| **Beklet** | Sepeti kenara koyar ("Müşteri 2 · 14:32"); kasa sıradaki müşteriye boşalır. En fazla 9 sepet bekletilebilir. |
| **Bekleyenler (n)** | Bekleyen sepetleri gösterir: **Aç** ya da **Sil**. Açarken elinizde dolu bir sepet varsa onu da bekletmeyi önerir. |
| **Fiyat Gör** (F11) | Satış yapmadan fiyat gösterir (aşağıda). Dar pencerede **⋯** menüsüne iner. |
| **⋯** | Son Satışı Geri Al, Sepeti Boşalt, Hızlı Satış. |

**Fiyat değişirse:** sepetteyken bir ürünün fiyatı değiştiyse (ör. Ürünler
ekranından) satır işaretlenir: *"Fiyat değişti: 70 → 75 TL"*. Ödeme,
**Güncel fiyatları uygula**'ya dokunana ya da satırı çıkarana kadar kapalıdır.
Böylece ekranda görünen, ödemede alınan ve kayda geçen tutar **her zaman
aynıdır**. Bekletilip geri açılan sepetler de aynı şekilde denetlenir.

**Son Satışı Geri Al** (F8) **önceki müşterinin** satışını iptal eder, elinizdeki
sepeti değil; bu yüzden sepet doluyken kapalıdır. Bugünden eski bir satışı
geri almak **Geçmiş** ekranından yapılır.

**Para Üstü** *(isteğe bağlı, varsayılan kapalı — Ayarlar → Kasa)*: açıksa
NAKİT'e dokununca alınan para sorulur. Hazır düğmeler (ör. 347 TL için
350 / 400 / 500 / 1.000; tam tutar için **Tam**) ya da **Özel** tutar
seçilir; para üstü satış şeridinde ayrıca yazar. Kapalıyken NAKİT tek
dokunuşla satar (V1.1 gibi).

> **F10 bu ekranda satış tamamlamaz.** Satış yalnızca NAKİT / KART'a
> dokunarak oluşur; yanlışlıkla basılan bir tuş satış yazamaz.

### ⚡ Hızlı Satış (F1)

**Barkodu okutun, ürün satılır.** Sepet yok, tamamla düğmesi yok.

- 10 bira için bir şişeyi **10 kez okutun**; her okutma bir satıştır.
- Her satıştan sonra büyük bir **✓ SATILDI** onayı görünür ve kısa bir
  "bip" duyulur.
- Yanlış satış için **F8** ya da *Son Satışı Geri Al*.

Hızlı Satış'ı kullanmıyorsanız **Ayarlar → Kasa**'dan gizleyebilirsiniz
(menüden, Ana Ekran'dan ve ⋯ menüsünden kalkar).

### 🏷 Fiyat Gör (F11)

Müşteri "bu kaç para?" diye sorduğunda: barkodu okutun, fiyat çok büyük
yazar. Üstte sarı **FİYAT KONTROL — SATIŞ YAPILMAZ** şeridi vardır; bu
ekranda **hiçbir şey satılmaz**, müşteri ekranı değişmez. Son 5 ürün
listelenir. Geldiğiniz kasa ekranına tek dokunuşla dönersiniz.

### Dokunmatik klavye

Klavyesi olmayan kasada ad, fiyat, adet, PIN ve arama metni ekrandaki
**rakam tuş takımı** ve **Türkçe Q klavye** ile yazılır (`ş, ğ, ı, İ`,
`- / ' %` gibi işaretler dahil). Fiziksel klavyesi olan bilgisayarda
**Ayarlar → Görünüm → Ekran klavyesi** kapatılabilir.

---

## 5. STOK

### 📥 Hızlı Stok Girişi

Tek tek gelen mal için: **okut → adedi gir (+ / − ya da tuş takımı) →
Adet / Paket / Koli → Kaydet → sıradaki ürün.** Tedarikçi ve fatura
sorulmaz. Alış fiyatı isteğe bağlıdır. Bu oturumda kaydedilenler altta
listelenir; yanlış bir satır **Geri Al** ile düzeltilir.

### 📦 Mal Kabul (F3)

Faturalı / irsaliyeli, çok kalemli giriş için.

- Üstte tedarikçi (yazdıkça önerir), fatura no ve tarih.
- **Koli barkodu** okutursanız kolideki adet doğrudan eklenir (örneğin 24).
- Alış fiyatı önceki alıştan **önerilir** ("önceki alıştan"); değiştirmek için
  dokunun. Tablo her satır için *Önceki alış / Yeni alış / Değişim % / Satış
  fiyatı / Tahmini marj* gösterir.
- Alış fiyatı ayarlanan oranın üzerinde değiştiyse (varsayılan %5) yanda
  **fiyat inceleme** listesi açılır. Satış fiyatı yalnızca siz
  **Fiyatı Güncelle** derseniz değişir.
- Alış fiyatını bilmiyorsanız boş bırakın: maliyet **tahmini** olarak işaretlenir
  ve kâr hesabında ayrı tutulur. `0` yazmak "bedelsiz geldi" demektir ve onay
  ister.
- **GİRİŞİ TAMAMLA (F10)** demeden stok değişmez. Yarım kalan giriş
  kaybolmaz; sonraki açılışta *Devam Et* ya da *Taslağı Sil* sorulur.

Marj, KDV dahil fiyatlarla hesaplanır ve tahminidir; alış fiyatlarını KDV
dahil girin.

### 📋 Stok Sayımı (F9)

Önce bir bölüm seçin (*Bira Dolabı*, *Depo*…), sonra ürünleri okutun ya da
adedi yazın. Bir ürün birden fazla yerde duruyorsa ve yalnızca birini
saydıysanız, stoğu **değiştirilmez**; sayım sonunda neden atlandığı yazılır ve
eksik yeri saymanız için tek düğme sunulur. **Kör sayım** seçeneği sistemdeki
adedi saymadan önce göstermez.

### 📈 Stok Durumu

Azalan, kritik, eksi (*Stok Kontrolü Gerekli*) ve hiç sayılmamış ürünler.
Stok sayıları tuhaf görünürse **Stokları Defterden Yeniden Hesapla** stok
hareketlerini baştan toplar; veri kaybolmaz.

---

## 6. YÖNETİM

### 📊 Analiz (F7)

Her zaman **Genel Bakış + Bugün** ile açılır. Dönemler: Bugün, Dün, Son 7 Gün,
Bu Hafta, Geçen Hafta, Bu Ay, Geçen Ay, Özel. Her dönem bir öncekiyle
karşılaştırılır.

| Sekme | İçerik |
|---|---|
| Genel Bakış | Ciro, sepet sayısı, satılan adet, ortalama sepet, sepet başına ürün, ödeme dağılımı |
| Eğilimler | Saatlik, haftanın günü, günlük, haftalık, aylık |
| Ürünler | En çok adet / ciro, az satanlar, uzun süredir satılmayanlar, kategori ve marka |
| Sepetler | Birlikte satılan ürün ve kategori çiftleri ("X alanların %n'i Y de aldı") — gerçek sepetlerin sayımıdır, tahmin değildir |
| Ödemeler | Nakit / Kart / Kaydedilmemiş ve **bu dönemde yapılan iadeler** (kasa sayımı için) |
| Kâr ve Maliyet Kapsamı | Maliyeti güvenilir / tahmini / bilinmeyen satışların payı ve kâr |

- **Kaydedilmemiş:** ödeme seçimi gelmeden önceki satışlar (Hızlı Satış dahil);
  nakit ya da kart sayılmaz.
- Geri alınan bir satış, **ilk satıldığı günün** cirosundan düşer. O günkü
  iade ise Ödemeler sekmesinde, iadenin yapıldığı günde görünür.
- Kâr yalnızca maliyeti güvenilir satışlar yeterli paydaysa (%95) tek rakam
  olarak gösterilir; değilse "kapsanan kısım için" diye yazılır.
- Satış Önceliği kipinde Genel Bakış'ta kâr yoktur; kâr bilgisi kendi
  sekmesindedir.
- Raporlar ürünün **bugünkü** kategorisini kullanır.

### 🏷️ Ürünler (F6)

Arama, kategori ve durum süzgeçleri; birden çok ürün seçip **Kategoriye taşı**
(önce önizleme). **Benzerini Oluştur** bir ürünü kopyalar (1 L varken 1,5 L
eklemek gibi). Satmadığınız ürün **Kullanımdan Kaldır** ile kalkar;
**Kullanımdan kaldırılanlar** listesinden **Yeniden Kullanıma Al** ile geri
gelir (barkodları da). Geçmiş satışlar her durumda korunur.

### 🗂 Kategoriler

En fazla iki seviye (ör. *Alkollü İçecekler → Bira*). Ad değiştirme, taşıma,
kullanımdan kaldırma, birleştirme. "Bira" varken "BİRA" eklenemez; "Biralar"
gibi benzer adlar için uyarı çıkar. **Şablondan eksikleri ekle**, eski
kurulumlara hazır ağaçtan yalnızca eksikleri, önce ne yapacağını göstererek
ekler.

### 💲 Fiyat Yönetimi

Tek ürün ya da süzgeçle seçilen çok ürün için fiyat değişikliği: yüzde artır /
azalt, TL ekle / çıkar, sabit fiyat, alış fiyatına göre marj. Yuvarlama
(ör. 1 TL) artışta yukarı, indirimde aşağı yapılır. **Önizle → Uygula.**
Her toplu değişiklik bir kayıt olarak saklanır ve **Geri Al** ile önceki
fiyatlara dönülebilir. Her ürünün fiyat geçmişi görülebilir.

### 📄 Ürün İçe Aktar

Excel (`.xlsx`) ya da CSV listeden ürün ekleme / güncelleme. Adımlar:
dosya → sütun eşleme → önizleme ve sorun özeti → seçim → onay.

- Seçenekler: *Yalnızca yeni ürünleri ekle*, *Yalnızca eşleşen ürünleri
  güncelle*, *Yenileri ekle ve eşleşenleri güncelle*.
- Boş hücre mevcut bilgiyi **silmez**. Baştaki sıfırlı barkodlar korunur;
  sayıya dönüşmüş barkodlar işaretlenir.
- Listedeki alış fiyatı yalnızca **Referans alış (katalog)** olarak saklanır;
  stok maliyetini ve kâr hesabını değiştirmez.
- İçe aktarmadan önce otomatik yedek alınır; işlem ya tamamen yapılır ya hiç
  yapılmaz. Hatalı satırlar ayrı bir CSV olarak kaydedilebilir.

### 🕘 Geçmiş

**Satışlar** sekmesinde dönem, kip (Sepetli / Hızlı), ödeme ve durum
süzgeçleri; seçilen satışın kalemleri yan panelde görünür. Bir satışı geri
almadan önce ne olacağı yazılır (ör. kart satışında "banka POS cihazından
ayrıca iade edin"). Ayrıca Stok Girişleri, Sayımlar ve İşlem Günlüğü.

### ⚙️ Ayarlar

Bölümler: **Kasa, Görünüm, Ses, Barkod Okuyucu, İşletme, Stok, Yedekleme,
Donanım, Güvenlik.** Her değişiklik anında kaydedilir.

- **Görünüm:** Açık / Koyu tema, yazı boyutu (%100–%130), yoğunluk
  (Normal / Rahat). **Kaydet ve yeniden başlat** ile uygulanır. 1000×600
  ekranda yazı boyutunu %100'de tutun.
- **Ses:** açık / kapalı, ses düzeyi, her olay için **Dinle**.
- **Barkod Okuyucu:** çift okuma süresi; okuyucunun önüne / sonuna eklediği
  karakterler (Gelişmiş).
- **İşletme:** dükkân adı (menüde ve pencere başlığında görünür), iş günü
  başlangıç saati.

### 🩺 Sistem Durumu

Sürüm, veri klasörü ve boyutu, veritabanı denetimi, son yedek ve hata, yedeklerin
toplam boyutu, boş disk, okuyucu ve donanım durumu. **Tam denetim yap** tüm
kayıtları baştan doğrular. **Destek paketi oluştur…** sorun bildirmek için tek
bir ZIP dosyası hazırlar (aşağıda).

### 🔎 Barkod Testi (F12)

Okuyucunun tam olarak ne gönderdiğini gösterir: karakter sayısı, hız, bitiş
tuşu, düzeltme sonucu. Bu ekranda **hiçbir satış ya da stok kaydı oluşmaz.**

---

## 7. Barkod okuyucu

Klavye gibi çalışan normal USB barkod okuyucularla çalışır; ayar gerekmez.

- **Barkod kutusuna tıklamanız gerekmez.** Bir tabloya ya da düğmeye
  dokunmuş olsanız bile okutma yakalanır ve doğru yere gider.
- Bir soru penceresi açıkken okutma yaparsanız uygulama **o okutmayı işlemez**
  ve hemen haber verir; pencere kapanınca beklenmedik bir satış oluşmaz.

Bir ürünün birden çok barkodu olabilir:

| Tür | Anlamı |
|---|---|
| Tekli / alternatif | 1 adet (eski ve yeni ambalaj gibi) |
| Paket | ör. 6 adet |
| Koli | ör. 24 adet |

**Satışta** koli barkodu okutunca kısa bir onay sorulur ("1 koli = 24 adet.
Satılsın mı?"); Ayarlar → Kasa'dan kapatılabilir. **Stok girişinde** sorulmaz.

---

## 8. Ürün tanımlama

Tüm ürünleri baştan tanımlamanız **gerekmez**. Tanınmayan bir barkod
okutunca uygulama sorar:

- **Yeni ürün:** ad, satış fiyatı ve kategori yeterlidir (barkod hazır gelir).
  Son kullanılan kategoriler tek dokunuşla seçilir. **Gelişmiş** bölümünde
  marka, tedarikçi, KDV, paket / koli barkodu, referans alış ve başlangıç stoğu.
- **Mevcut ürüne bağla:** yeni ambalajın barkodunu var olan ürüne tekli,
  paket ya da koli olarak bağlar; böylece aynı ürün iki kez açılmaz.
- Barkod **kullanımdan kaldırılmış** bir ürüne aitse, yeni ürün açmak yerine
  onu yeniden kullanıma almayı önerir.

Kaydettikten sonra satış kaldığı yerden devam eder (koli barkoduysa 24 adet).

"Şu an kaç adet var?" alanını bilmiyorsanız **boş bırakın**: ürün *Henüz
Sayılmadı* olur ve boş yere kritik stok uyarısı vermez. `0` "saydım, gerçekten
sıfır" demektir.

---

## 9. Yönetici PIN'i

İsteğe bağlıdır; siz belirleyene kadar kapalıdır (**Ayarlar → Güvenlik**).
PIN 4–8 rakamdır; 1234, 0000 gibi kolay PIN'ler kabul edilmez.

**PIN isteyen işler:** Ayarlar'a giriş, yedekten geri yükleme, toplu fiyat
değişikliği ve geri alması, ürün içe aktarma, ürünü kullanımdan kaldırma,
kategori kaldırma / birleştirme, geçmiş satışı geri alma, stok girişini geri
alma, stokları yeniden hesaplama, PIN değiştirme.

**PIN ASLA istenmez:** satış, aynı gün son satışı geri alma, bekletme,
fiyat gör, ürün arama, yeni ürün tanımlama, tek ürün fiyatı düzenleme,
ekranlar arası geçiş. Kasa hiçbir zaman PIN yüzünden yavaşlamaz.

- PIN bir kez girilince 5 dakika boyunca (ya da kasa ekranına dönene kadar)
  tekrar sorulmaz.
- 5 yanlış denemede 1 dakika bekletir; tekrarında süre ikiye katlanır
  (en çok 30 dakika).
- PIN belirlerken bir kez **kurtarma kodu** (`XXXX-XXXX-XXXX`) gösterilir;
  kâğıda yazıp saklayın. PIN'i unutursanız bu kodla yenisini belirlersiniz.
- Kurtarma kodu da kaybolduysa son çare: `TekelStok.exe --yonetici-pin-sifirla`.
  Ekrana `SIFIRLA` yazmanız istenir; önce `pin_sifirlama_oncesi_` yedeği alınır,
  PIN silinir ve yeni PIN belirleyip bildirimi onaylayana kadar Yönetim
  ekranlarında kırmızı bir uyarı görünür.

### PIN neyi korur, neyi korumaz?

PIN, dükkânda **yanlışlıkla ya da gelişigüzel** yapılacak değişiklikleri
önler (ör. kasada duran birinin fiyatları toplu değiştirmesi). Bir **güvenlik
kasası değildir**:

- Windows hesabına ya da dosyalara erişebilen biri veritabanına doğrudan
  ulaşabilir.
- PIN'in kendisi saklanmaz, yalnızca geri çözülemez bir özeti saklanır; bu özet
  yedeklerde de bulunur.
- Eski bir yedeğe dönmek, **o yedekteki PIN durumunu** geri getirir.
- Destek paketine PIN bilgisi hiçbir zaman konmaz.

---

## 10. Yedekleme

Uygulama yedekleri **kendisi** alır; satışı hiç bekletmez.

| Yedek | Ne zaman | Saklama |
|---|---|---|
| **Günlük** (`gunluk_…`) | Her iş günü bir kez, veri değiştiyse: açılışta, boşta (60 sn dokunulmadığında, 5 dakikada bir denenir) ya da kapanışta | Son 30 gün (7–365 ayarlanabilir) |
| **Otomatik** (`otomatik_…`) | Veri değiştiyse ve son yedekten beri 2 saat geçtiyse (5–1440 dk ayarlanabilir); açılışta, boşta ve kapanışta | Son 10 |
| **Güncelleme öncesi** | Yeni sürüm veriyi ilk açtığında | Asla silinmez |
| **İçe aktarma öncesi** | Her ürün içe aktarmadan önce | Son 10 |
| **Geri yükleme / geri dönüş / PIN sıfırlama öncesi** | O işlemden hemen önce | Asla silinmez |
| **Elle** (**Şimdi Yedek Al**) | Siz istediğinizde | **Asla silinmez** |

- Silme yalnızca uygulamanın **kendi oluşturduğu ve listesine yazdığı**
  dosyalara uygulanır; başka dosyalara ve başka kurulumların yedeklerine
  dokunulmaz.
- Otomatik yedek klasörü değiştirilebilir (ör. ikinci bir disk). Klasör
  yazılamazsa yedek varsayılan yere alınır ve durum çubuğunda uyarı görünür.
- Yedekler çalışan veritabanının anlık, tutarlı bir kopyasıdır; dükkân
  açıkken alınması güvenlidir.

**Geri yükleme** (**Ayarlar → Yedekleme → Yedekten Geri Yükle**, PIN ister):
işlemden hemen önce mevcut verinin bir kopyası alınır; geri yükleme başarısız
olursa eski veri geri konur. Seçtiğiniz yedek dosyası değiştirilmez. Eski
sürümden bir yedek seçerseniz kopyası yeni sürüme uyarlanır.

---

## 11. Veriler nerede?

| Ne | Nerede |
|---|---|
| Veritabanı | `%LOCALAPPDATA%\TekelStok\tekelstok.db` |
| Kayıtlar (log) | `%LOCALAPPDATA%\TekelStok\logs\app.log` |
| Otomatik, günlük ve güncelleme öncesi yedekler | `%LOCALAPPDATA%\TekelStok\backups` (değiştirilebilir) |
| Elle alınan yedekler | `Belgeler\Tekel Stok Yedekleri` (değiştirilebilir) |
| Ses dosyaları (kendiliğinden üretilir) | `%LOCALAPPDATA%\TekelStok\sounds` |

**Taşınabilir kullanım:** `TekelStok.exe` yanına `portable.txt` adında boş bir
dosya koyarsanız veriler exe'nin yanındaki `veri` klasöründe tutulur.

---

## 12. Hiçbir şey silinmez

Finansal ve stok geçmişi **fiziksel olarak silinmez**.

- Geri alınan satış "geri alındı" olarak işaretlenir ve tersini alan yeni bir
  kayıt oluşur. Aynı satış iki kez geri alınamaz.
- Satmadığınız ürün, kategori ya da barkod **Kullanımdan Kaldır** ile kalkar;
  geçmişi olduğu gibi kalır.
- Bugünün fiyatını değiştirmek **dünkü ciroyu değiştirmez**: her satış kendi
  fiyat ve maliyet kopyasını taşır.
- Toplu fiyat değişikliğinin geri alınması da yeni bir kayıttır.

---

## 13. Klavye kısayolları

| Tuş | İşlem |
|---|---|
| `F1` | Hızlı Satış |
| `F2` | Sepetli Satış |
| `F3` | Mal Kabul |
| `F4` | Yeni Müşteri işareti (Hızlı Satış; Satış Önceliği kipinde gerekmez) |
| `F5` | Yenile |
| `F6` | Ürünler |
| `F7` | Analiz |
| `F8` | Son İşlemi Geri Al — **Sepetli Satış'ta sepet boşken** |
| `F9` | Stok Sayımı |
| `F10` | İşlemi Tamamla (Mal Kabul / Stok Sayımı) — **Sepetli Satış'ta çalışmaz** |
| `F11` | Fiyat Gör |
| `F12` | Barkod Testi |
| `Esc` | Geri / Vazgeç (açık bir arama ya da ödeme panelini önce kapatır) |
| `Ctrl+F` | Ara (kasa ekranlarında Ürün Ara) |
| `Ctrl+H` | Ana Ekran |

Kısayollar bilerek F-tuşları ve `Ctrl`'lü tuşlardır: çıplak harf kısayolu
olsaydı, okutulan barkodun içindeki bir harf ekranı değiştirebilirdi. Menünün
altındaki sürüm yazısının üzerine gelince de bu liste görünür.

---

## 14. Bir sorun olursa

- Uygulama teknik hata göstermez; ne olduğunu ve ne yapılacağını sade Türkçe
  yazar. Teknik ayrıntı `logs\app.log` dosyasına gider.
- **Sistem Durumu → Destek paketi oluştur…** sorunu bildirmek için tek bir ZIP
  hazırlar: sürüm, ayarlar, kayıt dosyaları, denetim sonuçları. Kullanıcı adı
  ve klasör yolları gizlenir, **PIN bilgisi konmaz**, veritabanı
  **varsayılan olarak eklenmez** (isteğe bağlı kutucuk; önerilmez).
- Pencere ekran dışında kaldıysa: `TekelStok.exe --reset-window`.
- Uygulamanın kendini sınaması: `TekelStok.exe --self-test rapor.txt`.

---

## 15. Geliştirici notları

### Çalıştırma

```
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m app.main --data-dir C:\karalama\veri
```

> **Veri güvenliği:** Geliştirme bilgisayarında dükkânın **canlı** verisi
> (`%LOCALAPPDATA%\TekelStok`) bulunabilir. Geliştirme sırasında uygulamayı
> **her zaman** `--data-dir` ya da `TEKEL_DATA_DIR` ile bir karalama klasöründe
> çalıştırın. Aşağıdaki araçlar karalama klasörü verilmezse ya da gerçek veri
> klasörü verilirse **çalışmayı reddeder**.

### Testler

```
.venv\Scripts\python.exe -m pytest tests
.venv\Scripts\python.exe -m pytest tests -m perf
```

Varsayılan takım başarım (`perf`) testlerini atlar; onlar 10k / 100k satışlık
örnek veriyle ayrıca çalıştırılır. Arayüz testleri `QT_QPA_PLATFORM=offscreen`
ile çalışır; Windows'ta bir test 1000×600'ü **yerel** yazı ölçüleriyle de
denetler.

### Araçlar (hepsi karalama klasörü ister)

| Araç | Ne yapar |
|---|---|
| `python -m app.tools.perf_dataset --hazir 10k` (`kucuk`, `10k`, `100k`) | Gerçek servislerle büyük örnek veri üretir |
| `python -m app.tools.benchmark --veri <db> [--arayuz] [--v1-bicimi]` | Başarım ölçümü (p50 / p95); `docs/V1.2_PERFORMANCE.md` |
| `python -m app.tools.ekran_goruntusu --cikti <klasör> [--profil 1366x768]` | Örnek dükkânla 7 ekran profilinde tüm ekranların görüntüsü + taşma denetimi; `docs/V1.2_EKRAN_INCELEMESI.md` |

### Derleme

```
.venv\Scripts\python.exe build_exe.py --out TekelStok-1.2.0b1
powershell -ExecutionPolicy Bypass -File verify_build.ps1 -ExePath dist\TekelStok-1.2.0b1\TekelStok.exe
```

- `build_exe.py` çıktıyı `dist\<--out>` klasörüne ve yanına
  `<--out>_tasinabilir.zip` olarak yazar. Yayındaki V1.1 çıktısı
  (`dist\TekelStok`, `TekelStok_tasinabilir.zip`) korunur; üzerine yazılmaz.
- `verify_build.ps1` exe'yi gerçekten çalıştırır: pencereli uygulama mı,
  `--self-test`, temiz profilde açılış, ikinci açılışta kalıcılık ve depodaki
  V1.1 örneğinin **kopyasıyla** yükseltme + güncelleme öncesi yedek. Başka bir
  TekelStok açıksa **hiç başlamaz** (canlı kasaya dokunmamak için) ve yalnızca
  kendi başlattığı süreçleri kapatır.
- **Türkçe yol uyarısı:** PyInstaller'ın çalışma klasörü yalnızca ASCII içeren
  `C:\TekelStokBuild` altında tutulur (`TEKEL_BUILD_ROOT`). `verify_build.ps1`
  **UTF-8 BOM** ile kaydedilmelidir.

### Mimari

```
Arayüz (app/ui)                   — yalnızca çizer; SQL yazmaz
    ↓
Servisler (app/services)          — iş kuralları; her işlem kendi transaction'ı
Analiz (app/analytics), İçe aktarma (app/importers)
    ↓
Çekirdek (app/core)               — veritabanı, şema/göç, para, Türkçe metin, maliyet
    ↓
SQLite (WAL)
```

`app/core`, `app/services`, `app/analytics`, `app/importers` ve donanım /
okuyucu çekirdeği **PySide6 içe aktarmaz** — mimari testleri denetler.

### Veritabanı sürümleri

Şema sürümü **6**. Göçler yalnızca ekleme yapar (`ADD COLUMN`,
`CREATE TABLE`, `CREATE INDEX`) ve bekleyen tüm sürümler **tek bir
transaction**'da uygulanır; başarısız olursa dosya başladığı sürümde kalır.
Göçten önce boş disk denetlenir ve `guncelleme_oncesi_v<eski>_v<yeni>_*.db`
yedeği alınır. Daha yeni bir şemayla açılmaya çalışılan eski kod reddedilir
(V1.2 ve sonrası). Depoda V1.0 ve V1.1 ile üretilmiş örnek veritabanları
(`tests/fixtures`) vardır; testler her zaman kopyalarını kullanır.

### Bilinmesi gereken tasarım kararları

| Karar | Sebep |
|---|---|
| Para **tam sayı kuruş** | Kayan noktalı sayı zamanla kuruş kaybettirir |
| Stok defteri tek doğruluk kaynağı | `current_stock` bir önbellektir; defterden yeniden üretilebilir |
| Oransal maliyet çekimi `(2qV+S)//(2S)` | `q × round(V/S)` stok bitince kuruş artığı bırakır |
| Negatif stokta gelen mal önce "deliği kapatır" | O birimlerin maliyeti geçmiş satışlarda zaten gider yazıldı |
| Bilinmeyen alış maliyeti 0 yazılmaz, **tahmini** işaretlenir | 0 TL'lik giriş ortalama maliyeti sessizce yarıya indirirdi |
| Referans alış (katalog) maliyet hesabına girmez | Liste fiyatı gerçek alış değildir |
| Fiş geri alma **kanıtlanabilir** değilse reddedilir | Araya giren hareketlerden sonra ters kayıt ortalama maliyeti bozar |
| Görünen = onaylanan = kaydedilen tutar | Sepetteyken değişen fiyat ödemeden önce açıkça kabul edilir |
| Geri alınan satış ilk satış gününe yazılır | Gün sonu cirosu ve ödeme dağılımı geriye dönük tutarlı kalır |
| Çift okuma penceresi **120 ms** | Tekrar okutmak birincil miktar girişidir; geniş pencere gerçek satışı düşürür |
| Karar penceresi açıkken okutma **kuyruğa alınmaz** | Sonradan oynatılırsa gecikmiş sürpriz satış oluşur |
| Kasa katmanları (Ürün Ara, Bekleyenler, Para Üstü) iç içe olay döngüsü açmaz | Okuyucu ve ekran hiç kilitlenmez |
| Kısmi konum sayımı stoğu düzeltmez | Çok yerde bulunan ürünün tek yerini saymak sahte fark üretir |
| `business_date` yazma anında **dondurulur** | Gün başlangıcı ayarı değişse bile geçmiş raporlar değişmez |
| Satış yalnızca açık ödeme eylemiyle tamamlanır | Klavyesiz kasada genel bir kısayol yanlışlıkla satış yazmamalı |
| Ödeme onayı veritabanı işleminden ÖNCE | İleride kart terminali beklerken SQLite işlemi açık kalmasın |
| Yedekler ayrı bir salt okunur bağlantıdan, SQLite yedekleme API'siyle | WAL içeriği dahil tutarlı kopya; canlı dosya ham kopyalanmaz |
| Müşteri ekranı çağrıları yutulur | Ekran arızası bir satışı asla engellememeli |
| Barkodda baştaki sıfırlar korunur | Dahili kodlarda sıfır anlamlıdır; GTIN yalnızca kontrol hanesi doğrulanırsa birleştirilir |

### Kapsam dışında

Kart terminali (banka POS) ve müşteri ekranı seri protokolleri, parçalı ödeme,
veresiye / cari hesap ekranı (şemada `VERESIYE` tanımlı), fiş yazdırma,
indirim, bulut, mobil, çok şube, sadakat programı, otomatik sipariş, tartılı
ürün (şema hazır: `measure_kind` / `base_unit`), ayar dışa aktarma.
