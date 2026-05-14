// ==========================================================
// SiPadu — dashboard.js
// Chunk 1/4: state + helpers + navigation
// ==========================================================

const PAGE_LIMIT = 12;

const SECTION_TITLES = {
  dashboard:  ["Dashboard Admin",     "Pusat Kendali Pengaduan"],
  data:       ["Data Pengaduan",      "Arsip Pengaduan Tersimpan"],
  kategori:   ["Kelola Kategori",     "Master Kategori dan Instansi"],
  training:   ["Dataset & Training",  "Unggah Dataset dan Pantau Training"],
  pengaturan: ["Pengaturan",          "Pengaturan Sistem"],
};

const state = {
  stats: null,
  categories: [],
  trainingHistory: [],
  rows: [],
  currentPage: 1,
  totalItems: 0,
  trendMode: "harian",
  filters: { q: "", kategori: "", urgensi: "", instansi: "", date_from: "", date_to: "" },
};

const toast = document.getElementById("toast");
let searchTimer = null;
let selectedDatasetFile = null;
let confirmAction = null;

function formatLabel(value) {
  return String(value || "-").replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

function showToast(message, type = "success") {
  toast.textContent = message;
  toast.className = "toast show " + (type === "error" ? "error" : "");
  clearTimeout(showToast.timer);
  showToast.timer = setTimeout(() => { toast.className = "toast"; }, 2800);
}

async function apiJson(url, options) {
  const res = await fetch(url, options);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || "Permintaan gagal diproses.");
  return data;
}

function showError(message) {
  const box = document.getElementById("error-box");
  if (!box) return;
  box.textContent = message || "";
  box.style.display = message ? "block" : "none";
}

function sectionFromHash() {
  const value = location.hash.replace("#", "");
  return value || "dashboard";
}

function showSection(name, updateHash = true) {
  const target = document.querySelector('[data-section="' + name + '"]') ? name : "dashboard";
  document.querySelectorAll("[data-section]").forEach((section) => {
    section.classList.toggle("active", section.dataset.section === target);
  });
  document.querySelectorAll("[data-nav]").forEach((link) => {
    link.classList.toggle("active", link.dataset.nav === target);
  });
  const titles = SECTION_TITLES[target] || SECTION_TITLES.dashboard;
  const eyebrow = document.getElementById("topbar-eyebrow");
  const heading = document.getElementById("topbar-heading");
  if (eyebrow) eyebrow.textContent = titles[0];
  if (heading) heading.textContent = titles[1];
  if (updateHash && location.hash !== "#" + target) {
    history.replaceState(null, "", "#" + target);
  }
}

function tableMessageRow(text, colspan) {
  const row = document.createElement("tr");
  const td = document.createElement("td");
  td.colSpan = colspan;
  td.className = "empty";
  td.textContent = text;
  row.appendChild(td);
  return row;
}

function emptyBlock(text) {
  const empty = document.createElement("div");
  empty.className = "empty";
  empty.textContent = text;
  return empty;
}

function appendCell(tr, text, className) {
  const td = document.createElement("td");
  if (className) td.className = className;
  td.textContent = text;
  tr.appendChild(td);
}

function appendTagCell(tr, text, color) {
  const td = document.createElement("td");
  const tag = document.createElement("span");
  tag.className = "tag " + (color || "gray");
  tag.textContent = text;
  td.appendChild(tag);
  tr.appendChild(td);
}

function svgEl(name, attrs) {
  const el = document.createElementNS("http://www.w3.org/2000/svg", name);
  Object.entries(attrs).forEach(([k, v]) => el.setAttribute(k, v));
  return el;
}

function updateTimestamp() {
  const node = document.getElementById("last-updated");
  if (!node) return;
  node.textContent = "Diperbarui " + new Date().toLocaleTimeString("id-ID", { hour: "2-digit", minute: "2-digit" });
}

// ==========================================================
// Chunk 2/4: stats + KPI + bars + trend chart
// ==========================================================

