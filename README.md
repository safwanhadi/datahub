# SIMRS DataHub (Django)

Aplikasi pengambilan dan verifikasi indikator SIMRS. Data sumber diambil dari
endpoint SIMRS pada masing-masing menu indikator dan disimpan sebagai snapshot
yang tidak diedit. Koreksi dilakukan pada salinan verifikasi dan dicatat dalam
audit trail. Hanya data yang disetujui yang tersedia melalui API pihak ketiga.

Alur operasional lengkap tersedia di [FLOW_PENGGUNAAN.md](FLOW_PENGGUNAAN.md).

## Menjalankan

```powershell
.\venv\Scripts\python.exe manage.py migrate
.\venv\Scripts\python.exe manage.py createsuperuser
.\venv\Scripts\python.exe manage.py runserver
```

Buka `http://127.0.0.1:8000/`. Endpoint sumber dikelola melalui menu
**Administrasi → Endpoint API SIMRS**. Hak akses operasional tersedia melalui
grup Petugas Data, Verifikator, Administrator DataHub, dan Pembaca.

Untuk ikon aplikasi pada portal SIMADU, gunakan launch URL
`/accounts/simadu/launch/`. Endpoint ini membuat state dan PKCE sebelum menuju
authorize SIMADU. Jangan arahkan ikon langsung ke `/o/authorize/` atau callback.
Panduan lengkap tersedia di `docs/ALUR_SSO_SIMADU.txt`.

## Data masuk

URL API SIMRS dikelola secara dinamis melalui **Administrasi → Endpoint API
SIMRS**. Konfigurasi database memiliki prioritas atas environment; environment
tetap dipakai sebagai fallback untuk kompatibilitas. Credential OAuth dan
client secret tetap wajib disimpan di environment, bukan database.

Pengambilan data dilakukan melalui tombol **Ambil dari SIMRS** pada menu
**Indikator Rawat Inap** dan **Indikator Kesehatan**. Tidak ada impor JSON generik;
setiap kelompok data mengikuti kontrak dan validasi indikatornya sendiri.

## API pihak ketiga

DataHub tidak menerbitkan token lokal. Setiap aplikasi pihak ketiga meminta opaque
access token ke SIMADU menggunakan `client_credentials`, lalu mengirimkannya ke
DataHub:

Endpoint eksternal yang tersedia adalah indikator rawat inap dan indikator
kesehatan sebagaimana tercantum pada Swagger `/docs/external/`.

DataHub memvalidasi token melalui introspection SIMADU dan mewajibkan scope
`read:dash`.

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

Endpoint eksternal:

```text
GET /api/external/v1/indicators/alos/
GET /api/external/v1/indicators/bor/
GET /api/external/v1/indicators/bto/
GET /api/external/v1/indicators/toi/
GET /api/external/v1/indicators/gdr/
GET /api/external/v1/indicators/ndr/
```

Semua endpoint menerima `?tahun=2026&bulan=6` dan membutuhkan Bearer Token.

## Registrasi OAuth SIMADU

DataHub membutuhkan dua registrasi mesin yang terpisah:

1. `datahub-simrs-reader`, grant `client_credentials`, scope
   `simrs.indicators.read`. Credential ini dipakai DataHub untuk membaca PHP/SIMRS.
2. `datahub-resource-server`, credential khusus untuk memanggil introspection
   SIMADU. Credential ini tidak dikirim kepada pihak ketiga.

Setiap pihak ketiga juga dibuatkan client tersendiri, misalnya
`dinkes-datahub-reader`, dengan scope `read:dash`.

Konfigurasi introspection DataHub:

```powershell
$env:SIMADU_INTROSPECTION_URL="https://simadu.rsmandalika.com/o/introspect/"
$env:SIMADU_INTROSPECTION_CLIENT_ID="datahub-resource-server"
$env:SIMADU_INTROSPECTION_CLIENT_SECRET="secret-introspection-dari-simadu"
$env:SIMADU_INTROSPECTION_CACHE_SECONDS="30"
```

