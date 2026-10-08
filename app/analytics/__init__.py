"""Analiz V2 (V1.2 M8a): dönemler, genel bakış, eğilimler, ürünler, sepetler, kâr.

Qt bilmez. Her işlev bir ``Database`` ve bir ``Donem`` alır; ``AnalyticsService``
bu modüllerin önündeki cephe (facade) olarak V1.1 arayüzünü KORUR ve sonuçları
``(sorgu, dönem, data_version)`` anahtarıyla önbelleğe alır.

Ortak kurallar:
  * Dönem ölçüleri geri almayı ORİJİNAL satışın iş gününe yazar (geri alınan
    satış hiç sayılmaz; özet tabloları da böyle tutulur — I23/I34).
  * Kategori/marka kırılımı ürünlerin BUGÜNKÜ sınıflandırmasını kullanır
    (satış anındaki kategori saklanmaz; belgelenmiş sınır).
  * Sepet istatistikleri yalnızca KESİN sepetleri (Sepetli Satış) sayar.
"""
