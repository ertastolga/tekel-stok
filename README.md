# Tekel Stok

Küçük bir tekel bayi için **barkodlu stok, satış, sayım ve analiz** uygulaması.
Tamamen Türkçe, tamamen çevrimdışı, Windows masaüstü.

İnternet **gerekmez**. Veriler bilgisayarınızdan **dışarı çıkmaz**. Kurulum
gerektirmez.

---

## 1. Kurulum

1. `TekelStok_tasinabilir.zip` dosyasını bir klasöre çıkarın
   (örneğin `C:\TekelStok`).
2. İçindeki **`TekelStok.exe`** dosyasına çift tıklayın.
3. Kolaylık olsun diye masaüstüne kısayol oluşturabilirsiniz:
   sağ tık → *Kısayol oluştur*.

Uygulama ilk açılışta gerekli her şeyi kendisi hazırlar.

> **Not:** Uygulama zaten açıkken ikinci kez çalıştırırsanız yeni bir pencere
> açılmaz; mevcut pencere öne gelir. Bu, aynı veriye iki yerden yazılmasını
> önlemek içindir.

---

## 2. Çalışma kipi

Uygulamanın iki çalışma kipi vardır. **Ayarlar → Çalışma Kipi**'nden seçilir.

| Kip | Ne yapar |
|---|---|
| **Satış Önceliği** *(varsayılan)* | Uygulama doğrudan **Sepetli Satış** ekranına açılır. Dokunmatik kasa gibi çalışır. Stok bilgisi eksik ya da eksi olsa bile satış hiç durmaz ve kasada stok uyarısı çıkmaz. |
| **Stok Takibi** | V1 davranışı: uygulama ana ekrana açılır, satıştan sonra stok uyarıları görünür, panelde kâr ve stok değeri gösterilir. |

> Bu ayar **yalnızca ekranları ve uyarıları** değiştirir. Stok hareketleri,
> maliyetler ve geçmiş kayıtlar **her iki kipte de aynı şekilde** tutulur.
> İstediğiniz zaman geri alabilirsiniz; hiçbir veri etkilenmez.

Stok ekranları (Stok Girişi, Stok Sayımı, Stok Durumu) her iki kipte de
**Yönetim** altında aynen durur.

---

## 3. Günlük kullanım

Ana ekranda beş büyük düğme vardır. Günlük işin tamamı bunlarla yapılır.

### ⚡ Hızlı Satış (F1)

En çok kullanılan ekran. **Barkodu okutun, ürün satılır.** Başka hiçbir şey
yapmanız gerekmez: sepet yok, tamamla düğmesi yok, "Tamam" sorusu yok.

- Müşteri **10 bira** alıyorsa, elinizdeki **bir şişeyi 10 kez okutun**.
  Her okutma bir satıştır. Miktar yazmanız gerekmez.
- Her satıştan sonra ekranda 2 saniye büyük bir onay görünür: **✓ SATILDI**.
- Yanlış bir satış olursa **F8** ya da *Son Satışı Geri Al* düğmesi.

Ekrana sürekli bakmanız gerekmez: okutma tuttuğunda kısa bir "bip" duyarsınız.
Sesler Ayarlar'dan kapatılabilir.

### 🛒 Sepetli Satış (F2) — ana kasa ekranı

Satış Önceliği kipinde uygulama buraya açılır. Dokunmatik ekran için
tasarlanmıştır; fare gerekmez.

**Akış:** barkodu okut → sepet dolar → **NAKİT** ya da **KART**'a dokun → bitti.

- Aynı ürünü tekrar okutmak yeni satır açmaz, **mevcut satırın adedini
  artırır**. Barkod okutmak, ekrana dokunmaktan her zaman hızlıdır.
- Her satırda büyük **−**, **+** ve **✕** düğmeleri vardır. 1 adetteyken
  **−**'ye basmak ürünü sepetten çıkarır.
- Sepette ürün varken stok ve ciro **değişmez**; hiçbir şey satılmış sayılmaz.
- Altta toplam büyük yazar ve iki büyük düğme vardır:
  **NAKİT** (yeşil) ve **KART** (mavi). Tek dokunuş yeterlidir; ayrıca
  "ödeme seç" diye sorulmaz.
- Yanlışlıkla iki kez dokunmak **ikinci bir satış yazmaz**.
- Satıştan sonra sepet temizlenir ve ekran anında bir sonraki barkoda hazır olur.

