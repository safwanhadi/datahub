-- Pencarian metadata untuk MySQL/MariaDB, bukan query agregasi final.
-- Pilih database SIMRS yang benar terlebih dahulu. Tidak membaca isi pasien.
-- Sesuaikan kata kunci dengan penamaan lokal; hasil bukan pemetaan otomatis.
SELECT
    TABLE_NAME AS candidate_table,
    COLUMN_NAME AS candidate_column,
    DATA_TYPE,
    IS_NULLABLE,
    COLUMN_KEY
FROM INFORMATION_SCHEMA.COLUMNS
WHERE TABLE_SCHEMA = DATABASE()
  AND (
    LOWER(TABLE_NAME) REGEXP 'maternal|perinatal|obstetri|kebidanan|bersalin|persalinan|partus|bayi|neonat|kelahiran|kematian|diagnos|rujuk|registrasi|rawat_inap'
    OR LOWER(COLUMN_NAME) REGEXP 'hamil|gestasi|gestation|gravid|partus|persalinan|lahir|birth|mati|death|nifas|puerper|icd|diagnos|rujuk|referral|tgl_masuk|tgl_keluar'
  )
ORDER BY TABLE_NAME, ORDINAL_POSITION;

-- Relasi FK yang benar-benar dideklarasikan. Relasi aplikasi tanpa FK tidak
-- akan tercantum; telusuri model aplikasi atau dokumentasi SIMRS bila perlu.
SELECT
    TABLE_NAME,
    COLUMN_NAME,
    REFERENCED_TABLE_NAME,
    REFERENCED_COLUMN_NAME
FROM INFORMATION_SCHEMA.KEY_COLUMN_USAGE
WHERE TABLE_SCHEMA = DATABASE()
  AND REFERENCED_TABLE_NAME IS NOT NULL
ORDER BY TABLE_NAME, COLUMN_NAME;