async function loadStats() {
  try {
    const data = await apiJson("/api/stats");
    state.stats = data;
    renderKpi();
    renderBars("category-bars", data.kategori || [], "kategori", "total");
    renderUrgencyBars(data.urgensi || []);
    renderTrend();
    showError("");
  } catch (err) {
    showError(err.message || "Statistik gagal dimuat.");
    renderEmptyBars();
  }
}

function renderKpi() {
  const stats = state.stats || {};
  const urgMap = {};
  (stats.urgensi || []).forEach((row) => { urgMap[row.urgensi] = Number(row.total) || 0; });
  const latestDataset = state.trainingHistory[0] || {};
  document.getElementById("kpi-total").textContent    = stats.total || 0;
  document.getElementById("kpi-sangat").textContent   = urgMap.sangat_urgen || 0;
  document.getElementById("kpi-urgen").textContent    = urgMap.urgen || 0;
  document.getElementById("kpi-rendah").textContent   = (urgMap.biasa || 0) + (urgMap.tidak_urgen || 0);
  document.getElementById("kpi-kategori").textContent = state.categories.filter((i) => i.aktif).length;
  document.getElementById("kpi-dataset").textContent  = latestDataset.valid_rows || 0;
}

function renderEmptyBars() {
  document.getElementById("category-bars").replaceChildren(emptyBlock("Data kategori belum tersedia."));
  document.getElementById("urgency-bars").replaceChildren(emptyBlock("Data urgensi belum tersedia."));
}

function renderBars(containerId, rows, labelKey, valueKey) {
  const box = document.getElementById(containerId);
  box.replaceChildren();
  if (!rows.length) { box.appendChild(emptyBlock("Belum ada data tersimpan.")); return; }
  const max = Math.max(...rows.map((r) => Number(r[valueKey]) || 0), 1);
  rows.forEach((row) => {
    const value = Number(row[valueKey]) || 0;
    box.appendChild(createBar(formatLabel(row[labelKey]), value, (value / max) * 100, ""));
  });
}

function renderUrgencyBars(rows) {
  const order = ["sangat_urgen", "urgen", "biasa", "tidak_urgen"];
  const sorted = order.map((key) => rows.find((r) => r.urgensi === key)).filter(Boolean);
  const total = sorted.reduce((sum, r) => sum + (Number(r.total) || 0), 0) || 1;
  const box = document.getElementById("urgency-bars");
  box.replaceChildren();
  if (!sorted.length) { box.appendChild(emptyBlock("Belum ada data urgensi.")); return; }
  sorted.forEach((row) => {
    const value = Number(row.total) || 0;
    box.appendChild(createBar(
      row.urgensi_display || formatLabel(row.urgensi),
      value,
      (value / total) * 100,
      row.urgensi_color || "gray",
    ));
  });
}

function createBar(label, value, width, colorClass) {
  const row = document.createElement("div");
  row.className = "bar-row";
  const name = document.createElement("span");
  name.className = "bar-name";
  name.textContent = label;
  const track = document.createElement("span");
  track.className = "bar-track";
  const fill = document.createElement("span");
  fill.className = "bar-fill " + colorClass;
  fill.style.width = Math.max(0, Math.min(100, width)) + "%";
  track.appendChild(fill);
  const val = document.createElement("span");
  val.className = "bar-value";
  val.textContent = value;
  row.append(name, track, val);
  return row;
}

function setTrendMode(mode) {
  state.trendMode = mode;
  document.getElementById("btn-harian").classList.toggle("active", mode === "harian");
  document.getElementById("btn-mingguan").classList.toggle("active", mode === "mingguan");
  renderTrend();
}

