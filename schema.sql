-- ============================================================
-- SiPadu — Schema Database
-- Jalankan sekali: mysql -u root -p < schema.sql
-- ============================================================

CREATE DATABASE IF NOT EXISTS sipadu CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE sipadu;

-- Tabel utama: setiap pengaduan yang masuk
CREATE TABLE IF NOT EXISTS pengaduan (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    teks            TEXT NOT NULL,
    kategori        VARCHAR(50),
    instansi        VARCHAR(100),
    urgensi         VARCHAR(30),
    urgensi_display VARCHAR(50),
    urgensi_color   VARCHAR(20),    
    urgensi_icon    VARCHAR(10),
    urgensi_priority TINYINT,
    kat_confidence  FLOAT,
    urg_confidence  FLOAT,
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Kategori dinamis untuk panel admin dan mapping instansi
CREATE TABLE IF NOT EXISTS kategori (
    id          INT AUTO_INCREMENT PRIMARY KEY,
    slug        VARCHAR(80) NOT NULL UNIQUE,
    nama        VARCHAR(120) NOT NULL,
    instansi    VARCHAR(160) NOT NULL,
    aktif       TINYINT(1) DEFAULT 1,
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at  DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);

INSERT INTO kategori (slug, nama, instansi, aktif) VALUES
('administrasi', 'Administrasi', 'Dinas Kependudukan dan Catatan Sipil', 1),
('infrastruktur', 'Infrastruktur', 'Dinas Pekerjaan Umum', 1),
('keamanan', 'Keamanan', 'Satuan Polisi Pamong Praja', 1),
('kebersihan', 'Kebersihan', 'Dinas Lingkungan Hidup', 1),
('kesehatan', 'Kesehatan', 'Dinas Kesehatan', 1)
ON DUPLICATE KEY UPDATE slug = slug;

-- Riwayat validasi dataset dan status training
CREATE TABLE IF NOT EXISTS training_history (
    id            INT AUTO_INCREMENT PRIMARY KEY,
    filename      VARCHAR(255),
    total_rows    INT DEFAULT 0,
    valid_rows    INT DEFAULT 0,
    invalid_rows  INT DEFAULT 0,
    status        VARCHAR(40) DEFAULT 'divalidasi',
    message       TEXT,
    created_at    DATETIME DEFAULT CURRENT_TIMESTAMP,
    started_at    DATETIME NULL,
    finished_at   DATETIME NULL
);

-- View: ringkasan per kategori
CREATE OR REPLACE VIEW stat_kategori AS
SELECT
    kategori,
    instansi,
    COUNT(*) AS total,
    ROUND(AVG(kat_confidence), 2) AS avg_confidence
FROM pengaduan
GROUP BY kategori, instansi
ORDER BY total DESC;

-- View: ringkasan per urgensi
CREATE OR REPLACE VIEW stat_urgensi AS
SELECT
    urgensi,
    urgensi_display,
    urgensi_icon,
    urgensi_color,
    urgensi_priority,
    COUNT(*) AS total
FROM pengaduan
GROUP BY urgensi, urgensi_display, urgensi_icon, urgensi_color, urgensi_priority
ORDER BY urgensi_priority DESC;

-- View: tren per hari (30 hari terakhir)
CREATE OR REPLACE VIEW stat_harian AS
SELECT
    DATE(created_at) AS tanggal,
    COUNT(*) AS total,
    SUM(urgensi_priority >= 3) AS urgen_count
FROM pengaduan
WHERE created_at >= DATE_SUB(NOW(), INTERVAL 30 DAY)
GROUP BY DATE(created_at)
ORDER BY tanggal ASC;

-- View: tren per minggu
CREATE OR REPLACE VIEW stat_mingguan AS
SELECT
    YEARWEEK(created_at, 1) AS minggu,
    MIN(DATE(created_at)) AS mulai,
    COUNT(*) AS total,
    SUM(urgensi_priority >= 3) AS urgen_count
FROM pengaduan
WHERE created_at >= DATE_SUB(NOW(), INTERVAL 12 WEEK)
GROUP BY YEARWEEK(created_at, 1)
ORDER BY minggu ASC;
