# ============================================================
# FILE 4: PREDIKSI DARI CSV MENTAH (tanpa label)
# ============================================================
# Input : data_mentah.csv  → cuma kolom teks_bersih doang
# Output: hasil_prediksi.csv → teks + kategori + instansi + urgensi
#
# Jalankan:
#   python 4_prediksi_csv.py
# ============================================================

import pandas as pd
import torch
from transformers import AutoTokenizer, AutoModelForSequenceClassification
import json
import os

# ── KONFIGURASI ──────────────────────────────────────────────
FILE_INPUT        = "data_mentah_test_1.csv"
FILE_OUTPUT       = "hasil_prediksi.csv"
FOLDER_MODEL_KAT  = "./model_indobert_kategori"
FOLDER_MODEL_URG  = "./model_indobert_urgensi"
KOLOM_TEKS        = "teks_bersih"
BATCH_SIZE        = 16
MAX_LEN           = 128

INSTANSI_MAP = {
    "infrastruktur" : "Dinas Pekerjaan Umum",
    "kebersihan"    : "Dinas Lingkungan Hidup",
    "kesehatan"     : "Dinas Kesehatan",
    "administrasi"  : "Dinas Kependudukan dan Catatan Sipil",
    "keamanan"      : "Satuan Polisi Pamong Praja",
}

EMOJI_MAP = {
    "sangat_urgen" : "🔴 SANGAT URGEN",
    "urgen"        : "🟡 URGEN",
    "biasa"        : "🟢 BIASA",
    "tidak_urgen"  : "⚪ TIDAK URGEN",
}
# ─────────────────────────────────────────────────────────────


def load_model(folder, label_list):
    """Load model IndoBERT yang sudah di-training."""
    print(f"  Loading model dari: {folder}")

    if not os.path.exists(folder):
        print(f"  ❌ Folder '{folder}' tidak ditemukan!")
        print(f"     Pastikan sudah run 3_klasifikasi_dua_output.py dulu.")
        return None, None, None

    tokenizer = AutoTokenizer.from_pretrained(folder)
    model     = AutoModelForSequenceClassification.from_pretrained(folder)
    model.eval()

    # Buat id2label dari label_list yang diurutkan sama persis seperti waktu training
    # LabelEncoder sklearn mengurutkan label secara alphabetical
    sorted_labels = sorted(label_list)
    id2label = {i: label for i, label in enumerate(sorted_labels)}
    print(f"  Label mapping: {id2label}")

    return tokenizer, model, id2label


def prediksi_batch(texts, tokenizer, model, id2label):
    """Prediksi sekumpulan teks sekaligus."""
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model.to(device)

    semua_prediksi = []

    for i in range(0, len(texts), BATCH_SIZE):
        batch_texts = texts[i:i+BATCH_SIZE]

        encoding = tokenizer(
            batch_texts,
            truncation=True,
            padding=True,
            max_length=MAX_LEN,
            return_tensors="pt"
        ).to(device)

        with torch.no_grad():
            outputs = model(**encoding)
            pred_ids = torch.argmax(outputs.logits, dim=1).cpu().numpy()

        for pid in pred_ids:
            label = id2label.get(str(pid), id2label.get(pid, f"label_{pid}"))
            semua_prediksi.append(label)

        print(f"  Progress: {min(i+BATCH_SIZE, len(texts))}/{len(texts)} teks diproses...")

    return semua_prediksi


def main():
    print("=" * 60)
    print("PREDIKSI PENGADUAN MASYARAKAT")
    print("Input: CSV teks mentah → Output: CSV berlabel otomatis")
    print("=" * 60)

    # 1. Baca CSV input
    if not os.path.exists(FILE_INPUT):
        print(f"\n❌ File '{FILE_INPUT}' tidak ditemukan!")
        print(f"   Buat file CSV dengan satu kolom: teks_bersih")
        print(f"\n   Contoh isi {FILE_INPUT}:")
        print(f"   teks_bersih")
        print(f"   polisi tidur terlalu tinggi di jalan dipo")
        print(f"   sampah numpuk di depan pasar belum diangkut")
        print(f"   begal bunuh warga tadi malam di jalan gelap")
        return

    df = pd.read_csv(FILE_INPUT, encoding="utf-8-sig")

    if KOLOM_TEKS not in df.columns:
        print(f"❌ Kolom '{KOLOM_TEKS}' tidak ditemukan di CSV!")
        print(f"   Kolom yang ada: {list(df.columns)}")
        return

    df = df.dropna(subset=[KOLOM_TEKS])
    df = df[df[KOLOM_TEKS].str.strip().str.len() > 3]
    texts = df[KOLOM_TEKS].tolist()

    print(f"\n✓ Total teks yang akan diprediksi: {len(texts)}")

    # Label-label yang dipakai waktu training (harus sama persis!)
    LABELS_KATEGORI = ["administrasi", "infrastruktur", "keamanan", "kebersihan", "kesehatan"]
    LABELS_URGENSI  = ["biasa", "sangat_urgen", "tidak_urgen", "urgen"]

    # 2. Load kedua model
    print("\n[1/2] Loading model kategori...")
    tok_kat, mdl_kat, id2label_kat = load_model(FOLDER_MODEL_KAT, LABELS_KATEGORI)
    if mdl_kat is None: return

    print("\n[2/2] Loading model urgensi...")
    tok_urg, mdl_urg, id2label_urg = load_model(FOLDER_MODEL_URG, LABELS_URGENSI)
    if mdl_urg is None: return

    # 3. Prediksi kategori
    print("\n[3/4] Memprediksi kategori instansi...")
    pred_kategori = prediksi_batch(texts, tok_kat, mdl_kat, id2label_kat)

    # 4. Prediksi urgensi
    print("\n[4/4] Memprediksi tingkat urgensi...")
    pred_urgensi = prediksi_batch(texts, tok_urg, mdl_urg, id2label_urg)

    # 5. Gabungkan hasil
    df["kategori"] = pred_kategori
    df["instansi"] = df["kategori"].map(INSTANSI_MAP).fillna("-")
    df["urgensi"]  = pred_urgensi
    df["urgensi_label"] = df["urgensi"].map(EMOJI_MAP).fillna(df["urgensi"])

    # 6. Simpan output
    df.to_csv(FILE_OUTPUT, index=False, encoding="utf-8-sig")

    # 7. Preview hasil
    print(f"\n{'='*60}")
    print(f"✅ SELESAI! Hasil disimpan di: {FILE_OUTPUT}")
    print(f"{'='*60}")
    print("\nPreview hasil prediksi:")
    print(f"\n{'Teks':<40} {'Kategori':<15} {'Instansi':<35} {'Urgensi'}")
    print("-" * 110)
    for _, row in df.head(10).iterrows():
        teks_short = str(row[KOLOM_TEKS])[:38] + ".." if len(str(row[KOLOM_TEKS])) > 38 else str(row[KOLOM_TEKS])
        print(f"{teks_short:<40} {row['kategori']:<15} {row['instansi']:<35} {row['urgensi_label']}")


if __name__ == "__main__":
    main()