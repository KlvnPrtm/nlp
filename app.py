"""
app.py — Flask backend + MySQL untuk SiPadu
Letakkan di CobaLagi/, sejajar dengan folder model_indobert_*

Install deps:
    pip install flask flask-cors torch transformers pandas mysql-connector-python

Jalankan:
    python app.py
"""

from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import torch
from transformers import AutoTokenizer, AutoModelForSequenceClassification
import mysql.connector
from mysql.connector import pooling
import os   
from datetime import datetime

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

URGENSI_INFO = {
    "sangat_urgen": {"label": "Sangat Urgen", "color": "red",    "icon": "🔴", "priority": 4},
    "urgen":        {"label": "Urgen",         "color": "yellow", "icon": "🟡", "priority": 3},
    "biasa":        {"label": "Biasa",          "color": "green",  "icon": "🟢", "priority": 2},
    "tidak_urgen":  {"label": "Tidak Urgen",    "color": "gray",   "icon": "⚪", "priority": 1},
}

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
        print("✅ Database pool siap.")
        return True
    except Exception as e:
        print(f"❌ Gagal konek database: {e}")
        return False

def get_db():
    return db_pool.get_connection()

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
        print("✅ Model siap.")
        return True
    except Exception as e:
        models["error"] = str(e)
        print(f"❌ Gagal load model: {e}")
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
    
# ── DB HELPERS ────────────────────────────────────────────
def save_pengaduan(teks, kat_label, kat_conf, urg_label, urg_conf):
    urg_meta = URGENSI_INFO.get(urg_label, {"label": urg_label, "color": "gray", "icon": "?", "priority": 0})
    instansi = INSTANSI_MAP.get(kat_label, "-")
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

        instansi = INSTANSI_MAP.get(kat_label, "-")
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
        page   = int(request.args.get("page", 1))
        limit  = int(request.args.get("limit", 20))
        offset = (page - 1) * limit

        rows  = query_dict(
            "SELECT * FROM pengaduan ORDER BY created_at DESC LIMIT %s OFFSET %s",
            (limit, offset)
        )
        total = query_one("SELECT COUNT(*) AS n FROM pengaduan")["n"] or 0

        for row in rows:
            if row.get("created_at"):
                row["created_at"] = row["created_at"].strftime("%d %b %Y, %H:%M")

        return jsonify({"data": rows, "total": total, "page": page, "limit": limit})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    print("🚀 SiPadu starting...")
    init_db_pool()
    print("   Buka http://localhost:5000")
    app.run(debug=True, port=5000)
