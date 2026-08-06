# Flow Penggunaan SIMRS DataHub

## 1. Tujuan

SIMRS DataHub menjadi lapisan pemeriksaan antara SIMRS dan pihak ketiga. Database
SIMRS tidak diakses oleh Django. Data diambil oleh aplikasi PHP `refrensi_app`,
dikirim sebagai JSON, dihitung ulang oleh Django, diperiksa pegawai, kemudian
dipublikasikan melalui API setelah disetujui.

## 2. Aliran Data Utama

```mermaid
flowchart LR
    A[(Database SIMRS)] -->|Query internal| B[PHP refrensi_app]
    B -->|JSON + token server| C[Django DataHub]
    C --> D[(Snapshot asli)]
    C --> E[Perhitungan ulang Django]
    D --> F[(Salinan verifikasi)]
    E --> F
    F --> G{Pemeriksaan pegawai}
    G -->|Simpan draf| F
    G -->|Belum valid| H[Koreksi nilai dan catatan]
    H --> G
    G -->|Setujui| I[(Data terverifikasi)]
    I --> J[6 API publik]
    J -->|Bearer Token| K[Aplikasi pihak ketiga]
```

Database SIMRS hanya berkomunikasi dengan PHP. Server Django tidak menyimpan
credential database SIMRS dan tidak membuka koneksi langsung ke database tersebut.

## 3. Isi JSON dari PHP

PHP mengirimkan periode, data dasar, dan hasil perhitungan awal:

```json
{
  "periode": {
    "hari": 30,
    "awal": "2026-06-01",
    "akhir": "2026-06-30"
  },
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

Hasil perhitungan PHP disimpan sebagai pembanding dan tidak langsung
dipublikasikan.

## 4. Proses di Dalam Django

### 4.1 Penerimaan data

1. Petugas memilih bulan laporan.
2. Petugas menekan **Ambil dari SIMRS**.
3. Django memanggil endpoint PHP dengan tanggal awal dan akhir bulan.
4. PHP memvalidasi token server-to-server.
5. PHP menjalankan query internal terhadap SIMRS.
6. PHP mengirim respons JSON.
7. Django memvalidasi struktur dan nilai data dasar.

Jika koneksi gagal atau struktur JSON tidak sesuai, data tidak dibuat dan petugas
mendapatkan pesan kesalahan.

### 4.2 Penyimpanan snapshot asli

Django menyimpan:

- Periode laporan
- Data dasar dari SIMRS
- Enam nilai hasil perhitungan PHP
- Respons JSON asli
- Pengguna yang mengambil data
- Waktu pengambilan

Snapshot ini merupakan bukti data awal dan tidak dapat diedit oleh verifikator.

### 4.3 Perhitungan ulang

Django menghitung indikator hanya dari data dasar:

| Indikator | Rumus |
|---|---|
| ALOS | Hari perawatan ÷ pasien keluar |
| BOR | Hari perawatan ÷ (tempat tidur × hari periode) × 100 |
| BTO | Pasien keluar ÷ tempat tidur |
| TOI | ((tempat tidur × hari periode) − hari perawatan) ÷ pasien keluar |
| GDR | Pasien meninggal ÷ pasien keluar × 1.000 |
| NDR | Meninggal lebih dari 48 jam ÷ pasien keluar × 1.000 |

Nilai hasil PHP dan hasil Django disimpan di kolom yang berbeda. Selisih keduanya
dapat dilihat saat pemeriksaan.

### 4.4 Pembuatan salinan verifikasi

Setelah perhitungan selesai, Django membuat salinan verifikasi. Nilai awal salinan
berasal dari hasil hitung Django, bukan dari nilai hasil hitung PHP.

Pegawai hanya mengubah salinan verifikasi. Snapshot asli, data dasar, hasil PHP,
dan hasil hitung Django tidak berubah.

## 5. Flow Pengguna

### 5.1 Administrator

Dilakukan saat pemasangan atau ketika ada perubahan petugas:

1. Masuk ke menu **Administrasi**.
2. Membuat akun pegawai.
3. Membuat grup, misalnya `Petugas Data` dan `Verifikator`.
4. Memberikan izin mengambil data kepada Petugas Data.
5. Memberikan izin mengubah dan menyetujui hasil kepada Verifikator.
6. Membuat token API untuk aplikasi pihak ketiga.
7. Menyerahkan token melalui saluran yang aman.

### 5.2 Petugas pengambil data

Dilakukan setiap bulan, disarankan pada tanggal 5:

1. Masuk ke aplikasi.
2. Membuka menu **Indikator Rawat Inap**.
3. Memilih bulan yang akan diproses.
4. Menekan **Ambil dari SIMRS**.
5. Menunggu pesan bahwa data berhasil diterima.
6. Memastikan periode dan data dasar tampil di tabel.
7. Menginformasikan kepada verifikator bahwa data siap diperiksa.

Petugas tidak perlu membuka atau menulis JSON.

### 5.3 Verifikator

1. Masuk ke aplikasi.
2. Membuka menu **Indikator Rawat Inap**.
3. Memilih periode dengan status **Sedang diperiksa**.
4. Menekan **Periksa**.
5. Memeriksa data dasar dari SIMRS.
6. Membandingkan nilai PHP dengan nilai hitung Django.
7. Memeriksa enam kolom hasil verifikasi.
8. Jika belum selesai, menekan **Simpan draf**.
9. Jika ada koreksi, mengubah nilai dan menulis alasan pada kolom catatan.
10. Jika seluruh nilai valid, menekan **Setujui dan publikasikan**.

Setiap perubahan, pengguna, dan waktu perubahan dicatat dalam audit trail.

### 5.4 Aplikasi pihak ketiga

1. Administrator SIMADU membuat OAuth client khusus untuk aplikasi pihak ketiga.
2. Pihak ketiga meminta opaque access token ke token endpoint SIMADU dengan grant
   `client_credentials` dan scope `read:dash`.
3. Pihak ketiga memanggil salah satu endpoint DataHub dengan Bearer Token.
4. DataHub mengintrospeksi token kepada SIMADU.
5. DataHub memeriksa `active`, `exp`, `client_id`, dan scope.
6. Django mengambil data dari tabel hasil verifikasi.
7. Hanya periode berstatus **Terverifikasi** yang dikembalikan.

Contoh:

```http
GET /api/external/v1/indicators/bor/?tahun=2026&bulan=6
Authorization: Bearer opaque-access-token-dari-simadu
```

## 6. Status dan Hak Publikasi

```mermaid
stateDiagram-v2
    [*] --> BelumAda: Periode belum diambil
    BelumAda --> SedangDiperiksa: JSON diterima dan salinan dibuat
    SedangDiperiksa --> SedangDiperiksa: Simpan draf/koreksi
    SedangDiperiksa --> Terverifikasi: Verifikator menyetujui
    Terverifikasi --> API: Tersedia untuk pihak ketiga