> **F10 bu ekranda satış tamamlamaz.** Kasa dokunmatik olduğu için satış
> yalnızca açık bir ödeme eylemiyle (NAKİT / KART) oluşur; yanlışlıkla
> basılan bir tuş nakit satış yazamaz. F10, Stok Girişi ve Stok Sayımı
> ekranlarında eskisi gibi çalışır.

### 📦 Stok Girişi (F3)

Gelen malı okutup stoğa eklersiniz.

- **Koli barkodu** okutursanız kolideki adet doğrudan eklenir (örneğin 24).
- Alış fiyatı en son girdiğiniz fiyatla **kendiliğinden dolar**. Fiyat
  değişmediyse hiçbir şey yapmanıza gerek yoktur.
- Okutma sırasında hiçbir şey kalıcı olmaz. Ancak **Girişi Tamamla**
  dediğinizde stok değişir.
- Uygulama beklenmedik şekilde kapanırsa, yarım kalan giriş kaybolmaz;
  bir dahaki açılışta *Devam Et* ya da *Taslağı Sil* diye sorulur.

### 📋 Stok Sayımı (F9)

Raf raf sayım yaparsınız: önce bir bölüm seçin (*Bira Dolabı*, *Depo*…),
sonra ürünleri okutun ya da adedi yazın.

> **Önemli:** Bir ürün birden fazla yerde bulunuyorsa (örneğin hem dolapta hem
> depoda) ve siz yalnızca birini saydıysanız, o ürünün stoğu **değiştirilmez**.
> Sayım sonunda hangi ürünlerin neden atlandığı size açıkça yazılır ve eksik
> kalan yeri de saymanız için tek düğme sunulur. Bu, yanlış sayım yüzünden
> stoğun bozulmasını önler.

*Kör sayım* seçeneğini işaretlerseniz sistemdeki adet size önceden
gösterilmez; böylece sayarken sayıya göre kendinizi ayarlamazsınız.

### 📊 Bugün (F7)

**Satış Önceliği** kipinde: günün cirosu, kaç müşteri (tamamlanan sepet),
satılan ürün adedi, ortalama sepet tutarı, sepet başına ürün, nakit/kart
dağılımı, en çok satanlar, saatlik satış grafiği ve gün karşılaştırması.

Ödeme dağılımında **"Kaydedilmemiş"** diye bir satır görebilirsiniz: bunlar
ödeme yöntemi seçilmeden önce yapılmış satışlardır (Hızlı Satış dâhil).
Bilerek ayrı gösterilir — nakit ya da kart sayılmazlar.

> Satış Önceliği kipinde **kâr gösterilmez**. Stoksuz satış serbest olduğu
> için birçok satışın maliyeti tahminidir; kesin bir kâr rakamı göstermek
> yanıltıcı olurdu. Kâr bilgisi Stok Takibi kipinde ve Yönetim ekranlarında
> durur.

---

## 4. Barkod okuyucu

Uygulama, klavye gibi çalışan normal USB barkod okuyucularla çalışır.
Ayar yapmanız gerekmez.

- **Barkod kutusuna tıklamanıza gerek yoktur.** Bir tabloya ya da düğmeye
  tıklamış olsanız bile okutma yakalanır ve doğru yere gider.
- Bir soru penceresi açıkken okutma yaparsanız, uygulama **o okutmayı işlemez**
  ve size hemen haber verir. Pencereyi kapattıktan sonra beklenmedik bir satış
  oluşmaz.
- Okuyucunuz beklenmedik davranıyorsa **F12 — Barkod Testi** ekranını açın.
  Orada okuyucunun tam olarak ne gönderdiğini görebilirsiniz. Bu ekranda
  **hiçbir satış ya da stok kaydı oluşmaz.**

### Bir ürünün birden çok barkodu olabilir

| Tür | Örnek | Anlamı |
|---|---|---|
| Tekli | `8690...492` | 1 adet |
| Paket | `8690...515` | 6 adet |
| Koli | `8690...508` | 24 adet |

**Satışta** koli barkodu okutursanız uygulama kısa bir onay sorar
("1 koli = 24 adet. Satılsın mı?"), çünkü yanlışlıkla 24 adet satmak
düzeltmesi zor bir hatadır. **Stok girişinde** ise sormaz: orada koli okutmak
zaten "24 adet geldi" demektir.

---

## 5. Ürün tanımlama

Sıfırdan 800 ürün tanımlamanız **gerekmez**. Ürünleri işiniz sırasında,
azar azar tanıtabilirsiniz.

