"""Servis kabı: arayüzün gördüğü TEK giriş noktası.

Her ekran ``Services`` nesnesini alır. Böylece arayüz ne veritabanı yolunu ne
de servislerin birbirine nasıl bağlandığını bilir; testler de kendi geçici
veritabanlarını kolayca enjekte eder.
"""
from __future__ import annotations

from dataclasses import dataclass

from app import config
from app.core.db import Database, open_database
from app.hardware.customer_display import CustomerDisplayService
from app.payments.service import PaymentService
from app.services.analytics_service import AnalyticsService
from app.services.audit_service import AuditService
from app.services.backup_service import BackupService
from app.services.barcode_service import BarcodeService
from app.services.cart_service import CartService
from app.services.catalog_service import CatalogService
from app.services.count_service import CountService
from app.services.inventory_service import InventoryService
from app.services.product_service import ProductService
from app.services.purchase_service import PurchaseService
from app.services.sale_service import SaleService
from app.services.session_grouping_service import SessionGroupingService
from app.services.settings_service import SettingsService
from app.services.supplier_service import SupplierService


@dataclass
class Services:
    db: Database
    settings: SettingsService
    audit: AuditService
    catalog: CatalogService
    barcodes: BarcodeService
    inventory: InventoryService
    products: ProductService
    sales: SaleService
    cart: CartService
    suppliers: SupplierService
    purchases: PurchaseService
    counts: CountService
    backup: BackupService
    analytics: AnalyticsService
    grouping: SessionGroupingService
    payments: PaymentService
    display: CustomerDisplayService

    def close(self) -> None:
        self.display.close()
        if self.db.is_open:
            self.db.close()


def build_services(db: Database) -> Services:
    """Açık bir veritabanından servisleri kurar (testler ve araçlar için)."""
    settings = SettingsService(db)
    audit = AuditService(db)
    catalog = CatalogService(db)
    barcodes = BarcodeService(db, settings)
    inventory = InventoryService(db, settings)
    products = ProductService(db, settings, catalog, barcodes, inventory, audit)
    sales = SaleService(db, settings, inventory, audit)
    cart = CartService(db, settings, sales, products)
    suppliers = SupplierService(db)
    purchases = PurchaseService(db, settings, inventory, audit)
    counts = CountService(db, settings, inventory, catalog, audit)
    backup = BackupService(db, settings)
    analytics = AnalyticsService(db, settings, inventory, products)
    grouping = SessionGroupingService(db, settings, audit)
    # Odeme ve musteri ekrani: veritabani bilmeyen, degistirilebilir adaptorler.
    payments = PaymentService()
    display = CustomerDisplayService()
    return Services(
        db=db,
        settings=settings,
        audit=audit,
        catalog=catalog,
        barcodes=barcodes,
        inventory=inventory,
        products=products,
        sales=sales,
        cart=cart,
        suppliers=suppliers,
        purchases=purchases,
        counts=counts,
        backup=backup,
        analytics=analytics,
        grouping=grouping,
        payments=payments,
        display=display,
    )


def create_services() -> Services:
    """Üretim kurulumu: yolları ``config`` çözer — bunu yapan TEK yer burasıdır."""
    return build_services(open_database(config.db_path()))