```

| Status | Dapat diedit | Tampil di API publik |
|---|---:|---:|
| Belum ada | Tidak | Tidak |
| Sedang diperiksa | Ya, pada salinan | Tidak |
| Terverifikasi | Melalui proses verifikasi ulang | Ya |

## 7. Penanganan Perbedaan Nilai

Jika hasil PHP dan Django berbeda:

1. Jangan langsung menyetujui data.
2. Periksa data dasar dan jumlah hari periode.
3. Pastikan definisi pasien keluar dan kematian lebih dari 48 jam sama.
4. Pastikan jumlah tempat tidur hanya mencakup tempat tidur aktif sesuai kebijakan.
5. Catat penyebab perbedaan.
6. Koreksi salinan verifikasi jika sudah diperoleh nilai yang sah.
7. Setujui setelah pemeriksaan selesai.

Perbedaan hasil bukan berarti snapshot asli diubah. Semua versi tetap tersedia
untuk audit.

## 8. Sinkronisasi Ulang

Jika periode yang sama diambil kembali:

- Snapshot sumber diperbarui dengan respons PHP terbaru.
- Perhitungan Django dijalankan kembali.
- Hasil verifikasi yang sudah dibuat tidak ditimpa otomatis.
- Verifikator perlu menilai apakah perubahan sumber membutuhkan verifikasi ulang.

Untuk pengoperasian produksi, sinkronisasi ulang terhadap periode yang sudah
terverifikasi sebaiknya dilakukan oleh administrator atau petugas berwenang.

## 9. Batas Keamanan

- Endpoint PHP menggunakan HTTPS.
- Endpoint PHP menggunakan opaque token SIMADU dengan scope
  `simrs.indicators.read`.
- Endpoint PHP sebaiknya hanya menerima IP server Django.
- JSON tidak memuat credential database.
- JSON enam indikator sebaiknya hanya memuat data agregat, bukan identitas pasien.
- Token API publik memiliki client dan scope berbeda dari token antara Django
  dan PHP.
- DataHub memvalidasi token pihak ketiga melalui introspection SIMADU dengan
  cache maksimal 60 detik.
- Token tidak ditulis di source code atau log aplikasi.
- Database SIMRS tidak dibuka ke internet maupun ke server pihak ketiga.

## 10. Ringkasan Tanggung Jawab

| Komponen/Pengguna | Tanggung jawab |
|---|---|
| SIMRS | Menyimpan data operasional rumah sakit |
| PHP `refrensi_app` | Query internal dan menyediakan JSON agregat |
| Django DataHub | Arsip, hitung ulang, salinan verifikasi, audit, dan API |
| Petugas Data | Mengambil data sesuai periode |
| Verifikator | Memeriksa, mengoreksi, mencatat alasan, dan menyetujui |
| Administrator | Akun, izin, konfigurasi, dan token |
| Pihak ketiga | Mengonsumsi data terverifikasi menggunakan token |
