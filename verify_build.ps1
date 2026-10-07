# Derleme dogrulama.
#
# "PyInstaller hata vermedi" YETERLI BIR KANIT DEGILDIR. Bu betik derlenmis
# exe'yi gercekten calistirir ve su dort seyi dogrular:
#   1. Windows GUI uygulamasi mi (siyah konsol penceresi acilmiyor mu),
#   2. --self-test donmus kod yollarinda geciyor mu,
#   3. Temiz bir profilde veritabani ve log olusuyor mu,
#   4. Ikinci acilista veri KALICI mi.
#
# NOT: Bu dosya UTF-8 BOM ile kaydedilmelidir; aksi halde PowerShell 5.1 onu
# ANSI okur ve Turkce karsilastirmalar bozulur.
#
# Kullanim:
#   powershell -ExecutionPolicy Bypass -File verify_build.ps1 [-ExePath <exe>]
# -ExePath verilmezse en yeni dist\TekelStok-*\TekelStok.exe dogrulanir
# (yoksa dist\TekelStok\TekelStok.exe).
#
# GUVENLIK: Bu makinede sahibin CANLI kasa uygulamasi calisiyor olabilir.
# Betik baska bir TekelStok sureci aciksa HIC baslamaz ve yalnizca KENDI
# baslattigi surecleri (PID ile) kapatir; adi TekelStok olan her sureci
# oldurmez. Tum calistirmalar gecici --data-dir klasorleri kullanir.