function renderTrend() {
  const box = document.getElementById("trend-chart");
  box.replaceChildren();
  const rows = (state.stats && state.stats[state.trendMode]) || [];
  if (!rows.length) { box.appendChild(emptyBlock("Tren belum tersedia.")); return; }

  const width = 960;
  const height = 280;
  const pad = { top: 22, right: 28, bottom: 42, left: 48 };
  const total = rows.map((r) => Number(r.total) || 0);
  const urgent = rows.map((r) => Number(r.urgen_count) || 0);
  const maxVal = Math.max(...total, ...urgent, 1);
  const plotW = width - pad.left - pad.right;
  const plotH = height - pad.top - pad.bottom;
  const x = (i) => pad.left + (rows.length === 1 ? plotW / 2 : (i / (rows.length - 1)) * plotW);
  const y = (v) => pad.top + plotH - (v / maxVal) * plotH;
  const points = (values) => values.map((v, i) => x(i) + "," + y(v)).join(" ");

  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 " + width + " " + height);
  svg.setAttribute("preserveAspectRatio", "none");
  svg.setAttribute("role", "img");
  svg.setAttribute("aria-label", "Grafik tren pengaduan");

  for (let i = 0; i <= 4; i++) {
    const gy = pad.top + (plotH / 4) * i;
    svg.appendChild(svgEl("line", { x1: pad.left, y1: gy, x2: width - pad.right, y2: gy, class: "grid-line" }));
    const text = svgEl("text", { x: 12, y: gy + 4, class: "axis-text" });
    text.textContent = Math.round(maxVal - (maxVal / 4) * i);
    svg.appendChild(text);
  }

  const areaPoints =
    points(total) +
    " " + x(rows.length - 1) + "," + (pad.top + plotH) +
    " " + x(0) + "," + (pad.top + plotH);
  svg.appendChild(svgEl("polygon", { points: areaPoints, class: "area-total" }));

  svg.appendChild(svgEl("polyline", { points: points(total),  class: "line-total" }));
  svg.appendChild(svgEl("polyline", { points: points(urgent), class: "line-urgent" }));
  total.forEach((v, i)  => svg.appendChild(svgEl("circle", { cx: x(i), cy: y(v), r: 3.5, class: "dot-total" })));
  urgent.forEach((v, i) => svg.appendChild(svgEl("circle", { cx: x(i), cy: y(v), r: 3.5, class: "dot-urgent" })));

  rows.forEach((row, i) => {
    if (i % Math.ceil(rows.length / 7) === 0 || i === rows.length - 1) {
      const label = String(row.tanggal || row.mulai || "").slice(5);
      const text = svgEl("text", { x: x(i), y: height - 14, class: "axis-text", "text-anchor": "middle" });
      text.textContent = label;
      svg.appendChild(text);
    }
  });
  box.appendChild(svg);
}

// ==========================================================
// Chunk 3/4: categories, filters, riwayat, data table, detail, export
// ==========================================================

async function loadCategories() {
  try {
    const data = await apiJson("/api/categories");
    state.categories = data.data || [];
    renderCategoryTable();
    populateFilterOptions();
    renderKpi();
  } catch (err) {
    showToast(err.message || "Kategori gagal dimuat.", "error");
  }
}

function populateFilterOptions() {
  const agencies = [...new Set(state.categories.map((i) => i.instansi).filter(Boolean))].sort();
  document.querySelectorAll(".js-category-filter").forEach((select) => {
    const prev = select.value;
    select.replaceChildren(new Option("Semua kategori", ""));
    state.categories.forEach((i) => select.appendChild(new Option(i.nama, i.slug)));
    select.value = prev || state.filters.kategori;
  });
  document.querySelectorAll(".js-agency-filter").forEach((select) => {
    const prev = select.value;
    select.replaceChildren(new Option("Semua instansi", ""));
    agencies.forEach((a) => select.appendChild(new Option(a, a)));
    select.value = prev || state.filters.instansi;
  });
}

function syncFilterControls(key) {
  document.querySelectorAll('[data-filter="' + key + '"]').forEach((input) => {
    input.value = state.filters[key] || "";
  });
}

function resetFilters() {
  Object.keys(state.filters).forEach((key) => {
    state.filters[key] = "";
    syncFilterControls(key);
  });
  loadRiwayat(1);
}

