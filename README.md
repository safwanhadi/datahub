# SIMRS DataHub (Django)

Aplikasi penampung dan verifikasi data SIMRS. Data sumber masuk ke tabel staging yang
tidak diedit. Ketika pemeriksaan dimulai, aplikasi menyalinnya ke tabel verifikasi;
setiap koreksi dan persetujuan dicatat dalam audit trail. Hanya data yang disetujui
yang tersedia melalui API pihak ketiga.

Alur operasional lengkap tersedia di [FLOW_PENGGUNAAN.md](FLOW_PENGGUNAAN.md).

## Menjalankan

```powershell
.\venv\Scripts\python.exe manage.py migrate
.\venv\Scripts\python.exe manage.py createsuperuser
.\venv\Scripts\python.exe manage.py runserver
```

Buka `http://127.0.0.1:8000/`. Buat `Data Source` melalui halaman admin, lalu berikan
izin `add import batch` dan `change verified record` kepada grup verifikator.

## Data masuk

UI **Impor SIMRS** menerima array JSON berikut:

```json
[
  {"source_key": "2026/000001", "no_rawat": "2026/000001", "nama": "Pasien A"}
]
```

`source_key` wajib unik di dalam satu batch. Untuk integrasi produksi, pemanggilan
query/view SIMRS sebaiknya dibuat sebagai management command terjadwal dan tetap
memanggil fungsi `verification.services.import_records`.

## API pihak ketiga

DataHub tidak menerbitkan token lokal. Setiap aplikasi pihak ketiga meminta opaque
access token ke SIMADU menggunakan `client_credentials`, lalu mengirimkannya ke
DataHub:

```http
GET /api/v1/data/kunjungan/?limit=100
Authorization: Bearer opaque-access-token-dari-simadu
```

DataHub memvalidasi token melalui introspection SIMADU dan mewajibkan scope
`datahub.indicators.read`.

Konfigurasi produksi memakai environment variable `DJANGO_SECRET_KEY`,
`DJANGO_DEBUG=false`, dan `DJANGO_ALLOWED_HOSTS`.

## Sumber JSON PHP dan perhitungan ulang Django

Tahap pertama mengikuti enam kebutuhan awal pada workbook: ALOS, BOR, BTO, TOI,
GDR, dan NDR. Django tidak terhubung ke database SIMRS. PHP mengirim data dasar
dan hasil hitung awal dalam JSON; Django mengarsipkan keduanya lalu menghitung
ulang keenam indikator secara independen dari data dasar.

```powershell
$env:SIMRS_INDICATOR_API_URL="https://server-internal/refrensi_app/dashboard_eksekutif/api/data_indikator_ranap.php"
$env:SIMADU_TOKEN_URL="https://simadu.rsmandalika.com/o/token/"
$env:SIMADU_CLIENT_ID="datahub-simrs-reader"
$env:SIMADU_CLIENT_SECRET="secret-dari-simadu"
$env:SIMADU_SIMRS_SCOPE="simrs.indicators.read"
```

DataHub meminta opaque token baru kepada SIMADU secara otomatis dan menyimpannya
sementara di cache sampai mendekati kedaluwarsa.

Pegawai memilih bulan pada menu **Indikator Rawat Inap**, menekan **Ambil dari
SIMRS**, memeriksa tabel, dan menyetujui hasilnya. Data asli dan hasil verifikasi
berada di tabel terpisah.

Sinkronisasi tanpa membuka dashboard (cocok untuk Windows Task Scheduler):

```powershell
.\venv\Scripts\python.exe manage.py sync_inpatient_indicators --period 2026-06
```

Kontrak JSON minimal:

```json
{
  "periode": {"hari": 30, "awal": "2026-06-01", "akhir": "2026-06-30"},
  "data_dasar": {
    "jumlah_bed": 100,
    "hari_perawatan": 2100,
    "pasien_keluar": 350,
    "pasien_mati": 10,
    "pasien_mati_48": 5
  },
  "indikator": {
    "alos": 6,
    "bor": 70,
    "bto": 3.5,
    "toi": 2.57,
    "gdr": 28.57,
    "ndr": 14.29
  }
}
```

Endpoint publik:

```text
GET /api/v1/indikator/alos/
GET /api/v1/indikator/bor/
GET /api/v1/indikator/bto/
GET /api/v1/indikator/toi/
GET /api/v1/indikator/gdr/
GET /api/v1/indikator/ndr/
```

Semua endpoint menerima `?tahun=2026&bulan=6` dan membutuhkan Bearer Token.

## Registrasi OAuth SIMADU

DataHub membutuhkan dua registrasi mesin yang terpisah:

1. `datahub-simrs-reader`, grant `client_credentials`, scope
   `simrs.indicators.read`. Credential ini dipakai DataHub untuk membaca PHP/SIMRS.
2. `datahub-resource-server`, credential khusus untuk memanggil introspection
   SIMADU. Credential ini tidak dikirim kepada pihak ketiga.

Setiap pihak ketiga juga dibuatkan client tersendiri, misalnya
`dinkes-datahub-reader`, dengan scope `datahub.indicators.read`.

Konfigurasi introspection DataHub:

```powershell
$env:SIMADU_INTROSPECTION_URL="https://simadu.rsmandalika.com/o/introspect/"
$env:SIMADU_INTROSPECTION_CLIENT_ID="datahub-resource-server"
$env:SIMADU_INTROSPECTION_CLIENT_SECRET="secret-introspection-dari-simadu"
$env:DATAHUB_API_REQUIRED_SCOPE="datahub.indicators.read"
$env:SIMADU_ALLOWED_API_CLIENTS="dinkes-datahub-reader"
$env:SIMADU_INTROSPECTION_CACHE_SECONDS="30"
```

Lihat [.env.example](.env.example) untuk seluruh konfigurasi.