## API internal dan eksternal

DataHub menyediakan dua kontrak OpenAPI yang terpisah:

- API internal: `/api/internal/v1/`, Swagger `/docs/internal/`.
- API eksternal: `/api/external/v1/`, Swagger `/docs/external/`.

API internal menggunakan session login Django/SSO. API eksternal menggunakan
opaque Bearer Token SIMADU, lalu memeriksa `client_id`, scope, produk API yang
diberikan, masa berlaku grant, dan rate limit client.

Enam produk indikator dibuat otomatis oleh migrasi dengan kode
`indicator-alos`, `indicator-bor`, `indicator-bto`, `indicator-toi`,
`indicator-gdr`, dan `indicator-ndr`. Untuk membuka akses kepada mitra:

1. Buat OAuth client khusus mitra di SIMADU.
2. Buat **Client API eksternal** di Django Admin dengan `client_id` yang sama.
3. Tambahkan hanya **Izin client eksternal** yang disetujui.
4. Atur batas request per menit dan, bila diperlukan, tanggal kedaluwarsa grant.

### Indikator kesehatan rumah sakit

Kontrak indikator kesehatan mengikuti workbook kebutuhan data Dashboard
Kesehatan. Mock SIMRS membagi data bulanan tanpa identitas pasien ke dalam
empat kelompok: kunjungan pasien, 10 penyakit terbanyak, kunjungan wisatawan,
dan jumlah pasien berdasarkan kelompok penyakit.

```json
{
  "period": {"type": "month", "label": "2026-07", "start": "2026-07-01", "end": "2026-07-31", "days": 31},
  "hospital": {"code": "RS-MANDALIKA", "name": "RS Mandalika"},
  "results": [
    {"installation": "outpatient", "payment_status": "bpjs", "count": 120},
    {"installation": "inpatient", "payment_status": "bpjs", "count": 30},
    {"installation": "emergency", "payment_status": "general", "count": 20}
  ]
}
```

Nilai baku `installation`: `outpatient`, `inpatient`, `emergency`. Nilai baku
`payment_status`: `general`, `bpjs`, `private_insurance`, `social_assistance`,
`other`. Kelompok penyakit divalidasi terhadap rentang ICD-10 metadata: kanker
`C00-C96,D00-D48`, jantung `I00-I52`, stroke `I60-I69`, dan uronefrologi
`N00-N39`.

API internal tersedia di `/api/internal/v1/health-indicators/`. API eksternal
tersedia di `/api/external/v1/health-indicators/<code>/` dan memerlukan produk
grant `health-<code>`, misalnya `health-outpatient-visits` atau
`health-cancer-patients`.

Respons asli SIMRS tetap disimpan sebagai snapshot JSON. Salinan kerja pegawai
disimpan sebagai row relasional terpisah untuk kunjungan, penyakit terbanyak,
wisatawan, dan kelompok penyakit. Form verifikasi serta API membaca tabel row
tersebut; pegawai tidak perlu mengubah JSON.

### Mock API untuk tim SIMRS

Dalam mode development (`DJANGO_DEBUG=true`) tersedia mock sumber SIMRS dengan
Swagger di `/docs/mock-simrs/`. Gunakan Bearer Token dari `SIMRS_MOCK_TOKEN`
(default `mock-simrs-token`) dan parameter `tgl_awal` serta `tgl_akhir`.

```text
GET /mock/simrs/v1/visits/
GET /mock/simrs/v1/top-diseases/
GET /mock/simrs/v1/tourist-visits/
GET /mock/simrs/v1/disease-groups/
```

Masing-masing endpoint mengikuti kelompok data pada daftar kebutuhan. File OpenAPI yang dapat dibagikan tersedia di
`docs/simrs_mock_openapi.yaml`. Pada production, autentikasi mock diganti dengan
validasi opaque token SIMADU dan scope `simrs.indicators.read`.