param([string]$ExePath = "")

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not $ExePath) {
    $aday = Get-ChildItem -Path (Join-Path $ProjectRoot "dist") -Directory `
        -Filter "TekelStok-*" -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending |
        ForEach-Object { Join-Path $_.FullName "TekelStok.exe" } |
        Where-Object { Test-Path $_ } | Select-Object -First 1
    if ($aday) { $ExePath = $aday } else { $ExePath = Join-Path $ProjectRoot "dist\TekelStok\TekelStok.exe" }
}

$calisan = Get-Process -Name "TekelStok" -ErrorAction SilentlyContinue
if ($null -ne $calisan) {
    Write-Output "[DURDURULDU] Bir TekelStok sureci zaten calisiyor (PID: $(@($calisan).Id -join ', '))."
    Write-Output "Canli kasaya dokunmamak icin dogrulama baslatilmadi. Uygulamayi kapatip tekrar deneyin."
    exit 2
}

$script:Failures = 0

function Test-Step {
    param([string]$Name, [bool]$Ok, [string]$Detail = "")
    $status = if ($Ok) { "BASARILI" } else { "BASARISIZ" }
    if (-not $Ok) { $script:Failures++ }
    $line = "[$status] $Name"
    if ($Detail) { $line += " - $Detail" }
    Write-Output $line
}

Write-Output "Dogrulanan dosya: $ExePath"
Write-Output ""

if (-not (Test-Path $ExePath)) {
    Write-Output "[BASARISIZ] Exe bulunamadi. Once: py -3.12 build_exe.py"
    exit 1
}

# --- 1) PE basligindaki Subsystem alani -----------------------------------
# 2 = Windows GUI, 3 = Konsol. Kasa uygulamasinda konsol penceresi acilmamali.
$bytes = [System.IO.File]::ReadAllBytes($ExePath)
$peOffset = [BitConverter]::ToInt32($bytes, 0x3C)
$subsystem = [BitConverter]::ToUInt16($bytes, $peOffset + 0x5C)
Test-Step "Pencereli uygulama (konsol acilmiyor)" ($subsystem -eq 2) "Subsystem=$subsystem"

# --- 2) Kendi kendini sinama ----------------------------------------------
$report = Join-Path $env:TEMP "tekelstok_verify_report.txt"
if (Test-Path $report) { Remove-Item $report -Force }
$proc = Start-Process -FilePath $ExePath -ArgumentList "--self-test", $report `
    -Wait -PassThru -NoNewWindow
Test-Step "Kendi kendini sinama cikis kodu" ($proc.ExitCode -eq 0) "kod=$($proc.ExitCode)"

if (Test-Path $report) {
    $content = Get-Content $report -Raw -Encoding UTF8
    Test-Step "Sinama raporunda basarisiz kontrol yok" (-not ($content -match "BASARISIZ"))
    # Turkce karakterler donmus kodda da bozulmamali.
    Test-Step "Turkce karakterler korunuyor" ($content -match "Çaykur")
} else {
    Test-Step "Sinama raporu yazildi" $false
}

# --- 3) Temiz profilde acilis ---------------------------------------------
$cleanDir = Join-Path $env:TEMP ("tekelstok_verify_" + [Guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Force -Path $cleanDir | Out-Null

$app = Start-Process -FilePath $ExePath `
    -ArgumentList "--data-dir", $cleanDir, "--reset-window" -PassThru
$dbPath = Join-Path $cleanDir "tekelstok.db"
$logPath = Join-Path $cleanDir "logs\app.log"

$found = $false
for ($i = 0; $i -lt 40; $i++) {
    Start-Sleep -Seconds 1
    if ((Test-Path $dbPath) -and (Test-Path $logPath)) { $found = $true; break }
}
Test-Step "Temiz profilde veritabani ve log olustu" $found $cleanDir

# Pencere gercekten acildi mi? Veritabani, pencere gorunmeden ONCE olusur;
# bu yuzden baslik icin ayrica beklenir. (onefile kipinde baslatici AYRI bir
# surectir, bu yuzden tum TekelStok surecleri taranir.)
$titled = $null
for ($i = 0; $i -lt 30; $i++) {
    $titled = Get-Process -Name "TekelStok" -ErrorAction SilentlyContinue |
        Where-Object { $_.MainWindowTitle -ne "" }
    if ($null -ne $titled) { break }
    Start-Sleep -Seconds 1
}
Test-Step "Ana pencere acildi" ($null -ne $titled) `
    ($(if ($titled) { @($titled)[0].MainWindowTitle } else { "baslik bulunamadi" }))

# DUZGUN kapanis: closeEvent calissin ki WAL diske islensin ve pencere
# konumu kaydedilsin. Zorla oldurmek bu yollari HIC denemez.
$closed = $app.CloseMainWindow()
if (-not $app.WaitForExit(15000)) {
    Stop-Process -Id $app.Id -Force -ErrorAction SilentlyContinue
}
Test-Step "Uygulama duzgun kapandi" $closed
Start-Sleep -Seconds 2

# --- 4) Ikinci acilis: veri kalici mi -------------------------------------
# NOT: Dosya boyutu tek basina yaniltici bir olcuttur. WAL kipinde veri
# -wal dosyasinda bekliyor olabilir; bu yuzden boyut yerine UYGULAMANIN
# ikinci kez ayni veriyle acilabildigi dogrulanir.
$sizeBefore = (Get-Item $dbPath).Length
Test-Step "Veritabani bos degil" ($sizeBefore -gt 0) "$sizeBefore bayt"

$app2 = Start-Process -FilePath $ExePath -ArgumentList "--data-dir", $cleanDir -PassThru
$titled2 = $null
for ($i = 0; $i -lt 30; $i++) {
    $titled2 = Get-Process -Name "TekelStok" -ErrorAction SilentlyContinue |
        Where-Object { $_.MainWindowTitle -ne "" }
    if ($null -ne $titled2) { break }
    Start-Sleep -Seconds 1
}
Test-Step "Ikinci acilis basarili" ($null -ne $titled2)

$app2.CloseMainWindow() | Out-Null
if (-not $app2.WaitForExit(15000)) {
    Stop-Process -Id $app2.Id -Force -ErrorAction SilentlyContinue
}
Start-Sleep -Seconds 2

# Log iki ayri acilis kaydetmis olmali: ayni veri klasoru iki kez acildi.
$logText = Get-Content $logPath -Raw -Encoding UTF8
$starts = ([regex]::Matches($logText, "baslatiliyor|başlatılıyor")).Count
Test-Step "Log iki acilis kaydetti" ($starts -ge 2) "$starts acilis"
Test-Step "Kapanis temiz kaydedildi" ($logText -match "kapatildi|kapatıldı")

# Duzgun kapanista WAL islenmis olmali: veritabani dosyasi artik dolu.
$sizeAfter = (Get-Item $dbPath).Length
Test-Step "Veritabani diske islendi" ($sizeAfter -gt 20000) `
    "$sizeBefore -> $sizeAfter bayt"

# Temizlik
try { Remove-Item $cleanDir -Recurse -Force -ErrorAction SilentlyContinue } catch {}

Write-Output ""
if ($script:Failures -eq 0) {
    Write-Output "SONUC: TUM DOGRULAMALAR BASARILI"
    exit 0
} else {
    Write-Output "SONUC: $($script:Failures) DOGRULAMA BASARISIZ"
    exit 1
}