Tanınmayan bir barkod okuttuğunuzda uygulama *"Ürün tanınmadı"* der ve
tanımlamak isteyip istemediğinizi sorar. Tanımlarsanız yalnızca üç şey
istenir: **ad, satış fiyatı, kategori.** Kaydettikten sonra barkodu tekrar
okutmanız gerekmez, satış devam eder.

**Benzer Üründen Oluştur:** Coca-Cola 1 L varken 1,5 L eklemek için markayı,
kategoriyi ve rafları yeniden yazmanıza gerek yok. Kopyalanır; siz yalnızca
barkodu, adı ve fiyatı değiştirirsiniz.

**"Şu an kaç adet var?" alanı:** bilmiyorsanız **boş bırakın**. O zaman ürün
*Henüz Sayılmadı* olarak işaretlenir ve boş yere "kritik stok" uyarısı vermez.
`0` yazarsanız bu "saydım, gerçekten sıfır" demektir.

---

## 6. Ürün nerede duruyor?

Bir ürün aynı anda **birden fazla yerde** bulunabilir: yazın dolapta, kışın
rafta, ayrıca depoda.

**Ürünün yerini değiştirmek stoğu DEĞİŞTİRMEZ.** Bu bir stok hareketi değildir,
yalnızca "nerede bulunur" bilgisidir.

---

## 7. Veriler nerede?

| Ne | Nerede |
|---|---|
| Veritabanı | `%LOCALAPPDATA%\TekelStok\tekelstok.db` |
| Kayıtlar (log) | `%LOCALAPPDATA%\TekelStok\logs\app.log` |
| Otomatik yedekler | `%LOCALAPPDATA%\TekelStok\backups` |
| Elle alınan yedekler | `Belgeler\Tekel Stok Yedekleri` |

Uygulamayı taşınabilir kullanmak isterseniz, `TekelStok.exe` yanına
`portable.txt` adında boş bir dosya koyun; veriler exe'nin yanındaki `veri`
klasöründe tutulur.

---

## 8. Yedekleme

- Uygulama **kendiliğinden** yedek alır (varsayılan: 2 saatte bir, yalnızca
  veri değiştiyse). Eski otomatik yedekler sınıra göre silinir.
- **Elle aldığınız yedekler ASLA kendiliğinden silinmez.**
- Ayarlar → Yedekleme bölümünden istediğiniz an yedek alabilir ya da eski bir
  yedeğe dönebilirsiniz.

**Geri yükleme güvenlidir:** işlemden hemen önce mevcut verilerinizin bir
kopyası otomatik alınır. Geri yükleme herhangi bir sebeple başarısız olursa
eski verileriniz geri konur; hiçbir şey kaybolmaz.

---

## 9. Hiçbir şey silinmez

Bu uygulamada finansal ve stok geçmişi **fiziksel olarak silinmez**.

- Bir satışı geri aldığınızda kayıt silinmez; "geri alındı" olarak işaretlenir
  ve tersini alan yeni bir kayıt oluşur.
- Aynı satış iki kez geri alınamaz.
- Artık satmadığınız bir ürünü *Pasife Al* dersiniz; geçmiş satışları,
  maliyetleri ve stok hareketleri olduğu gibi kalır.
- Bugünün fiyatını değiştirmek **dünkü ciroyu değiştirmez**: her satış kendi
  fiyat ve maliyet kopyasını taşır.

---

## 10. Klavye kısayolları

| Tuş | İşlem |
|---|---|
| `F1` | Hızlı Satış |
| `F2` | Sepetli Satış |
| `F3` | Stok Girişi |
| `F4` | Yeni Müşteri işareti |
| `F5` | Yenile |
| `F6` | Ürünler |
| `F7` | Bugün |
| `F8` | Son İşlemi Geri Al |
| `F9` | Stok Sayımı |
| `F10` | İşlemi Tamamla (Stok Girişi / Stok Sayımı) — **Sepetli Satış'ta çalışmaz** |
| `F12` | Barkod Testi |
| `Esc` | Geri / Vazgeç |
| `Ctrl+F` | Ara |

Kısayollar bilerek F-tuşları ve `Ctrl`'lü tuşlardan seçilmiştir: çıplak bir
harf kısayolu olsaydı, okutulan barkodun içindeki harf ekranı değiştirirdi.

---

## 11. Bir sorun olursa

- **Ekranda anlamadığınız bir mesaj yok.** Uygulama teknik hata göstermez;
  ne olduğunu sade Türkçe yazar.
