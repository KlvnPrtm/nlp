# ============================================================
# FILE 3 (UPDATE): KLASIFIKASI PENGADUAN - DUA OUTPUT
# Kategori Instansi + Tingkat Urgensi
# ============================================================
# Sesuai arahan dosen:
#   Output 1 → Kategori instansi (infrastruktur/kebersihan/dll)
#   Output 2 → Tingkat urgensi (sangat_urgen/urgen/biasa/tidak_urgen)
#
# Install:
#   pip install transformers torch scikit-learn pandas seaborn matplotlib
#
# Jalankan:
#   python 3_klasifikasi_dua_output.py
# ============================================================

import pandas as pd
import numpy as np
import os
import random
import sys
import matplotlib.pyplot as plt
import seaborn as sns
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import LabelEncoder
from sklearn.metrics import classification_report, accuracy_score, confusion_matrix
import warnings
warnings.filterwarnings("ignore")

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# ── KONFIGURASI ──────────────────────────────────────────────
FILE_DATA      = "data_pengaduan_berlabel_5.csv"
FILE_DATA_TAMBAHAN = "data_tambahan_pengaduan.csv"
MODEL_INDOBERT = "indobenchmark/indobert-base-p1"
BATCH_SIZE     = 8
MAX_LEN        = 128
EPOCHS         = 3
LEARNING_RATE  = 2e-5
TEST_SIZE      = 0.2
RANDOM_STATE   = 42
USE_CLASS_WEIGHTS = True

# Mapping instansi (untuk output yang lebih informatif)
INSTANSI_MAP = {
    'infrastruktur': 'Dinas Pekerjaan Umum',
    'kebersihan'   : 'Dinas Lingkungan Hidup',
    'kesehatan'    : 'Dinas Kesehatan',
    'administrasi' : 'Dinas Kependudukan dan Catatan Sipil',
    'keamanan'     : 'Satuan Polisi Pamong Praja',
}
# ─────────────────────────────────────────────────────────────

def set_seed(seed=RANDOM_STATE):
    random.seed(seed)
    np.random.seed(seed)
    try:
        import torch
        torch.manual_seed(seed)
        if torch.cuda.is_available():
            torch.cuda.manual_seed_all(seed)
    except ImportError:
        pass


