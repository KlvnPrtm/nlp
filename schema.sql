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