function renderFilterChips() {
  const box = document.getElementById("filter-chips");
  if (!box) return;
  box.replaceChildren();
  const labels = {
    q: "Kata kunci", kategori: "Kategori", urgensi: "Urgensi",
    instansi: "Instansi", date_from: "Dari", date_to: "Sampai",
  };
  Object.entries(state.filters).forEach(([key, value]) => {
    if (!value) return;
    const chip = document.createElement("button");
    chip.type = "button";
    chip.className = "filter-chip";
    const shown = (key === "kategori" || key === "urgensi") ? formatLabel(value) : value;
    chip.textContent = labels[key] + ": " + shown + " x";
    chip.addEventListener("click", () => {
      state.filters[key] = "";
      syncFilterControls(key);
      loadRiwayat(1);
    });
    box.appendChild(chip);
  });
}

async function loadRiwayat(page) {
  state.currentPage = Math.max(page, 1);
  const tbody = document.getElementById("table-body");
  tbody.replaceChildren(tableMessageRow("Memuat data pengaduan...", 9));
  try {
    const params = new URLSearchParams({ page: state.currentPage, limit: PAGE_LIMIT });
    Object.entries(state.filters).forEach(([k, v]) => { if (v) params.set(k, v); });
    const data = await apiJson("/api/riwayat?" + params.toString());
    state.rows = data.data || [];
    state.totalItems = Number(data.total) || 0;
    document.getElementById("table-count").textContent = state.totalItems + " data ditemukan";
    document.getElementById("page-info").textContent = state.totalItems
      ? "Halaman " + state.currentPage + " dari " + Math.max(Math.ceil(state.totalItems / PAGE_LIMIT), 1)
      : "Tidak ada data";
    renderDataTable(state.rows);
    renderRecentTable(state.rows.slice(0, 6));
    updatePagination();
    renderFilterChips();
  } catch (err) {
    tbody.replaceChildren(tableMessageRow(err.message || "Data pengaduan gagal dimuat.", 9));
    renderRecentTable([]);
  }
}

function renderDataTable(rows) {
  const tbody = document.getElementById("table-body");
  tbody.replaceChildren();
  if (!rows.length) { tbody.appendChild(tableMessageRow("Tidak ada data yang cocok dengan filter.", 9)); return; }
  rows.forEach((row) => {
    const tr = document.createElement("tr");
    appendCell(tr, row.id, "mono");
    appendCell(tr, row.teks || "-", "td-text");
    appendTagCell(tr, formatLabel(row.kategori), "category");
    appendCell(tr, row.instansi || "-", "");
    appendTagCell(tr, row.urgensi_display || formatLabel(row.urgensi), row.urgensi_color || "gray");
    appendCell(tr, (row.kat_confidence ?? "-") + "%", "mono");
    appendCell(tr, (row.urg_confidence ?? "-") + "%", "mono");
    appendCell(tr, row.created_at || "-", "mono");
    const action = document.createElement("td");
    action.className = "action-cell";
    const btn = document.createElement("button");
    btn.className = "btn btn-secondary btn-small";
    btn.type = "button";
    btn.textContent = "Lihat";
    btn.addEventListener("click", () => openDetail(row));
    action.appendChild(btn);
    tr.appendChild(action);
    tbody.appendChild(tr);
  });
}

function renderRecentTable(rows) {
  const tbody = document.getElementById("dashboard-recent-body");
  tbody.replaceChildren();
  if (!rows.length) { tbody.appendChild(tableMessageRow("Belum ada pengaduan terbaru.", 6)); return; }
  rows.forEach((row) => {
    const tr = document.createElement("tr");
    appendCell(tr, row.id, "mono");
    appendCell(tr, row.teks || "-", "td-text");
    appendTagCell(tr, formatLabel(row.kategori), "category");
    appendCell(tr, row.instansi || "-", "");
    appendTagCell(tr, row.urgensi_display || formatLabel(row.urgensi), row.urgensi_color || "gray");
    appendCell(tr, row.created_at || "-", "mono");
    tbody.appendChild(tr);
  });
}

