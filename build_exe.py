"""Windows .exe üretir.

    py -3.12 build_exe.py            # taşınabilir klasör (ÖNERİLEN)
    py -3.12 build_exe.py --onefile  # ek olarak tek dosya

ÖNEMLİ — Türkçe yol sorunu
--------------------------
Bu projenin yolu Türkçe karakter içerir ("Aİ Barkot Stok-Satış Uygulaması").
PyInstaller'ın geçici çalışma klasörü bu yolun altında olursa kodlama hataları
çıkar. Bu yüzden derleme YALNIZCA ASCII karakterli bir klasörde yapılır
(``C:\\TekelStokBuild``) ve çıktı sonradan projeye kopyalanır.
``TEKEL_BUILD_ROOT`` ile değiştirilebilir.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
SPEC = PROJECT_ROOT / "TekelStok.spec"
DIST = PROJECT_ROOT / "dist"

#: Türkçe karakter içermeyen derleme kökü — bkz. modül notu.
ASCII_BUILD_ROOT = Path(os.environ.get("TEKEL_BUILD_ROOT", r"C:\TekelStokBuild"))

APP_NAME = "TekelStok"

#: Sahibin kullandığı (V1.1) dağıtım. V1.2 derlemeleri buraya ASLA yazmaz;
#: geçişi dükkân sahibi kendisi yapar (bkz. docs/V1.2_MASTER_PLAN.md §2).
KORUNAN_CIKTILAR = (DIST / APP_NAME, DIST / f"{APP_NAME}_tasinabilir.zip", DIST / f"{APP_NAME}.exe")


def varsayilan_cikti_adi() -> str:
    """``TekelStok-<sürüm>`` — sürüm ``app.config.APP_VERSION``'dan okunur."""
    sys.path.insert(0, str(PROJECT_ROOT))
    from app.config import APP_VERSION

    return f"{APP_NAME}-{APP_VERSION}"


def korumali_mi(yol: Path) -> bool:
    hedef = yol.resolve()
    return any(hedef == k.resolve() for k in KORUNAN_CIKTILAR)


def log(mesaj: str) -> None:
    print(f"[derleme] {mesaj}", flush=True)


def ensure_icon() -> None:
    ikon = PROJECT_ROOT / "resources" / "icon.ico"
    if ikon.exists():
        return
    log("İkon yok, üretiliyor…")
    try:
        subprocess.run(
            [sys.executable, "-m", "app.tools.make_icon"],
            cwd=str(PROJECT_ROOT), check=True,
        )
    except Exception as hata:
        log(f"İkon üretilemedi (sorun değil, ikonsuz devam): {hata}")


def remove_locked(path: Path, retries: int = 3) -> None:
    """Çalışan bir exe klasörü kilitli olabilir; birkaç kez denenir."""
    for deneme in range(retries):
        if not path.exists():
            return
        try:
            shutil.rmtree(path)
            return
        except PermissionError:
            if deneme == retries - 1:
                raise SystemExit(
                    f"'{path}' silinemedi. Uygulama açıksa kapatıp tekrar deneyin."
                )
            log("Klasör kilitli, 3 sn sonra tekrar denenecek…")
            time.sleep(3)


