"""
app.py — Flask backend + MySQL untuk SiPadu
Letakkan di CobaLagi/, sejajar dengan folder model_indobert_*

Install deps:
    pip install flask flask-cors torch transformers pandas mysql-connector-python

Jalankan:
    python app.py
"""

from flask import Flask, request, jsonify, send_from_directory, Response
from flask_cors import CORS
import torch
from transformers import AutoTokenizer, AutoModelForSequenceClassification
import mysql.connector
from mysql.connector import pooling
import csv
import io
import json
import os
import re
import sys
from datetime import datetime
from werkzeug.utils import secure_filename

if sys.stdout is None:
    sys.stdout = open(os.devnull, "w", encoding="utf-8")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w", encoding="utf-8")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

app = Flask(__name__, static_folder="static")
CORS(app)

# ── KONFIGURASI MODEL ─────────────────────────────────────
FOLDER_MODEL_KAT = "./model_indobert_kategori"
FOLDER_MODEL_URG = "./model_indobert_urgensi"
MAX_LEN = 128

LABELS_KATEGORI = ["administrasi", "infrastruktur", "keamanan", "kebersihan", "kesehatan"]
LABELS_URGENSI  = ["biasa", "sangat_urgen", "tidak_urgen", "urgen"]

INSTANSI_MAP = {
    "infrastruktur": "Dinas Pekerjaan Umum",
    "kebersihan":    "Dinas Lingkungan Hidup",
    "kesehatan":     "Dinas Kesehatan",
    "administrasi":  "Dinas Kependudukan dan Catatan Sipil",
    "keamanan":      "Satuan Polisi Pamong Praja",
}

DEFAULT_CATEGORIES = [
    {"slug": slug, "nama": slug.replace("_", " ").title(), "instansi": instansi}
    for slug, instansi in INSTANSI_MAP.items()
]

URGENSI_INFO = {
    "sangat_urgen": {"label": "Sangat Urgen", "color": "red",    "icon": "🔴", "priority": 4},
    "urgen":        {"label": "Urgen",         "color": "yellow", "icon": "🟡", "priority": 3},
    "biasa":        {"label": "Biasa",          "color": "green",  "icon": "🟢", "priority": 2},
    "tidak_urgen":  {"label": "Tidak Urgen",    "color": "gray",   "icon": "⚪", "priority": 1},
}

TRAINING_STATUS = {
    "state": "idle",
    "progress": 0,
    "message": "Belum ada proses training berjalan.",
    "updated_at": None,
    "current_job_id": None,
}

SECURITY_TERMS = (
    "begal", "dibegal", "jambret", "dijambret", "curanmor", "pencurian",
    "maling", "kemalingan", "perampokan", "perampok", "rampok", "dirampok",
    "pembunuhan", "dibunuh", "bunuh", "penyerangan", "diserang", "senjata",
)

HIGH_URGENCY_SECURITY_TERMS = (
    "dibegal", "begal", "perampokan", "perampok", "rampok", "dirampok",
    "pembunuhan", "dibunuh", "bunuh", "senjata", "penyerangan", "diserang",
)

# ── KONFIGURASI DATABASE ──────────────────────────────────
DB_CONFIG = {
    "host":     "localhost",
    "port":     3306,
    "user":     "root",       # ← ganti sesuai MySQL kamu
    "password": "1234",           # ← ganti sesuai MySQL kamu
    "database": "sipadu",
    "charset":  "utf8mb4",
}

db_pool = None

def init_db_pool():
    global db_pool
    try:
        db_pool = pooling.MySQLConnectionPool(
            pool_name="sipadu_pool",
            pool_size=5,
            **DB_CONFIG
        )
        print("[OK] Database pool siap.")
        ensure_support_tables()
        return True
    except Exception as e:
        print(f"[ERROR] Gagal konek database: {e}")
        return False

def get_db():
    return db_pool.get_connection()

def execute_write(sql, params=None):
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(sql, params or ())
        conn.commit()
        new_id = cur.lastrowid
        cur.close()
        return new_id
    finally:
        conn.close()