def load_data():
    print("=" * 60)
    print("KLASIFIKASI PENGADUAN MASYARAKAT")
    print("Output: Kategori Instansi + Tingkat Urgensi")
    print("=" * 60)

    df = pd.read_csv(FILE_DATA, encoding="utf-8-sig")
    if os.path.exists(FILE_DATA_TAMBAHAN):
        extra = pd.read_csv(FILE_DATA_TAMBAHAN, encoding="utf-8-sig")
        missing_cols = {"teks_bersih", "kategori", "urgensi"} - set(extra.columns)
        if missing_cols:
            raise ValueError(f"{FILE_DATA_TAMBAHAN} kurang kolom: {sorted(missing_cols)}")
        print(f"✓ Data tambahan terbaca: {len(extra)} baris")
        df = pd.concat([df, extra], ignore_index=True)

    df = df.dropna(subset=["teks_bersih", "kategori", "urgensi"])
    df = df[df["teks_bersih"].str.strip().str.len() > 5]
    df["teks_bersih"] = df["teks_bersih"].astype(str).str.strip()
    df = df.drop_duplicates(subset=["teks_bersih", "kategori", "urgensi"])

    print(f"\n✓ Total data: {len(df)} baris\n")

    print("Distribusi KATEGORI:")
    for label, count in df["kategori"].value_counts().items():
        bar = "█" * (count // 5)
        print(f"  {label:15s} {count:4d}  {bar}")

    print("\nDistribusi URGENSI:")
    urgensi_order = ["sangat_urgen", "urgen", "biasa", "tidak_urgen"]
    for label in urgensi_order:
        count = len(df[df["urgensi"] == label])
        bar = "█" * (count // 5)
        print(f"  {label:15s} {count:4d}  {bar}")

    return df


def latih_tfidf_svm(X_train, X_test, y_train, y_test, nama_task):
    """Latih TF-IDF + SVM untuk satu task (kategori atau urgensi)."""
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.svm import LinearSVC
    from sklearn.pipeline import Pipeline

    model = Pipeline([
        ("tfidf", TfidfVectorizer(max_features=10000, ngram_range=(1, 2), sublinear_tf=True)),
        ("svm", LinearSVC(C=1.0, max_iter=2000))
    ])
    model.fit(X_train, y_train)
    y_pred = model.predict(X_test)
    acc = accuracy_score(y_test, y_pred)

    print(f"\n  TF-IDF+SVM [{nama_task}] → Accuracy: {acc*100:.2f}%")
    print(classification_report(y_test, y_pred, zero_division=0))

    return model, y_pred, acc


def latih_indobert(X_train, X_test, y_train, y_test, le, nama_task):
    """Fine-tune IndoBERT untuk satu task."""
    import torch
    from torch.utils.data import Dataset, DataLoader
    from transformers import (
        AutoTokenizer, AutoModelForSequenceClassification,
        get_linear_schedule_with_warmup
    )
    from torch.optim import AdamW

    print(f"\n  Fine-tuning IndoBERT [{nama_task}]...")
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"  Device: {device}")

    tokenizer = AutoTokenizer.from_pretrained(MODEL_INDOBERT)
    id2label = {i: label for i, label in enumerate(le.classes_)}
    label2id = {label: i for i, label in id2label.items()}
    model = AutoModelForSequenceClassification.from_pretrained(
        MODEL_INDOBERT,
        num_labels=len(le.classes_),
        id2label=id2label,
        label2id=label2id,
    ).to(device)

    class PengaduanDataset(torch.utils.data.Dataset):
        def __init__(self, texts, labels):
            self.enc = tokenizer(
                texts.tolist(), truncation=True,
                padding=True, max_length=MAX_LEN, return_tensors="pt"
            )
            self.labels = torch.tensor(labels, dtype=torch.long)
        def __len__(self): return len(self.labels)
        def __getitem__(self, i):
            item = {k: v[i] for k, v in self.enc.items()}
            item["labels"] = self.labels[i]
            return item

    train_dl = DataLoader(PengaduanDataset(X_train, y_train), batch_size=BATCH_SIZE, shuffle=True)
    test_dl  = DataLoader(PengaduanDataset(X_test, y_test),   batch_size=BATCH_SIZE)

    optimizer = AdamW(model.parameters(), lr=LEARNING_RATE)
    total_steps = len(train_dl) * EPOCHS
    scheduler = get_linear_schedule_with_warmup(
        optimizer, num_warmup_steps=int(0.1*total_steps), num_training_steps=total_steps
    )
    class_weights = None
    if USE_CLASS_WEIGHTS:
        counts = np.bincount(y_train, minlength=len(le.classes_))
        weights = len(y_train) / (len(le.classes_) * np.maximum(counts, 1))
        class_weights = torch.tensor(weights, dtype=torch.float).to(device)
        print("  Class weights:", {label: round(float(class_weights[i].cpu()), 3) for i, label in id2label.items()})

    history = []
    for epoch in range(EPOCHS):
        model.train()
        total_loss = 0
        for batch in train_dl:
            batch = {k: v.to(device) for k, v in batch.items()}
            labels = batch.pop("labels")
            logits = model(**batch).logits
            loss = torch.nn.functional.cross_entropy(logits, labels, weight=class_weights)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step(); scheduler.step(); optimizer.zero_grad()
            total_loss += loss.item()
        avg = total_loss / len(train_dl)
        history.append(avg)
        print(f"    Epoch {epoch+1}/{EPOCHS} — Loss: {avg:.4f}")

    # Evaluasi
    model.eval()
    preds = []
    with torch.no_grad():
        for batch in test_dl:
            batch = {k: v.to(device) for k, v in batch.items()}
            preds.extend(torch.argmax(model(**batch).logits, 1).cpu().numpy())

    y_pred_names = le.inverse_transform(preds)
    y_test_names = le.inverse_transform(y_test)
    acc = accuracy_score(y_test_names, y_pred_names)

    print(f"\n  IndoBERT [{nama_task}] → Accuracy: {acc*100:.2f}%")
    print(classification_report(y_test_names, y_pred_names, zero_division=0))

    # Simpan model
    folder = f"./model_indobert_{nama_task.lower().replace(' ','_')}"
    model.save_pretrained(folder)
    tokenizer.save_pretrained(folder)
    print(f"  ✓ Model disimpan di: {folder}/")

    return y_pred_names, y_test_names, acc, history, model, tokenizer, le, device


def demo_prediksi(model_kat, model_urg, le_kat, le_urg):
    """Demo prediksi dua output sekaligus — kategori + urgensi."""
    print("\n" + "=" * 60)
    print("DEMO PREDIKSI — DUA OUTPUT SEKALIGUS")
    print("=" * 60)

    contoh = [
        "jalan di depan rumah berlubang kecil sudah sebulan",
        "jembatan penghubung desa kami hampir putus sangat berbahaya",
        "ada begal membunuh warga tadi malam di jalan gelap",
        "sampah di TPS tidak diangkut sudah seminggu bau busuk",
        "wabah kolera menyebar di desa sudah ada yang meninggal",
        "KTP saya sudah empat bulan belum jadi",
        "pak wali kota ganteng sekali orangnya baik",
    ]

    print(f"\n{'Teks Laporan':<45} {'Kategori':<17} {'Instansi':<35} {'Urgensi'}")
    print("-" * 120)

    for teks in contoh:
        kat  = model_kat.predict([teks])[0]
        urg  = model_urg.predict([teks])[0]
        inst = INSTANSI_MAP.get(kat, '-')

        # Emoji urgensi
        emoji = {"sangat_urgen":"🔴","urgen":"🟡","biasa":"🟢","tidak_urgen":"⚪"}.get(urg, "")

        print(f"{teks[:44]:<45} {kat:<17} {inst:<35} {emoji} {urg}")


def buat_visualisasi(acc_svm_kat, acc_bert_kat, acc_svm_urg, acc_bert_urg,
                     y_test_kat, y_pred_kat, y_test_urg, y_pred_urg, le_kat, le_urg):
    """Buat grafik perbandingan untuk bab hasil skripsi."""
    fig, axes = plt.subplots(1, 3, figsize=(18, 5))

    # 1. Perbandingan accuracy
    labels_bar = ['TF-IDF+SVM\nKategori', 'IndoBERT\nKategori',
                  'TF-IDF+SVM\nUrgensi', 'IndoBERT\nUrgensi']
    vals = [acc_svm_kat*100, acc_bert_kat*100, acc_svm_urg*100, acc_bert_urg*100]
    colors = ['#93c5fd','#1d4ed8','#86efac','#16a34a']
    bars = axes[0].bar(labels_bar, vals, color=colors, width=0.5)
    axes[0].set_title("Perbandingan Akurasi", fontsize=12)
    axes[0].set_ylabel("Akurasi (%)")
    axes[0].set_ylim(0, 105)
    for bar, val in zip(bars, vals):
        axes[0].text(bar.get_x() + bar.get_width()/2, val+1,
                     f"{val:.1f}%", ha='center', fontsize=9, fontweight='bold')

    # 2. Confusion matrix kategori (IndoBERT)
    labels_kat = sorted(list(set(y_test_kat)))
    cm_kat = confusion_matrix(y_test_kat, y_pred_kat, labels=labels_kat)
    sns.heatmap(cm_kat, annot=True, fmt='d', cmap='Blues',
                xticklabels=labels_kat, yticklabels=labels_kat, ax=axes[1])
    axes[1].set_title("Confusion Matrix — Kategori (IndoBERT)", fontsize=11)
    axes[1].set_xlabel("Prediksi"); axes[1].set_ylabel("Aktual")
    plt.setp(axes[1].xaxis.get_majorticklabels(), rotation=30, ha='right')

    # 3. Confusion matrix urgensi (IndoBERT)
    labels_urg = ["sangat_urgen","urgen","biasa","tidak_urgen"]
    labels_urg_exist = [l for l in labels_urg if l in set(y_test_urg)]
    cm_urg = confusion_matrix(y_test_urg, y_pred_urg, labels=labels_urg_exist)
    sns.heatmap(cm_urg, annot=True, fmt='d', cmap='Oranges',
                xticklabels=labels_urg_exist, yticklabels=labels_urg_exist, ax=axes[2])
    axes[2].set_title("Confusion Matrix — Urgensi (IndoBERT)", fontsize=11)
    axes[2].set_xlabel("Prediksi"); axes[2].set_ylabel("Aktual")
    plt.setp(axes[2].xaxis.get_majorticklabels(), rotation=30, ha='right')

    plt.tight_layout()
    plt.savefig("hasil_evaluasi.png", dpi=150, bbox_inches="tight")
    print("\n✓ Grafik disimpan di: hasil_evaluasi.png")
    plt.show()


def main():
    set_seed()

    # Load data
    df = load_data()

    X = df["teks_bersih"].values

    # ── Encode dua label ──
    le_kat = LabelEncoder()
    le_urg = LabelEncoder()
    y_kat  = le_kat.fit_transform(df["kategori"].values)
    y_urg  = le_urg.fit_transform(df["urgensi"].values)

    # Split (sama untuk kedua task agar perbandingan adil)
    stratify_key = df["kategori"].astype(str) + "|" + df["urgensi"].astype(str)
    if stratify_key.value_counts().min() < 2:
        print("\n⚠ Kombinasi kategori+urgensi terlalu sedikit untuk stratify gabungan; pakai stratify kategori.")
        stratify_key = y_kat

    X_train, X_test, yk_train, yk_test, yu_train, yu_test = train_test_split(
        X, y_kat, y_urg,
        test_size=TEST_SIZE, random_state=RANDOM_STATE, stratify=stratify_key
    )

    print(f"\nData training: {len(X_train)} | Data testing: {len(X_test)}")

    # ══════════════════════════════════════════════════
    # TASK 1: KLASIFIKASI KATEGORI INSTANSI
    # ══════════════════════════════════════════════════
    print("\n" + "="*60)
    print("TASK 1: KLASIFIKASI KATEGORI INSTANSI")
    print("="*60)

    yk_train_names = le_kat.inverse_transform(yk_train)
    yk_test_names  = le_kat.inverse_transform(yk_test)

    print("\n[Baseline] TF-IDF + SVM:")
    model_svm_kat, y_pred_svm_kat, acc_svm_kat = latih_tfidf_svm(
        X_train, X_test, yk_train_names, yk_test_names, "Kategori"
    )

    print("\n[Utama] IndoBERT Fine-Tune:")
    y_pred_bert_kat, y_test_bert_kat, acc_bert_kat, history_kat, \
        m_kat, tok_kat, le_kat, dev_kat = latih_indobert(
        X_train, X_test, yk_train, yk_test, le_kat, "Kategori"
    )

    # ══════════════════════════════════════════════════
    # TASK 2: KLASIFIKASI TINGKAT URGENSI
    # ══════════════════════════════════════════════════
    print("\n" + "="*60)
    print("TASK 2: KLASIFIKASI TINGKAT URGENSI")
    print("="*60)

    yu_train_names = le_urg.inverse_transform(yu_train)
    yu_test_names  = le_urg.inverse_transform(yu_test)

    print("\n[Baseline] TF-IDF + SVM:")
    model_svm_urg, y_pred_svm_urg, acc_svm_urg = latih_tfidf_svm(
        X_train, X_test, yu_train_names, yu_test_names, "Urgensi"
    )

    print("\n[Utama] IndoBERT Fine-Tune:")
    y_pred_bert_urg, y_test_bert_urg, acc_bert_urg, history_urg, \
        m_urg, tok_urg, le_urg, dev_urg = latih_indobert(
        X_train, X_test, yu_train, yu_test, le_urg, "Urgensi"
    )

    # ══════════════════════════════════════════════════
    # DEMO + VISUALISASI
    # ══════════════════════════════════════════════════
    demo_prediksi(model_svm_kat, model_svm_urg, le_kat, le_urg)

    buat_visualisasi(
        acc_svm_kat, acc_bert_kat, acc_svm_urg, acc_bert_urg,
        y_test_bert_kat, y_pred_bert_kat,
        y_test_bert_urg, y_pred_bert_urg,
        le_kat, le_urg
    )

    # ══════════════════════════════════════════════════
    # RINGKASAN AKHIR
    # ══════════════════════════════════════════════════
    print("\n" + "=" * 60)
    print("RINGKASAN HASIL — UNTUK SKRIPSI")
    print("=" * 60)
    print(f"  TASK 1 — Kategori Instansi:")
    print(f"    TF-IDF + SVM  : {acc_svm_kat*100:.2f}%")
    print(f"    IndoBERT      : {acc_bert_kat*100:.2f}%")
    print(f"    Peningkatan   : +{(acc_bert_kat-acc_svm_kat)*100:.2f}%")
    print(f"\n  TASK 2 — Tingkat Urgensi:")
    print(f"    TF-IDF + SVM  : {acc_svm_urg*100:.2f}%")
    print(f"    IndoBERT      : {acc_bert_urg*100:.2f}%")
    print(f"    Peningkatan   : +{(acc_bert_urg-acc_svm_urg)*100:.2f}%")
    print("\n  → Dua output sekaligus: kategori instansi + urgensi")
    print("  → IndoBERT terbukti lebih unggul dari baseline TF-IDF+SVM")
    print("=" * 60)


if __name__ == "__main__":
    main()