def run_pyinstaller(onefile: bool, cikti_adi: str) -> None:
    calisma = ASCII_BUILD_ROOT / ("work_onefile" if onefile else "work_onedir")
    cikti = ASCII_BUILD_ROOT / ("dist_onefile" if onefile else "dist_onedir")
    remove_locked(calisma)
    remove_locked(cikti)
    calisma.mkdir(parents=True, exist_ok=True)
    cikti.mkdir(parents=True, exist_ok=True)

    ortam = dict(os.environ)
    ortam["TEKEL_ONEFILE"] = "1" if onefile else "0"
    ortam["TEKEL_PROJECT_ROOT"] = str(PROJECT_ROOT)
    ortam["PYTHONIOENCODING"] = "utf-8"

    komut = [
        sys.executable, "-m", "PyInstaller", str(SPEC),
        "--noconfirm", "--clean",
        "--distpath", str(cikti),
        "--workpath", str(calisma),
        "--log-level", "WARN",
    ]
    log(("onefile" if onefile else "onedir") + " derleniyor…")
    subprocess.run(komut, check=True, env=ortam, cwd=str(ASCII_BUILD_ROOT))

    DIST.mkdir(parents=True, exist_ok=True)
    if onefile:
        kaynak = cikti / f"{APP_NAME}.exe"
        hedef = DIST / f"{cikti_adi}.exe"
        if korumali_mi(hedef):
            raise SystemExit(f"Korunan dağıtıma yazılamaz: {hedef}")
        if hedef.exists():
            hedef.unlink()
        shutil.copy2(kaynak, hedef)
        log(f"Hazır: {hedef}")
    else:
        kaynak = cikti / APP_NAME
        hedef = DIST / cikti_adi
        if korumali_mi(hedef):
            raise SystemExit(f"Korunan dağıtıma yazılamaz: {hedef}")
        remove_locked(hedef)
        shutil.copytree(kaynak, hedef)
        log(f"Hazır: {hedef / (APP_NAME + '.exe')}")


def make_zip(cikti_adi: str) -> Path:
    klasor = DIST / cikti_adi
    zip_yolu = DIST / f"{cikti_adi}_tasinabilir.zip"
    if korumali_mi(zip_yolu):
        raise SystemExit(f"Korunan dağıtıma yazılamaz: {zip_yolu}")
    if zip_yolu.exists():
        zip_yolu.unlink()
    log("ZIP hazırlanıyor…")
    with zipfile.ZipFile(zip_yolu, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for yol in klasor.rglob("*"):
            if yol.is_file():
                z.write(yol, yol.relative_to(DIST))
    log(f"Hazır: {zip_yolu}")
    return zip_yolu


def main() -> int:
    ayrist = argparse.ArgumentParser(description="Tekel Stok derleyici")
    ayrist.add_argument(
        "--onefile", action="store_true",
        help="Ek olarak tek dosyalık exe üret (önerilmez: yavaş açılır).",
    )
    ayrist.add_argument(
        "--skip-tests", action="store_true", help="Testleri atla (önerilmez).",
    )
    ayrist.add_argument(
        "--out", default=None,
        help="dist altındaki çıktı klasörü adı (varsayılan: TekelStok-<sürüm>). "
             "Dağıtılmış dist/TekelStok asla hedef olamaz.",
    )
    args = ayrist.parse_args()
    cikti_adi = args.out or varsayilan_cikti_adi()
    if korumali_mi(DIST / cikti_adi):
        log(f"REDDEDİLDİ: '{cikti_adi}' dağıtılmış sürümün klasörü; başka bir ad seçin.")
        return 2

    if not args.skip_tests:
        log("Testler çalıştırılıyor…")
        sonuc = subprocess.run(
            [sys.executable, "-m", "pytest", "tests", "-q"],
            cwd=str(PROJECT_ROOT),
        )
        if sonuc.returncode != 0:
            log("TESTLER BAŞARISIZ — derleme durduruldu.")
            return 1

    ensure_icon()
    ASCII_BUILD_ROOT.mkdir(parents=True, exist_ok=True)
    log(f"Derleme klasörü (ASCII): {ASCII_BUILD_ROOT}")

    run_pyinstaller(onefile=False, cikti_adi=cikti_adi)
    make_zip(cikti_adi)
    if args.onefile:
        run_pyinstaller(onefile=True, cikti_adi=cikti_adi)

    exe = DIST / cikti_adi / f"{APP_NAME}.exe"
    log("")
    log(f"Bitti. Çıktı: {exe}")
    log(f'Doğrulama için: powershell -ExecutionPolicy Bypass -File verify_build.ps1 -ExePath "{exe}"')
    return 0


if __name__ == "__main__":
    sys.exit(main())