- Teknik ayrıntılar `%LOCALAPPDATA%\TekelStok\logs\app.log` dosyasına yazılır.
- Stok sayıları tuhaf görünüyorsa: **Stok Durumu → Stokları Defterden Yeniden
  Hesapla**. Bu işlem stok hareketlerini baştan toplar; veri kaybolmaz.

---

## 12. Geliştirici notları

### Çalıştırma

```
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m app.main
```

### Testler

```
.venv\Scripts\python.exe -m pytest tests -q
```

### Derleme

```
.venv\Scripts\python.exe build_exe.py
powershell -ExecutionPolicy Bypass -File verify_build.ps1
```

> **Türkçe yol uyarısı:** Proje yolu Türkçe karakter içerdiği için
> (`Aİ`, `Satış`, `Ertaş`) PyInstaller'ın geçici çalışma klasörü yalnızca ASCII
> karakter içeren `C:\TekelStokBuild` altında tutulur. `TEKEL_BUILD_ROOT` ile
> değiştirilebilir. `verify_build.ps1` **UTF-8 BOM** ile kaydedilmelidir; aksi
> hâlde PowerShell 5.1 dosyayı ANSI okur ve Türkçe karşılaştırmalar bozulur.

### Mimari

```
Arayüz (app/ui)          — yalnızca çizer; iş kuralı SQL'i ÇALIŞTIRMAZ
    ↓
Servisler (app/services) — iş kuralları; her işlem kendi transaction'ını açar
    ↓
Çekirdek (app/core)      — veritabanı, para, Türkçe metin, maliyet motoru
    ↓
SQLite (WAL)
```

`app/core` ve `app/services` içinde **PySide6 içe aktarılmaz** — bir test bunu
denetler. Böylece iş kuralları başsız ve hızlı test edilebilir.

### Bilinmesi gereken tasarım kararları

| Karar | Sebep |
|---|---|
| Para **tam sayı kuruş** | Kayan noktalı sayı zamanla kuruş kaybettirir |
| Stok defteri tek doğruluk kaynağı | `current_stock` bir önbellektir; defterden yeniden üretilebilir |
| Oransal maliyet çekimi `(2qV+S)//(2S)` | `q × round(V/S)` stok bitince kuruş artığı bırakır |
| Negatif stokta gelen mal önce "deliği kapatır" | O birimlerin maliyeti geçmiş satışlarda zaten gider yazıldı |
| Fiş geri alma **kanıtlanabilir** değilse reddedilir | Araya giren hareketlerden sonra tam simetrik ters kayıt ortalama maliyeti bozar |
| Çift okuma penceresi **120 ms** | Tekrar okutmak birincil miktar giriş yöntemidir; geniş pencere gerçek satışı düşürür |
| Karar penceresi açıkken okutma **kuyruğa alınmaz** | Sonradan oynatılırsa gecikmiş sürpriz satış oluşur |
| Kısmi konum sayımı stoğu düzeltmez | Çok yerde bulunan ürünün tek yerini saymak sahte fark üretir |
| `business_date` yazma anında **dondurulur** | Gün başlangıcı ayarı değişse bile geçmiş raporlar değişmez |
| Satış yalnızca açık ödeme eylemiyle tamamlanır | Klavyesiz dokunmatik kasada genel bir kısayol yanlışlıkla satış yazmamalı (`completes_with_shortcut` varsayılanı `False`) |
| Ödeme onayı veritabanı işleminden ÖNCE | İleride kart terminali beklerken SQLite işlemi açık kalmasın |
| Ödeme kovaları çıkarmayla değil, açıkça sayılır | `toplam − nakit − kart` ileride VERESİYE/DİĞER tutarını sessizce "bilinmiyor" diye etiketlerdi |
| Müşteri ekranı çağrıları yutulur | Ekran arızası bir satışı asla engellememeli |
| Barkodda baştaki sıfırlar korunur | Dahili kodlarda sıfır anlamlıdır; GTIN yalnızca kontrol hanesi doğrulanırsa birleştirilir |

### V1 kapsamı dışında (şema hazır)

- **Veresiye / cari hesap** — `payment_method` içinde `VERESIYE` değeri
  şimdiden tanımlı, ekranı yok.
- **Tartılı ürün** — `measure_kind` / `base_unit` / `pricing_basis` sütunları
  var ve `COUNT`/`ADET`/`PER_UNIT` dışına servis katmanı izin vermiyor
  (`I33` değişmezi denetliyor). İleride gram bazlı ürün, tam sayı temel birim
  (350 g = 350) olarak şema kırılmadan eklenebilir.
- **Konum bazlı stok** ve iç transferler.