function updatePagination() {
  const totalPages = Math.max(Math.ceil(state.totalItems / PAGE_LIMIT), 1);
  document.getElementById("prev-page").disabled = state.currentPage <= 1;
  document.getElementById("next-page").disabled = state.currentPage >= totalPages;
}

function openDetail(row) {
  const drawer = document.getElementById("detail-drawer");
  const content = document.getElementById("detail-content");
  content.replaceChildren();
  const fields = [
    ["ID Data", "#" + row.id],
    ["Kategori", formatLabel(row.kategori)],
    ["Instansi", row.instansi || "-"],
    ["Urgensi", row.urgensi_display || formatLabel(row.urgensi)],
    ["Kepercayaan Kategori", (row.kat_confidence ?? "-") + "%"],
    ["Kepercayaan Urgensi",  (row.urg_confidence ?? "-") + "%"],
    ["Waktu Masuk", row.created_at || "-"],
    ["Teks Pengaduan", row.teks || "-"],
  ];
  fields.forEach(([label, value]) => {
    const block = document.createElement("div");
    block.className = "detail-row";
    const dt = document.createElement("span"); dt.textContent = label;
    const dd = document.createElement("strong"); dd.textContent = value;
    block.append(dt, dd);
    content.appendChild(block);
  });
  drawer.classList.add("open");
  drawer.setAttribute("aria-hidden", "false");
}

function closeDetail() {
  const drawer = document.getElementById("detail-drawer");
  drawer.classList.remove("open");
  drawer.setAttribute("aria-hidden", "true");
}

async function exportData(button) {
  const tools = button.closest(".export-tools");
  const format = tools.querySelector(".export-format").value;
  const original = button.innerHTML;
  button.disabled = true;
  button.textContent = "Sedang menyiapkan file...";
  try {
    const res = await fetch("/api/export?format=" + encodeURIComponent(format));
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      throw new Error(data.error || "Gagal mengunduh data.");
    }
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = "sipadu-pengaduan." + format;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
    showToast("Data berhasil diunduh.");
  } catch (err) {
    showToast(err.message || "Gagal mengunduh data.", "error");
  } finally {
    button.disabled = false;
    button.innerHTML = original;
  }
}

// ==========================================================
// Chunk 4a/4: category CRUD + confirm modal
// ==========================================================

function renderCategoryTable() {
  const tbody = document.getElementById("category-table-body");
  tbody.replaceChildren();
  document.getElementById("category-count").textContent =
    state.categories.length + " kategori terdaftar";
  if (!state.categories.length) {
    tbody.appendChild(tableMessageRow("Belum ada kategori.", 5));
    return;
  }
  state.categories.forEach((item) => {
    const tr = document.createElement("tr");
    appendTagCell(tr, item.nama, "category");
    appendCell(tr, item.instansi || "-", "");
    appendCell(tr, item.jumlah_pengaduan || 0, "mono");
    appendTagCell(tr, item.aktif ? "Aktif" : "Nonaktif", item.aktif ? "green" : "gray");
    const action = document.createElement("td");
    action.className = "action-cell";
    const edit = document.createElement("button");
    edit.className = "btn btn-secondary btn-small";
    edit.type = "button";
    edit.textContent = "Edit";
    edit.addEventListener("click", () => openCategoryModal(item));
    const remove = document.createElement("button");
    remove.className = item.jumlah_pengaduan ? "btn btn-ghost btn-small" : "btn btn-danger btn-small";
    remove.type = "button";
    remove.textContent = item.jumlah_pengaduan ? "Nonaktifkan" : "Hapus";
    remove.disabled = !item.aktif && item.jumlah_pengaduan > 0;
    remove.addEventListener("click", () => confirmCategoryRemoval(item));
    action.append(edit, remove);
    tr.appendChild(action);
    tbody.appendChild(tr);
  });
}

