import {
  AlertTriangle,
  CheckCircle,
  Clock,
  Cpu,
  Database,
  FileText,
  Loader2,
  RefreshCw,
  Trash2,
  XCircle,
} from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import Modal from "../components/Modal";
import Select from "../components/Select";
import api from "../api";

const PAGE_SIZES = [20, 50, 100, 200].map((n) => ({ value: n, label: `${n} baris` }));

function formatTokens(n) {
  if (n === null || n === undefined) return "0";
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
  return String(n);
}

function formatTime(iso) {
  if (!iso) return "-";
  try {
    const d = new Date(iso);
    return d.toLocaleString("id-ID", {
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hour12: false,
    });
  } catch {
    return iso;
  }
}

function formatMaybeJson(text) {
  if (!text) return "-";
  try {
    const parsed = JSON.parse(text);
    return JSON.stringify(parsed, null, 2);
  } catch {
    return text;
  }
}

export default function UsageLogs() {
  const [items, setItems] = useState([]);
  const [total, setTotal] = useState(0);
  const [stats, setStats] = useState(null);
  const [loading, setLoading] = useState(true);
  const [clearing, setClearing] = useState(false);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [detail, setDetail] = useState(null);
  const [detailBody, setDetailBody] = useState(null);
  const [detailBodyLoading, setDetailBodyLoading] = useState(false);
  const [copyStatus, setCopyStatus] = useState(null);
  const [rangeHours, setRangeHours] = useState(24);
  const [statusFilter, setStatusFilter] = useState("all");
  const [formatFilter, setFormatFilter] = useState("");
  const [modelFilter, setModelFilter] = useState("");
  const [statusCodeFilter, setStatusCodeFilter] = useState("");
  const [message, setMessage] = useState(null);

  const getStartTimestamp = useCallback(() => {
    if (!rangeHours || rangeHours <= 0) return null;
    return Math.floor(Date.now() / 1000) - rangeHours * 3600;
  }, [rangeHours]);

  const loadLogs = useCallback(async () => {
    setLoading(true);
    try {
      const offset = (page - 1) * pageSize;
      const start = getStartTimestamp();
      const params = {
        offset,
        limit: pageSize,
        status: statusFilter,
        api_format: formatFilter || undefined,
        model_name: modelFilter.trim() || undefined,
        status_code: statusCodeFilter.trim() ? Number(statusCodeFilter.trim()) : undefined,
        start_timestamp: start ?? undefined,
      };
      const res = await api.get("/usage-logs/list", { params });
      setItems(res.data.items || []);
      setTotal(res.data.total || 0);
    } catch (err) {
      setMessage({ type: "error", text: err.response?.data?.detail || "Gagal memuat log" });
    } finally {
      setLoading(false);
    }
  }, [page, pageSize, statusFilter, formatFilter, modelFilter, statusCodeFilter, getStartTimestamp]);

  const loadStats = useCallback(async () => {
    try {
      const start = getStartTimestamp();
      const params = start ? { start_timestamp: start } : {};
      const res = await api.get("/usage-logs/stats", { params });
      setStats(res.data);
    } catch {
      /* non-blocking */
    }
  }, [getStartTimestamp]);

  useEffect(() => {
    loadLogs();
  }, [loadLogs]);

  useEffect(() => {
    loadStats();
  }, [loadStats]);

  const refresh = () => {
    loadLogs();
    loadStats();
  };

  const clearLogs = async () => {
    if (!window.confirm("Apakah Anda yakin ingin membersihkan log panggilan API yang lebih lama dari 3 hari?")) return;
    setClearing(true);
    try {
      const res = await api.post("/usage-logs/clear", null, { params: { days: 3 } });
      setMessage({ type: "success", text: res.data.message || "Log berhasil dibersihkan" });
      refresh();
    } catch (err) {
      setMessage({ type: "error", text: err.response?.data?.detail || "Gagal membersihkan log" });
    } finally {
      setClearing(false);
    }
  };

  const truncateLogs = async () => {
    if (!window.confirm("Apakah Anda yakin ingin menghapus SELURUH riwayat log panggilan API? Tindakan ini permanen.")) return;
    setClearing(true);
    try {
      const res = await api.post("/usage-logs/clear", null, { params: { days: 0 } });
      setMessage({ type: "success", text: res.data.message || "Seluruh log berhasil dihapus" });
      refresh();
    } catch (err) {
      setMessage({ type: "error", text: err.response?.data?.detail || "Gagal menghapus log" });
    } finally {
      setClearing(false);
    }
  };

  const openRequestBody = async () => {
    if (!detail?.request_log_file) return;
    setDetailBodyLoading(true);
    setCopyStatus(null);
    try {
      const res = await api.get(`/usage-logs/body/${encodeURIComponent(detail.request_log_file)}`);
      setDetailBody(res.data);
    } catch (err) {
      setDetailBody({ __missing: true, __message: err.response?.data?.detail || "Berkas log detail tidak ditemukan atau telah dibersihkan" });
    } finally {
      setDetailBodyLoading(false);
    }
  };

  const copyDetailBody = async () => {
    if (!detailBody || detailBody.__missing) return;
    const text = JSON.stringify(detailBody, null, 2);
    let ok = false;
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(text);
        ok = true;
      }
    } catch {
      ok = false;
    }
    setCopyStatus(ok ? "ok" : "fail");
  };

  const totalPages = Math.max(1, Math.ceil(total / pageSize));

  return (
    <div className="space-y-4">
      {/* Kartu Ringkasan Metrik */}
      {stats && (
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
          <div className="card p-4 flex items-center gap-3">
            <div className="p-2.5 bg-purple-600/20 rounded-lg">
              <Database size={20} className="text-purple-400" />
            </div>
            <div className="min-w-0">
              <div className="text-xl font-bold">{stats.total_requests}</div>
              <div className="text-xs text-gray-500">Total Permintaan</div>
            </div>
          </div>
          <div className="card p-4 flex items-center gap-3">
            <div className="p-2.5 bg-green-600/20 rounded-lg">
              <CheckCircle size={20} className="text-green-400" />
            </div>
            <div className="min-w-0">
              <div className="text-xl font-bold text-green-400">{stats.success_count}</div>
              <div className="text-xs text-gray-500">Berhasil</div>
            </div>
          </div>
          <div className="card p-4 flex items-center gap-3">
            <div className="p-2.5 bg-red-600/20 rounded-lg">
              <XCircle size={20} className="text-red-400" />
            </div>
            <div className="min-w-0">
              <div className="text-xl font-bold text-red-400">{stats.error_count}</div>
              <div className="text-xs text-gray-500">Gagal</div>
            </div>
          </div>
          <div className="card p-4 flex items-center gap-3">
            <div className="p-2.5 bg-blue-600/20 rounded-lg">
              <Cpu size={20} className="text-blue-400" />
            </div>
            <div className="min-w-0">
              <div className="text-xl font-bold">{formatTokens(stats.total_tokens)}</div>
              <div className="text-xs text-gray-500">
                Total Token{stats.cached_tokens > 0 ? ` (Cache ${formatTokens(stats.cached_tokens)})` : ""}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Baris Tombol Aksi */}
      <div className="flex flex-wrap items-center gap-2">
        <button onClick={refresh} disabled={loading} className="btn btn-secondary text-xs sm:text-sm px-3 py-1.5 sm:px-4 sm:py-2 flex items-center gap-1.5">
          <RefreshCw size={15} className={loading ? "animate-spin" : ""} />
          Segarkan
        </button>
        <button onClick={clearLogs} disabled={clearing} className="btn btn-secondary text-xs sm:text-sm px-3 py-1.5 sm:px-4 sm:py-2 flex items-center gap-1.5">
          {clearing ? <Loader2 size={15} className="animate-spin" /> : <Trash2 size={15} />}
          Bersihkan Log &gt; 3 Hari
        </button>
        <button onClick={truncateLogs} disabled={clearing} className="btn btn-danger text-xs sm:text-sm px-3 py-1.5 sm:px-4 sm:py-2 flex items-center gap-1.5">
          <Trash2 size={15} />
          Hapus Semua Log
        </button>
      </div>

      {/* Modal Notifikasi */}
      {message && (
        <Modal type={message.type} title={message.type === "success" ? "Berhasil" : "Gagal"} onClose={() => setMessage(null)}>
          <span className="whitespace-pre-wrap break-all">{message.text}</span>
        </Modal>
      )}

      {/* Filter Log */}
      <div className="grid grid-cols-2 sm:flex sm:flex-wrap gap-2 sm:gap-3 text-sm">
        <Select
          value={rangeHours}
          onChange={(v) => { setRangeHours(Number(v)); setPage(1); }}
          className="w-full sm:w-36"
          options={[
            { value: 1, label: "1 Jam Terakhir" },
            { value: 6, label: "6 Jam Terakhir" },
            { value: 24, label: "24 Jam Terakhir" },
            { value: 24 * 7, label: "7 Hari Terakhir" },
            { value: 24 * 30, label: "30 Hari Terakhir" },
            { value: 0, label: "Semua Waktu" },
          ]}
        />
        <Select
          value={statusFilter}
          onChange={(v) => { setStatusFilter(v); setPage(1); }}
          className="w-full sm:w-36"
          options={[
            { value: "all", label: "Status: Semua" },
            { value: "success", label: "Hanya Berhasil" },
            { value: "error", label: "Hanya Gagal" },
          ]}
        />
        <Select
          value={formatFilter}
          onChange={(v) => { setFormatFilter(v); setPage(1); }}
          className="w-full sm:w-32"
          options={[
            { value: "", label: "Format: Semua" },
            { value: "openai", label: "OpenAI" },
            { value: "gemini", label: "Gemini" },
            { value: "anthropic", label: "Claude" },
          ]}
        />
        <input
          value={modelFilter}
          onChange={(e) => { setModelFilter(e.target.value); setPage(1); }}
          placeholder="Cari model..."
          className="w-full sm:w-40 bg-dark-800 border border-dark-600 rounded-lg px-3 py-2 text-gray-200 text-xs sm:text-sm placeholder-gray-500"
        />
        <input
          value={statusCodeFilter}
          onChange={(e) => { setStatusCodeFilter(e.target.value); setPage(1); }}
          placeholder="Status HTTP..."
          inputMode="numeric"
          className="w-full sm:w-28 bg-dark-800 border border-dark-600 rounded-lg px-3 py-2 text-gray-200 text-xs sm:text-sm placeholder-gray-500"
        />
        <Select
          value={pageSize}
          onChange={(v) => { setPageSize(Number(v)); setPage(1); }}
          className="w-full sm:w-32"
          options={PAGE_SIZES}
        />
      </div>

      {/* Tabel / Daftar Riwayat Log */}
      {loading ? (
        <div className="flex items-center justify-center py-12">
          <Loader2 className="animate-spin text-purple-500" size={28} />
        </div>
      ) : items.length === 0 ? (
        <div className="card p-8 text-center text-gray-500">Belum ada riwayat log permintaan</div>
      ) : (
        <div className="space-y-2">
          {items.map((item) => (
            <button
              key={item.id}
              onClick={() => { setDetail(item); setDetailBody(null); }}
              className="card p-3 sm:p-4 w-full text-left hover:border-purple-500/40 transition-colors cursor-pointer"
            >
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className={`text-xs px-1.5 py-0.5 rounded ${item.success ? "bg-green-500/15 text-green-400" : "bg-red-500/15 text-red-400"}`}>
                      {item.success ? "✓ Berhasil" : `✗ ${item.status_code || "Gagal"}`}
                    </span>
                    <span className="text-sm font-medium text-gray-200 truncate">{item.model_name || "(unknown)"}</span>
                    {item.upstream_model_name && item.upstream_model_name !== item.model_name && (
                      <span className="text-xs text-gray-500 truncate" title="Model Upstream">→ {item.upstream_model_name}</span>
                    )}
                    <span className="text-xs px-1.5 py-0.5 rounded bg-dark-700 text-gray-400">
                      {item.api_format === "openai" ? "OpenAI" : item.api_format === "gemini" ? "Gemini" : item.api_format === "anthropic" ? "Claude" : item.api_format || "?"}
                    </span>
                    {item.is_stream && <span className="text-xs px-1.5 py-0.5 rounded bg-blue-500/15 text-blue-400">Streaming</span>}
                    {item.request_log_file && <span className="text-xs px-1.5 py-0.5 rounded bg-amber-500/15 text-amber-400">Rinci</span>}
                  </div>
                  <div className="text-xs text-gray-500 mt-1 flex flex-wrap gap-x-3 gap-y-0.5">
                    <span className="flex items-center gap-1"><Clock size={11} />{formatTime(item.created_at)}</span>
                    <span>{(item.use_time || 0).toFixed(2)}s</span>
                    <span>{item.credential_email || "-"}</span>
                  </div>
                </div>
                <div className="text-right shrink-0 text-xs text-gray-400">
                  <div>{formatTokens(item.total_tokens)} token</div>
                  <div className="text-gray-600">
                    ↑{formatTokens(item.prompt_tokens)} ↓{formatTokens(item.completion_tokens)}
                  </div>
                  {item.cached_tokens > 0 && (
                    <div className="text-emerald-500/80" title="Token yang terkena prompt cache">
                      ⚡Cache {formatTokens(item.cached_tokens)}
                    </div>
                  )}
                </div>
              </div>
            </button>
          ))}
        </div>
      )}

      {/* Navigasi Halaman */}
      {total > 0 && (
        <div className="flex items-center justify-between text-sm text-gray-400">
          <span>Total {total} log</span>
          <div className="flex items-center gap-2">
            <button
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              disabled={page <= 1}
              className="btn btn-secondary text-xs px-3 py-1.5 disabled:opacity-40"
            >
              Sebelumnya
            </button>
            <span>{page} / {totalPages}</span>
            <button
              onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
              disabled={page >= totalPages}
              className="btn btn-secondary text-xs px-3 py-1.5 disabled:opacity-40"
            >
              Berikutnya
            </button>
          </div>
        </div>
      )}

      {/* Modal Rincian Permintaan */}
      {detail && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60" onClick={() => setDetail(null)}>
          <div className="card max-w-lg w-full max-h-[80vh] overflow-y-auto" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-base font-semibold text-purple-400">Rincian Permintaan</h3>
              <button onClick={() => setDetail(null)} className="text-gray-400 hover:text-white">✕</button>
            </div>
            <div className="space-y-2 text-sm">
              {[
                ["Waktu", formatTime(detail.created_at)],
                ["ID Permintaan", detail.request_id || "-"],
                ["Status", detail.success ? "Berhasil" : `Gagal (${detail.status_code})`],
                ["Format API", detail.api_format || "-"],
                ["IP Klien", detail.client_ip || "-"],
                ["Model Diminta", detail.model_name || "-"],
                ["Model Upstream", detail.upstream_model_name || detail.model_name || "-"],
                ["Akun / Kredensial", detail.credential_email || "-"],
                ["Streaming (SSE)", detail.is_stream ? "Ya" : "Tidak"],
                ["Durasi", `${(detail.use_time || 0).toFixed(2)} detik`],
                ["Total Token", `${formatTokens(detail.total_tokens)} (Masuk: ${formatTokens(detail.prompt_tokens)}, Keluar: ${formatTokens(detail.completion_tokens)})`],
                ...(detail.cached_tokens > 0 ? [["Token Cache", String(detail.cached_tokens)]] : []),
              ].map(([k, v]) => (
                <div key={k} className="flex justify-between py-1 border-b border-dark-700/50">
                  <span className="text-gray-500">{k}</span>
                  <span className="font-mono text-gray-200 text-xs sm:text-sm text-right break-all max-w-[65%]">{v}</span>
                </div>
              ))}
              {detail.error_message && (
                <div>
                  <div className="text-gray-500 mb-1">Pesan Kesalahan</div>
                  <div className="bg-red-500/10 border border-red-500/30 rounded-lg p-2.5 text-xs text-red-300 break-all">
                    {detail.error_message}
                  </div>
                </div>
              )}
              {detail.request_log_file && (
                <div className="pt-2">
                  <div className="flex items-center justify-between gap-2">
                    <div className="text-gray-500">Log Rinci Payload</div>
                    <button
                      onClick={openRequestBody}
                      disabled={detailBodyLoading}
                      className="btn btn-secondary text-xs px-3 py-1.5 flex items-center gap-1.5"
                    >
                      {detailBodyLoading ? <Loader2 size={13} className="animate-spin" /> : <FileText size={13} />}
                      Lihat Payload Rinci
                    </button>
                  </div>
                  <p className="text-xs text-gray-500 mt-1.5">
                    Payload lengkap (header dan body) disimpan untuk memudahkan investigasi error upstream (seperti 400).
                  </p>
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Modal Detail Payload Log */}
      {detailBody && (
        <div className="fixed inset-0 z-[60] flex items-center justify-center p-4 bg-black/70" onClick={() => setDetailBody(null)}>
          <div className="card max-w-4xl w-full max-h-[85vh] overflow-y-auto" onClick={(e) => e.stopPropagation()}>
            {detailBody.__missing ? (
              <div className="py-8 text-center text-sm text-gray-400">
                <AlertTriangle size={28} className="mx-auto mb-3 text-amber-400" />
                <div>{detailBody.__message}</div>
                <div className="text-xs text-gray-500 mt-2">Berkas log di disk kemungkinan telah dibersihkan atau dihapus manual.</div>
              </div>
            ) : (
              <>
                <div className="flex items-center justify-between mb-3">
                  <h3 className="text-base font-semibold text-purple-400">Payload Permintaan Rinci</h3>
                  <div className="flex items-center gap-2">
                    {copyStatus === "ok" && <span className="text-xs text-green-400">Tersalin</span>}
                    {copyStatus === "fail" && <span className="text-xs text-red-400">Gagal menyalin</span>}
                    <button onClick={copyDetailBody} className="btn btn-secondary text-xs px-3 py-1.5">
                      Salin JSON
                    </button>
                    <button onClick={() => setDetailBody(null)} className="text-gray-400 hover:text-white">✕</button>
                  </div>
                </div>
                <div className="space-y-3 text-xs">
                  <div>
                    <div className="text-gray-400 mb-1">URL Permintaan</div>
                    <pre className="bg-dark-800 border border-dark-600 rounded-lg p-2.5 overflow-x-auto text-gray-200 whitespace-pre-wrap break-all">{detailBody.url || "-"}</pre>
                  </div>
                  <div>
                    <div className="text-gray-400 mb-1">Header Permintaan (Tersanitasi)</div>
                    <pre className="bg-dark-800 border border-dark-600 rounded-lg p-2.5 overflow-x-auto text-gray-200">{JSON.stringify(detailBody.request_headers || {}, null, 2)}</pre>
                  </div>
                  <div>
                    <div className="text-gray-400 mb-1">Body Permintaan</div>
                    <pre className="bg-dark-800 border border-dark-600 rounded-lg p-2.5 overflow-x-auto text-gray-200">{JSON.stringify(detailBody.request_body ?? {}, null, 2)}</pre>
                  </div>
                  {detailBody.response_body && (
                    <div>
                      <div className="text-gray-400 mb-1">Respons Upstream</div>
                      <pre className="bg-dark-800 border border-dark-600 rounded-lg p-2.5 overflow-x-auto text-gray-200 whitespace-pre-wrap break-all">{formatMaybeJson(detailBody.response_body)}</pre>
                    </div>
                  )}
                  {detailBody.error_message && (
                    <div>
                      <div className="text-gray-400 mb-1">Ringkasan Error</div>
                      <pre className="bg-red-500/10 border border-red-500/30 rounded-lg p-2.5 overflow-x-auto text-red-300 whitespace-pre-wrap break-all">{detailBody.error_message}</pre>
                    </div>
                  )}
                </div>
              </>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