def ensure_support_tables():
    if not db_pool:
        return

    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS kategori (
                id INT AUTO_INCREMENT PRIMARY KEY,
                slug VARCHAR(80) NOT NULL UNIQUE,
                nama VARCHAR(120) NOT NULL,
                instansi VARCHAR(160) NOT NULL,
                aktif TINYINT(1) DEFAULT 1,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
            ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS training_history (
                id INT AUTO_INCREMENT PRIMARY KEY,
                filename VARCHAR(255),
                total_rows INT DEFAULT 0,
                valid_rows INT DEFAULT 0,
                invalid_rows INT DEFAULT 0,
                status VARCHAR(40) DEFAULT 'divalidasi',
                message TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                started_at DATETIME NULL,
                finished_at DATETIME NULL
            ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
        """)
        for item in DEFAULT_CATEGORIES:
            cur.execute(
                """
                INSERT INTO kategori (slug, nama, instansi, aktif)
                VALUES (%s, %s, %s, 1)
                ON DUPLICATE KEY UPDATE slug = slug
                """,
                (item["slug"], item["nama"], item["instansi"]),
            )
        conn.commit()
        cur.close()
    finally:
        conn.close()

def slugify_category(value):
    slug = re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower())
    slug = re.sub(r"_+", "_", slug).strip("_")
    return slug[:80]

def title_label(value):
    return str(value or "-").replace("_", " ").title()

def get_category_agency(kat_label):
    if db_pool:
        try:
            row = query_one(
                "SELECT instansi FROM kategori WHERE slug = %s AND aktif = 1",
                (kat_label,),
            )
            if row.get("instansi"):
                return row["instansi"]
        except Exception:
            pass
    return INSTANSI_MAP.get(kat_label, "-")

def normalize_category_row(row):
    return {
        "id": row.get("id"),
        "slug": row.get("slug"),
        "nama": row.get("nama") or title_label(row.get("slug")),
        "instansi": row.get("instansi") or "-",
        "aktif": bool(row.get("aktif", 1)),
        "jumlah_pengaduan": int(row.get("jumlah_pengaduan") or 0),
        "created_at": str(row.get("created_at") or ""),
        "updated_at": str(row.get("updated_at") or ""),
    }

# ── MODEL STATE ───────────────────────────────────────────
models = {
    "kategori": {"tokenizer": None, "model": None, "id2label": None},
    "urgensi":  {"tokenizer": None, "model": None, "id2label": None},
    "loaded": False,
    "error": None,
}

def load_model_once(folder, label_list):
    if not os.path.exists(folder):
        raise FileNotFoundError(f"Folder model tidak ditemukan: {folder}")
    tokenizer = AutoTokenizer.from_pretrained(folder)
    model = AutoModelForSequenceClassification.from_pretrained(folder)
    model.eval()
    config_labels = getattr(model.config, "id2label", {}) or {}
    has_real_labels = all(
        not str(label).startswith("LABEL_") for label in config_labels.values()
    )
    if config_labels and has_real_labels:
        id2label = {int(i): label for i, label in config_labels.items()}
    else:
        sorted_labels = sorted(label_list)
        id2label = {i: label for i, label in enumerate(sorted_labels)}
    return tokenizer, model, id2label

def ensure_models_loaded():
    if models["loaded"]:
        return True
    if models["error"]:
        return False
    try:
        tok_kat, mdl_kat, id2kat = load_model_once(FOLDER_MODEL_KAT, LABELS_KATEGORI)
        models["kategori"] = {"tokenizer": tok_kat, "model": mdl_kat, "id2label": id2kat}
        tok_urg, mdl_urg, id2urg = load_model_once(FOLDER_MODEL_URG, LABELS_URGENSI)
        models["urgensi"]  = {"tokenizer": tok_urg, "model": mdl_urg, "id2label": id2urg}
        models["loaded"] = True
        print("[OK] Model siap.")
        return True
    except Exception as e:  
        models["error"] = str(e)
        print(f"[ERROR] Gagal load model: {e}")
        return False

def predict_single(text, mtype):
    tokenizer = models[mtype]["tokenizer"]
    model     = models[mtype]["model"]
    id2label  = models[mtype]["id2label"]
    device    = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model.to(device)

    encoding = tokenizer(
        [text], truncation=True, padding=True,
        max_length=MAX_LEN, return_tensors="pt"
    ).to(device)

    with torch.no_grad():
        outputs = model(**encoding)
        logits  = outputs.logits[0]
        probs   = torch.softmax(logits, dim=0).cpu().numpy()
        pred_id = int(torch.argmax(logits).cpu())

    label = id2label.get(str(pred_id), id2label.get(pred_id, f"label_{pred_id}"))
    confidence = float(probs[pred_id])
    all_probs  = {
        id2label.get(str(i), id2label.get(i, f"label_{i}")): round(float(p) * 100, 1)
        for i, p in enumerate(probs)
    }
    return label, confidence, all_probs

def contains_term(text, terms):
    normalized = text.lower()
    return any(re.search(rf"\b{re.escape(term)}\b", normalized) for term in terms)

def apply_domain_guard(text, kat_label, kat_conf, urg_label, urg_conf):
    """Koreksi konservatif untuk kata kriminal eksplisit yang sering pendek."""
    guard_applied = False

    if contains_term(text, SECURITY_TERMS):
        kat_label = "keamanan"
        kat_conf = max(kat_conf, 0.92)
        guard_applied = True

    if contains_term(text, HIGH_URGENCY_SECURITY_TERMS):
        current_priority = URGENSI_INFO.get(urg_label, {}).get("priority", 0)
        if current_priority < URGENSI_INFO["urgen"]["priority"]:
            urg_label = "urgen"
            urg_conf = max(urg_conf, 0.88)
            guard_applied = True

    return kat_label, kat_conf, urg_label, urg_conf, guard_applied

def rebalance_probs(probs, forced_label, forced_conf):
    if forced_label not in probs:
        return probs

    forced_pct = round(forced_conf * 100, 1)
    remaining = max(0.0, 100.0 - forced_pct)
    other_total = sum(value for label, value in probs.items() if label != forced_label)
    if other_total <= 0:
        return {label: (forced_pct if label == forced_label else 0.0) for label in probs}

    return {
        label: forced_pct if label == forced_label else round((value / other_total) * remaining, 1)
        for label, value in probs.items()
    }
    
# ── DB HELPERS ────────────────────────────────────────────
def save_pengaduan(teks, kat_label, kat_conf, urg_label, urg_conf):
    urg_meta = URGENSI_INFO.get(urg_label, {"label": urg_label, "color": "gray", "icon": "?", "priority": 0})
    instansi = get_category_agency(kat_label)
    sql = """
        INSERT INTO pengaduan
            (teks, kategori, instansi, urgensi, urgensi_display,
             urgensi_color, urgensi_icon, urgensi_priority,
             kat_confidence, urg_confidence)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
    """
    vals = (
        teks, kat_label, instansi, urg_label, urg_meta["label"],
        urg_meta["color"], urg_meta["icon"], urg_meta["priority"],
        round(kat_conf * 100, 2), round(urg_conf * 100, 2)
    )
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(sql, vals)
        conn.commit()
        new_id = cur.lastrowid
        cur.close()
        return new_id
    finally:
        conn.close()

def query_dict(sql, params=None):
    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(sql, params or ())
        rows = cur.fetchall()
        cur.close()
        return rows
    finally:
        conn.close()

def query_one(sql, params=None):
    rows = query_dict(sql, params)
    return rows[0] if rows else {}

def get_all_pengaduan_rows():
    return query_dict("""
        SELECT id, teks, kategori, instansi, urgensi, urgensi_display,
               kat_confidence, urg_confidence, created_at
        FROM pengaduan
        ORDER BY created_at DESC
    """)

def format_dt(value):
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    return str(value or "")

def csv_export(rows):
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "ID",
        "Teks Pengaduan",
        "Kategori",
        "Instansi",
        "Urgensi",
        "Kepercayaan Kategori",
        "Kepercayaan Urgensi",
        "Waktu Masuk",
    ])
    for row in rows:
        writer.writerow([
            row.get("id"),
            row.get("teks"),
            row.get("kategori"),
            row.get("instansi"),
            row.get("urgensi_display") or row.get("urgensi"),
            row.get("kat_confidence"),
            row.get("urg_confidence"),
            format_dt(row.get("created_at")),
        ])
    return "\ufeff" + output.getvalue()

def pdf_escape(value):
    text = str(value or "").encode("latin-1", "replace").decode("latin-1")
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")

def wrap_text(value, width=92):
    text = re.sub(r"\s+", " ", str(value or "-")).strip()
    lines = []
    while len(text) > width:
        split_at = text.rfind(" ", 0, width)
        if split_at <= 0:
            split_at = width
        lines.append(text[:split_at].strip())
        text = text[split_at:].strip()
    lines.append(text)
    return lines

def build_pdf(rows):
    lines = [
        "SiPadu - Data Pengaduan",
        f"Dibuat: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"Total data: {len(rows)}",
        "",
    ]
    for row in rows:
        lines.append(f"ID {row.get('id')} | {format_dt(row.get('created_at'))}")
        lines.append(f"Kategori: {title_label(row.get('kategori'))} | Instansi: {row.get('instansi') or '-'}")
        lines.append(f"Urgensi: {row.get('urgensi_display') or title_label(row.get('urgensi'))}")
        lines.append(f"Kepercayaan: kategori {row.get('kat_confidence') or '-'}% | urgensi {row.get('urg_confidence') or '-'}%")
        wrapped_text = wrap_text(row.get("teks"))
        for idx, wrapped in enumerate(wrapped_text):
            lines.append(f"Teks: {wrapped}" if idx == 0 else f"      {wrapped}")
        lines.append("")

    pages = [lines[i:i + 42] for i in range(0, len(lines), 42)] or [["SiPadu - Data Pengaduan"]]
    objects = [None]
    objects.append("<< /Type /Catalog /Pages 2 0 R >>")
    objects.append(None)
    objects.append("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    kids = []

    for page_lines in pages:
        content = ["BT", "/F1 9 Tf", "50 800 Td", "13 TL"]
        for line in page_lines:
            content.append(f"({pdf_escape(line)}) Tj")
            content.append("T*")
        content.append("ET")
        content_text = "\n".join(content)
        content_bytes = content_text.encode("latin-1", "replace")
        content_id = len(objects)
        objects.append(f"<< /Length {len(content_bytes)} >>\nstream\n{content_text}\nendstream")
        page_id = len(objects)
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
            f"/Resources << /Font << /F1 3 0 R >> >> /Contents {content_id} 0 R >>"
        )
        kids.append(f"{page_id} 0 R")

    objects[2] = f"<< /Type /Pages /Kids [{' '.join(kids)}] /Count {len(kids)} >>"

    pdf = "%PDF-1.4\n"
    offsets = [0]
    for obj_id in range(1, len(objects)):
        offsets.append(len(pdf.encode("latin-1")))
        pdf += f"{obj_id} 0 obj\n{objects[obj_id]}\nendobj\n"
    xref_offset = len(pdf.encode("latin-1"))
    pdf += f"xref\n0 {len(objects)}\n0000000000 65535 f \n"
    for offset in offsets[1:]:
        pdf += f"{offset:010d} 00000 n \n"
    pdf += f"trailer\n<< /Size {len(objects)} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF"
    return pdf.encode("latin-1", "replace")

def validate_dataset_file(file_storage):
    filename = secure_filename(file_storage.filename or "")
    if not filename.lower().endswith(".csv"):
        return None, {"error": "File harus berformat CSV."}

    raw = file_storage.read()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")

    reader = csv.DictReader(io.StringIO(text))
    fieldnames = reader.fieldnames or []
    required = {"teks", "kategori", "urgensi"}
    missing = sorted(required - set(fieldnames))
    if missing:
        return None, {
            "error": "Kolom wajib belum lengkap.",
            "missing_columns": missing,
            "columns": fieldnames,
        }

    preview = []
    invalid_rows = []
    total_rows = 0
    valid_rows = 0

    for index, row in enumerate(reader, start=2):
        total_rows += 1
        reasons = []
        teks = (row.get("teks") or "").strip()
        kategori = (row.get("kategori") or "").strip()
        urgensi = (row.get("urgensi") or "").strip()
        if not teks:
            reasons.append("teks kosong")
        if not kategori:
            reasons.append("kategori kosong")
        if not urgensi:
            reasons.append("urgensi kosong")
        if reasons:
            invalid_rows.append({"baris": index, "alasan": ", ".join(reasons), "data": row})
            continue
        valid_rows += 1
        if len(preview) < 10:
            preview.append({"teks": teks, "kategori": kategori, "urgensi": urgensi})

    result = {
        "filename": filename,
        "columns": fieldnames,
        "required_columns": ["teks", "kategori", "urgensi"],
        "total_rows": total_rows,
        "valid_rows": valid_rows,
        "invalid_rows": invalid_rows[:25],
        "invalid_count": len(invalid_rows),
        "preview": preview,
        "valid": total_rows > 0 and len(invalid_rows) == 0,
    }
    return result, None

# ── ROUTES ────────────────────────────────────────────────
@app.route("/")
def index():
    return send_from_directory("static", "index.html")

@app.route("/dashboard")
def dashboard():
    return send_from_directory("static", "dashboard.html")

@app.route("/api/status")
def status():
    ensure_models_loaded()
    return jsonify({
        "loaded": models["loaded"],
        "error":  models["error"],
        "device": "cuda" if torch.cuda.is_available() else "cpu",
        "db":     db_pool is not None,
    })

@app.route("/api/predict", methods=["POST"])
def predict():
    data = request.get_json(force=True)
    text = (data.get("text") or "").strip()

    if not text or len(text) < 5:
        return jsonify({"error": "Teks terlalu pendek (minimal 5 karakter)."}), 400
    if not ensure_models_loaded():
        return jsonify({"error": f"Model gagal dimuat: {models['error']}"}), 503

    try:
        kat_label, kat_conf, kat_probs = predict_single(text, "kategori")
        urg_label, urg_conf, urg_probs = predict_single(text, "urgensi")
        kat_label, kat_conf, urg_label, urg_conf, guard_applied = apply_domain_guard(
            text, kat_label, kat_conf, urg_label, urg_conf
        )
        if guard_applied:
            kat_probs = rebalance_probs(kat_probs, kat_label, kat_conf)
            urg_probs = rebalance_probs(urg_probs, urg_label, urg_conf)

        instansi = get_category_agency(kat_label)
        urg_meta = URGENSI_INFO.get(urg_label, {"label": urg_label, "color": "gray", "icon": "?", "priority": 0})

        new_id = None
        if db_pool:
            new_id = save_pengaduan(text, kat_label, kat_conf, urg_label, urg_conf)

        return jsonify({
            "id":        new_id,
            "teks":      text,
            "timestamp": datetime.now().strftime("%d %b %Y, %H:%M"),
            "kategori": {
                "label":         kat_label,
                "confidence":    round(kat_conf * 100, 1),
                "probabilities": kat_probs,
            },
            "instansi": instansi,
            "urgensi": {
                "label":         urg_label,
                "display":       urg_meta["label"],
                "color":         urg_meta["color"],
                "icon":          urg_meta["icon"],
                "priority":      urg_meta["priority"],
                "confidence":    round(urg_conf * 100, 1),
                "probabilities": urg_probs,
            },
            "saved": new_id is not None,
            "guard_applied": guard_applied,
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/stats")
def stats():
    if not db_pool:
        return jsonify({"error": "Database tidak tersambung."}), 503
    try:
        total    = query_one("SELECT COUNT(*) AS n FROM pengaduan")["n"] or 0
        kategori = query_dict("SELECT * FROM stat_kategori")
        urgensi  = query_dict("SELECT * FROM stat_urgensi")
        harian   = query_dict("SELECT * FROM stat_harian")
        mingguan = query_dict("SELECT * FROM stat_mingguan")

        for row in harian:
            if row.get("tanggal"):
                row["tanggal"] = str(row["tanggal"])
        for row in mingguan:
            if row.get("mulai"):
                row["mulai"] = str(row["mulai"])

        return jsonify({
            "total":    total,
            "kategori": kategori,
            "urgensi":  urgensi,
            "harian":   harian,
            "mingguan": mingguan,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/riwayat")
def riwayat():
    if not db_pool:
        return jsonify({"error": "Database tidak tersambung."}), 503
    try:
        page   = max(int(request.args.get("page", 1)), 1)
        limit  = min(max(int(request.args.get("limit", 20)), 1), 100)
        search = (request.args.get("q") or "").strip()
        kategori = (request.args.get("kategori") or "").strip()
        urgensi = (request.args.get("urgensi") or "").strip()
        instansi = (request.args.get("instansi") or "").strip()
        date_from = (request.args.get("date_from") or "").strip()
        date_to = (request.args.get("date_to") or "").strip()
        offset = (page - 1) * limit

        clauses = []
        params = []
        if search:
            clauses.append("(teks LIKE %s OR kategori LIKE %s OR urgensi LIKE %s OR instansi LIKE %s)")
            like = f"%{search}%"
            params.extend([like, like, like, like])
        if kategori:
            clauses.append("kategori = %s")
            params.append(kategori)
        if urgensi:
            clauses.append("urgensi = %s")
            params.append(urgensi)
        if instansi:
            clauses.append("instansi = %s")
            params.append(instansi)
        if re.match(r"^\d{4}-\d{2}-\d{2}$", date_from):
            clauses.append("created_at >= %s")
            params.append(f"{date_from} 00:00:00")
        if re.match(r"^\d{4}-\d{2}-\d{2}$", date_to):
            clauses.append("created_at <= %s")
            params.append(f"{date_to} 23:59:59")

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""

        rows  = query_dict(
            f"SELECT * FROM pengaduan {where} ORDER BY created_at DESC LIMIT %s OFFSET %s",
            (*params, limit, offset)
        )
        total = query_one(f"SELECT COUNT(*) AS n FROM pengaduan {where}", params)["n"] or 0

        for row in rows:
            if row.get("created_at"):
                row["created_at"] = row["created_at"].strftime("%d %b %Y, %H:%M")

        return jsonify({"data": rows, "total": total, "page": page, "limit": limit})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/export")
def export_data():
    if not db_pool:
        return jsonify({"error": "Database tidak tersambung."}), 503
    export_format = (request.args.get("format") or "csv").lower()
    try:
        rows = get_all_pengaduan_rows()
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        if export_format == "pdf":
            pdf = build_pdf(rows)
            return Response(
                pdf,
                mimetype="application/pdf",
                headers={"Content-Disposition": f"attachment; filename=sipadu-pengaduan-{timestamp}.pdf"},
            )
        if export_format != "csv":
            return jsonify({"error": "Format ekspor tidak didukung."}), 400
        csv_data = csv_export(rows)
        return Response(
            csv_data,
            mimetype="text/csv; charset=utf-8",
            headers={"Content-Disposition": f"attachment; filename=sipadu-pengaduan-{timestamp}.csv"},
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/categories", methods=["GET", "POST"])
def categories():
    if request.method == "GET":
        if not db_pool:
            return jsonify({
                "data": [
                    {
                        "id": index + 1,
                        "slug": item["slug"],
                        "nama": item["nama"],
                        "instansi": item["instansi"],
                        "aktif": True,
                        "jumlah_pengaduan": 0,
                    }
                    for index, item in enumerate(DEFAULT_CATEGORIES)
                ],
                "source": "fallback",
            })
        try:
            rows = query_dict("""
                SELECT k.id, k.slug, k.nama, k.instansi, k.aktif,
                       k.created_at, k.updated_at,
                       COALESCE(COUNT(p.id), 0) AS jumlah_pengaduan
                FROM kategori k
                LEFT JOIN pengaduan p
                    ON CONVERT(p.kategori USING utf8mb4) COLLATE utf8mb4_unicode_ci = k.slug COLLATE utf8mb4_unicode_ci
                GROUP BY k.id, k.slug, k.nama, k.instansi, k.aktif, k.created_at, k.updated_at
                ORDER BY k.aktif DESC, k.nama ASC
            """)
            return jsonify({"data": [normalize_category_row(row) for row in rows]})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    if not db_pool:
        return jsonify({"error": "Database tidak tersambung."}), 503
    data = request.get_json(force=True)
    nama = (data.get("nama") or "").strip()
    instansi = (data.get("instansi") or "").strip()
    slug = slugify_category(data.get("slug") or nama)
    aktif = 1 if data.get("aktif", True) else 0
    if len(nama) < 2:
        return jsonify({"error": "Nama kategori minimal 2 karakter."}), 400
    if len(instansi) < 2:
        return jsonify({"error": "Instansi terkait wajib diisi."}), 400
    if not slug:
        return jsonify({"error": "Slug kategori tidak valid."}), 400
    try:
        new_id = execute_write(
            "INSERT INTO kategori (slug, nama, instansi, aktif) VALUES (%s, %s, %s, %s)",
            (slug, nama, instansi, aktif),
        )
        row = query_one("SELECT *, 0 AS jumlah_pengaduan FROM kategori WHERE id = %s", (new_id,))
        return jsonify({"message": "Kategori berhasil ditambahkan.", "data": normalize_category_row(row)}), 201
    except mysql.connector.IntegrityError:
        return jsonify({"error": "Kategori dengan nama atau slug tersebut sudah ada."}), 409
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/categories/<int:category_id>", methods=["PUT", "DELETE"])
def category_detail(category_id):
    if not db_pool:
        return jsonify({"error": "Database tidak tersambung."}), 503
    existing = query_one("SELECT * FROM kategori WHERE id = %s", (category_id,))
    if not existing:
        return jsonify({"error": "Kategori tidak ditemukan."}), 404

    if request.method == "PUT":
        data = request.get_json(force=True)
        nama = (data.get("nama") or "").strip()
        instansi = (data.get("instansi") or "").strip()
        aktif = 1 if data.get("aktif", True) else 0
        if len(nama) < 2:
            return jsonify({"error": "Nama kategori minimal 2 karakter."}), 400
        if len(instansi) < 2:
            return jsonify({"error": "Instansi terkait wajib diisi."}), 400
        try:
            execute_write(
                "UPDATE kategori SET nama = %s, instansi = %s, aktif = %s WHERE id = %s",
                (nama, instansi, aktif, category_id),
            )
            row = query_one("""
                SELECT k.*, COALESCE(COUNT(p.id), 0) AS jumlah_pengaduan
                FROM kategori k
                LEFT JOIN pengaduan p
                    ON CONVERT(p.kategori USING utf8mb4) COLLATE utf8mb4_unicode_ci = k.slug COLLATE utf8mb4_unicode_ci
                WHERE k.id = %s
                GROUP BY k.id, k.slug, k.nama, k.instansi, k.aktif, k.created_at, k.updated_at
            """, (category_id,))
            return jsonify({"message": "Kategori berhasil diperbarui.", "data": normalize_category_row(row)})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    hard_delete = request.args.get("hard") == "1"
    count = query_one(
        "SELECT COUNT(*) AS n FROM pengaduan WHERE kategori = %s",
        (existing.get("slug"),),
    ).get("n", 0)
    try:
        if hard_delete and not count:
            execute_write("DELETE FROM kategori WHERE id = %s", (category_id,))
            return jsonify({"message": "Kategori berhasil dihapus.", "deleted": True})
        execute_write("UPDATE kategori SET aktif = 0 WHERE id = %s", (category_id,))
        return jsonify({"message": "Kategori berhasil dinonaktifkan.", "deleted": False})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/dataset/upload", methods=["POST"])
def dataset_upload():
    if "file" not in request.files:
        return jsonify({"error": "File CSV belum dipilih."}), 400
    result, error = validate_dataset_file(request.files["file"])
    if error:
        return jsonify(error), 400

    job_id = None
    if db_pool:
        status_text = "divalidasi" if result["valid"] else "gagal_validasi"
        message = "Dataset valid dan siap dipakai." if result["valid"] else "Dataset masih memiliki baris tidak valid."
        job_id = execute_write(
            """
            INSERT INTO training_history
                (filename, total_rows, valid_rows, invalid_rows, status, message)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (
                result["filename"],
                result["total_rows"],
                result["valid_rows"],
                result["invalid_count"],
                status_text,
                message,
            ),
        )
    result["job_id"] = job_id
    return jsonify(result)

@app.route("/api/training/start", methods=["POST"])
def training_start():
    if not db_pool:
        return jsonify({"error": "Database tidak tersambung."}), 503
    latest = query_one("""
        SELECT * FROM training_history
        WHERE valid_rows > 0 AND invalid_rows = 0
        ORDER BY created_at DESC
        LIMIT 1
    """)
    if not latest:
        return jsonify({"error": "Unggah dan validasi dataset yang valid terlebih dahulu."}), 400

    execute_write(
        """
        UPDATE training_history
        SET status = 'menunggu_pipeline',
            message = 'Dataset valid. Pipeline training siap dihubungkan ke proses fine-tuning.',
            started_at = NOW()
        WHERE id = %s
        """,
        (latest["id"],),
    )
    TRAINING_STATUS.update({
        "state": "menunggu_pipeline",
        "progress": 15,
        "message": "Dataset valid. Pipeline training siap dihubungkan ke proses fine-tuning.",
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "current_job_id": latest["id"],
    })
    return jsonify(TRAINING_STATUS), 202

@app.route("/api/training/status")
def training_status():
    return jsonify(TRAINING_STATUS)

@app.route("/api/training/history")
def training_history():
    if not db_pool:
        return jsonify({"data": []})
    try:
        rows = query_dict("""
            SELECT id, filename, total_rows, valid_rows, invalid_rows,
                   status, message, created_at, started_at, finished_at
            FROM training_history
            ORDER BY created_at DESC
            LIMIT 20
        """)
        for row in rows:
            for key in ("created_at", "started_at", "finished_at"):
                if row.get(key):
                    row[key] = format_dt(row[key])
        return jsonify({"data": rows})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    print("SiPadu starting...")
    init_db_pool()
    print("   Buka http://localhost:5000")
    app.run(debug=True, port=5000, use_reloader=False)