function openCategoryModal(item = null) {
  document.getElementById("category-modal-title").textContent = item ? "Edit Kategori" : "Tambah Kategori";
  document.getElementById("category-id").value = item ? item.id : "";
  document.getElementById("category-name").value = item ? item.nama : "";
  document.getElementById("category-agency").value = item ? item.instansi : "";
  document.getElementById("category-active").checked = item ? item.aktif : true;
  const modal = document.getElementById("category-modal");
  modal.classList.add("open");
  modal.setAttribute("aria-hidden", "false");
}

function closeCategoryModal() {
  const modal = document.getElementById("category-modal");
  modal.classList.remove("open");
  modal.setAttribute("aria-hidden", "true");
}

async function saveCategory(event) {
  event.preventDefault();
  const id = document.getElementById("category-id").value;
  const payload = {
    nama:     document.getElementById("category-name").value.trim(),
    instansi: document.getElementById("category-agency").value.trim(),
    aktif:    document.getElementById("category-active").checked,
  };
  if (payload.nama.length < 2 || payload.instansi.length < 2) {
    showToast("Nama kategori dan instansi wajib diisi.", "error");
    return;
  }
  try {
    const data = await apiJson(id ? "/api/categories/" + id : "/api/categories", {
      method: id ? "PUT" : "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    showToast(data.message || "Kategori berhasil disimpan.");
    closeCategoryModal();
    await loadCategories();
  } catch (err) {
    showToast(err.message || "Kategori gagal disimpan.", "error");
  }
}

function confirmCategoryRemoval(item) {
  const hard = Number(item.jumlah_pengaduan || 0) === 0;
  openConfirm(
    hard ? "Hapus Kategori" : "Nonaktifkan Kategori",
    hard
      ? "Kategori " + item.nama + " akan dihapus dari master data."
      : "Kategori " + item.nama + " memiliki pengaduan terkait, sehingga akan dinonaktifkan agar riwayat tetap aman.",
    async () => {
      const data = await apiJson(
        "/api/categories/" + item.id + (hard ? "?hard=1" : ""),
        { method: "DELETE" },
      );
      showToast(data.message || "Kategori berhasil diperbarui.");
      await loadCategories();
    },
  );
}

function openConfirm(title, body, action) {
  confirmAction = action;
  document.getElementById("confirm-title").textContent = title;
  document.getElementById("confirm-body").textContent = body;
  const modal = document.getElementById("confirm-modal");
  modal.classList.add("open");
  modal.setAttribute("aria-hidden", "false");
}

function closeConfirm() {
  confirmAction = null;
  const modal = document.getElementById("confirm-modal");
  modal.classList.remove("open");
  modal.setAttribute("aria-hidden", "true");
}

// ==========================================================
// Chunk 4b/4: dataset upload + training pipeline
// ==========================================================

function setDatasetMessage(message, type = "info") {
  const box = document.getElementById("dataset-message");
  box.textContent = message || "";
  box.className = "alert " + type;
  box.style.display = message ? "block" : "none";
}

function setSelectedFile(file) {
  selectedDatasetFile = file;
  document.getElementById("selected-file").textContent =
    file ? file.name : "Belum ada file dipilih.";
  document.getElementById("upload-dataset-btn").disabled = !file;
}

async function uploadDataset() {
  if (!selectedDatasetFile) {
    setDatasetMessage("Pilih file CSV terlebih dahulu.", "error");
    return;
  }
  const button = document.getElementById("upload-dataset-btn");
  button.disabled = true;
  button.textContent = "Memvalidasi...";
  try {
    const form = new FormData();
    form.append("file", selectedDatasetFile);
    const res = await fetch("/api/dataset/upload", { method: "POST", body: form });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Validasi CSV gagal.");
    renderDatasetResult(data);
    await loadTrainingHistory();
  } catch (err) {
    setDatasetMessage(err.message || "Validasi CSV gagal.", "error");
  } finally {
    button.disabled = false;
    button.textContent = "Validasi CSV";
  }
}

function renderDatasetResult(data) {
  const valid = data.valid;
  document.getElementById("start-training-btn").disabled = !valid;
  setDatasetMessage(
    valid
      ? "Dataset valid: " + data.valid_rows + " baris siap dipakai."
      : "Dataset belum valid: " + data.invalid_count + " baris perlu diperbaiki.",
    valid ? "success" : "error",
  );
  const preview = document.getElementById("dataset-preview");
  preview.replaceChildren();
  if (!data.preview.length) {
    preview.appendChild(tableMessageRow("Pratinjau belum tersedia.", 3));
  } else {
    data.preview.forEach((row) => {
      const tr = document.createElement("tr");
      appendCell(tr, row.teks, "td-text");
      appendTagCell(tr, row.kategori, "category");
      appendTagCell(tr, row.urgensi, "gray");
      preview.appendChild(tr);
    });
  }
  const invalid = document.getElementById("invalid-row-list");
  invalid.replaceChildren();
  (data.invalid_rows || []).forEach((row) => {
    const item = document.createElement("div");
    item.className = "invalid-row";
    item.textContent = "Baris " + row.baris + ": " + row.alasan;
    invalid.appendChild(item);
  });
}

async function startTraining() {
  const button = document.getElementById("start-training-btn");
  button.disabled = true;
  button.textContent = "Memulai...";
  try {
    const data = await apiJson("/api/training/start", { method: "POST" });
    renderTrainingStatus(data);
    showToast("Status training diperbarui.");
    await loadTrainingHistory();
  } catch (err) {
    showToast(err.message || "Training gagal dimulai.", "error");
  } finally {
    button.disabled = false;
    button.textContent = "Mulai Training";
  }
}

async function loadTrainingStatus() {
  try {
    const data = await apiJson("/api/training/status");
    renderTrainingStatus(data);
  } catch {
    renderTrainingStatus({ progress: 0, message: "Status training belum tersedia." });
  }
}

function renderTrainingStatus(data) {
  document.getElementById("training-status-text").textContent =
    data.message || "Belum ada proses training berjalan.";
  document.getElementById("training-progress").style.width =
    Math.max(0, Math.min(100, Number(data.progress) || 0)) + "%";
}

async function loadTrainingHistory() {
  try {
    const data = await apiJson("/api/training/history");
    state.trainingHistory = data.data || [];
    renderTrainingHistory();
    renderKpi();
  } catch {
    state.trainingHistory = [];
    renderTrainingHistory();
  }
}

function renderTrainingHistory() {
  const box = document.getElementById("training-history");
  box.replaceChildren();
  if (!state.trainingHistory.length) {
    const empty = document.createElement("div");
    empty.className = "empty-state compact";
    const s = document.createElement("strong");
    s.textContent = "Riwayat training kosong";
    const p = document.createElement("span");
    p.textContent = "Validasi dataset akan muncul di sini.";
    empty.append(s, p);
    box.appendChild(empty);
    return;
  }
  state.trainingHistory.slice(0, 5).forEach((item) => {
    const row = document.createElement("div");
    row.className = "history-card";
    const title = document.createElement("strong");
    title.textContent = item.filename || "Dataset";
    const meta = document.createElement("span");
    meta.textContent =
      (item.status || "-") + " | " + (item.valid_rows || 0) + " valid / " + (item.invalid_rows || 0) + " tidak valid";
    row.append(title, meta);
    box.appendChild(row);
  });
}

// ==========================================================
// Chunk 4c/4: event wiring + boot
// ==========================================================

async function loadAll() {
  await Promise.all([loadCategories(), loadTrainingHistory(), loadTrainingStatus()]);
  await Promise.all([loadStats(), loadRiwayat(state.currentPage)]);
  updateTimestamp();
}

document.querySelectorAll("[data-nav]").forEach((link) => {
  link.addEventListener("click", (event) => {
    event.preventDefault();
    showSection(link.dataset.nav);
  });
});

document.querySelectorAll("[data-nav-trigger]").forEach((link) => {
  link.addEventListener("click", (event) => {
    event.preventDefault();
    showSection(link.dataset.navTrigger);
  });
});

window.addEventListener("hashchange", () => showSection(sectionFromHash(), false));

document.querySelectorAll("[data-filter]").forEach((input) => {
  input.addEventListener("input", () => {
    const key = input.dataset.filter;
    state.filters[key] = input.value.trim();
    syncFilterControls(key);
    if (key === "q") {
      clearTimeout(searchTimer);
      searchTimer = setTimeout(() => loadRiwayat(1), 350);
    }
  });
  input.addEventListener("change", () => {
    const key = input.dataset.filter;
    state.filters[key] = input.value.trim();
    syncFilterControls(key);
    if (key !== "q") loadRiwayat(1);
  });
});

document.querySelectorAll(".filter-apply").forEach((button) =>
  button.addEventListener("click", () => loadRiwayat(1)),
);
document.querySelectorAll(".filter-reset").forEach((button) =>
  button.addEventListener("click", resetFilters),
);

document.querySelectorAll("[data-export]").forEach((button) =>
  button.addEventListener("click", () => exportData(button)),
);

document.getElementById("btn-harian").addEventListener("click", () => setTrendMode("harian"));
document.getElementById("btn-mingguan").addEventListener("click", () => setTrendMode("mingguan"));

document.getElementById("prev-page").addEventListener("click", () => loadRiwayat(state.currentPage - 1));
document.getElementById("next-page").addEventListener("click", () => loadRiwayat(state.currentPage + 1));

document.getElementById("refresh-btn").addEventListener("click", () =>
  loadAll().then(() => showToast("Dashboard diperbarui.")),
);

document.getElementById("detail-close").addEventListener("click", closeDetail);
document.getElementById("detail-drawer").addEventListener("click", (event) => {
  if (event.target.id === "detail-drawer") closeDetail();
});

document.getElementById("category-add").addEventListener("click", () => openCategoryModal());
document.getElementById("category-form").addEventListener("submit", saveCategory);
document.querySelectorAll("[data-close-category]").forEach((button) =>
  button.addEventListener("click", closeCategoryModal),
);
document.getElementById("category-modal").addEventListener("click", (event) => {
  if (event.target.id === "category-modal") closeCategoryModal();
});

document.getElementById("confirm-cancel").addEventListener("click", closeConfirm);
document.getElementById("confirm-ok").addEventListener("click", async () => {
  if (!confirmAction) return closeConfirm();
  try {
    await confirmAction();
  } catch (err) {
    showToast(err.message || "Aksi gagal diproses.", "error");
  } finally {
    closeConfirm();
  }
});

const fileInput = document.getElementById("dataset-file");
const dropZone = document.getElementById("drop-zone");

document.getElementById("choose-file-btn").addEventListener("click", (event) => {
  event.stopPropagation();
  fileInput.click();
});

dropZone.addEventListener("click", (event) => {
  if (event.target.id !== "choose-file-btn") fileInput.click();
});

fileInput.addEventListener("change", () => setSelectedFile(fileInput.files[0] || null));

dropZone.addEventListener("dragover", (event) => {
  event.preventDefault();
  dropZone.classList.add("dragging");
});
dropZone.addEventListener("dragleave", () => dropZone.classList.remove("dragging"));
dropZone.addEventListener("drop", (event) => {
  event.preventDefault();
  dropZone.classList.remove("dragging");
  setSelectedFile(event.dataTransfer.files[0] || null);
});

document.getElementById("upload-dataset-btn").addEventListener("click", uploadDataset);
document.getElementById("start-training-btn").addEventListener("click", startTraining);

showSection(sectionFromHash(), false);
loadAll();
setInterval(loadAll, 30000);
