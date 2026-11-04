import { Loader2, Plus, RefreshCw, Save, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import Modal from "../components/Modal";
import Select from "../components/Select";
import api from "../api";

function CsvNumbersField({ value, onChange, placeholder }) {
  const [text, setText] = useState(() =>
    Array.isArray(value) ? value.join(", ") : ""
  );

  useEffect(() => {
    setText(Array.isArray(value) ? value.join(", ") : "");
  }, [value]);

  const parseToNumbers = (raw) => {
    return raw
      .split(/[,，\s]+/)
      .map((s) => s.trim())
      .filter((s) => /^\d+$/.test(s))
      .map(Number)
      .filter((n) => n >= 100 && n <= 599);
  };

  const handleBlur = () => {
    const numbers = parseToNumbers(text);
    onChange(numbers);
    setText(numbers.join(", "));
  };

  const handleChange = (e) => {
    const raw = e.target.value;
    setText(raw);
    onChange(parseToNumbers(raw));
  };

  return (
    <input
      type="text"
      value={text}
      onChange={handleChange}
      onBlur={handleBlur}
      placeholder={placeholder}
      className="w-full px-3 py-2 bg-dark-800 border border-dark-600 rounded-lg text-sm text-white placeholder-gray-500 font-mono"
    />
  );
}

const CONFIG_GROUPS = [
  {
    title: "Konfigurasi Server",
    fields: [
      { key: "host", label: "Host Server", type: "text", note: "Alamat host server (0.0.0.0 mendengarkan seluruh antarmuka jaringan; berlaku setelah restart)" },
      { key: "port", label: "Port Server", type: "number", note: "Port layanan (berlaku setelah restart)" },
      { key: "api_password", label: "Kunci Akses API (API Password)", type: "text", note: "Kunci akses untuk endpoint OpenAI, Gemini, dan Claude" },
      { key: "panel_password", label: "Kata Sandi Panel Kontrol", type: "text", note: "Kata sandi otorisasi untuk masuk ke panel web ini" },
    ],
  },
  {
    title: "Whitelist Alamat IP",
    fields: [
      { key: "ip_whitelist_enabled", label: "Aktifkan Whitelist IP", type: "bool", note: "Jika aktif, hanya IP yang terdaftar yang dapat mengakses API dan panel (IP lain langsung 403)" },
      { key: "ip_whitelist", label: "Daftar Whitelist IP", type: "textarea", showIf: (cfg) => !!cfg.ip_whitelist_enabled, note: "Satu IP atau CIDR per baris (mendukung IPv4 dan IPv6). Contoh: 127.0.0.1, 192.168.1.0/24", placeholder: "127.0.0.1\n192.168.1.0/24\n::1" },
    ],
  },
  {
    title: "Konfigurasi Dasar",
    fields: [
      { key: "credentials_dir", label: "Direktori Kredensial", type: "text", note: "Lokasi penyimpanan berkas kredensial akun" },
      { key: "proxy", label: "Proksi Keluar (Outbound Proxy)", type: "text", note: "Mendukung http/https/socks5/socks5h (contoh: socks5h://127.0.0.1:1080); kosongkan jika koneksi langsung", placeholder: "http://user:pass@proxy:port atau socks5h://proxy:port" },
    ],
  },
  {
    title: "Konfigurasi Endpoint",
    fields: [
      { key: "oauth_proxy_url", label: "Endpoint OAuth", type: "text", note: "URL endpoint Google OAuth2 untuk pembuatan dan penyegaran token" },
      { key: "googleapis_proxy_url", label: "Endpoint Google APIs", type: "text", note: "URL endpoint Google APIs upstream" },
      { key: "antigravity_api_url", label: "Endpoint API Antigravity", type: "text", note: "URL endpoint layanan backend Antigravity" },
    ],
  },
  {
    title: "Pemblokiran Otomatis (Auto-Ban)",
    fields: [
      { key: "auto_ban_enabled", label: "Aktifkan Auto-Ban", type: "bool", note: "Otomatis menonaktifkan kredensial jika menemui kode status error tertentu" },
      { key: "auto_ban_error_codes", label: "Daftar Kode Error Auto-Ban", type: "text", note: "Format array JSON, contoh: [403, 400]" },
    ],
  },
  {
    title: "Percobaan Ulang (Retry)",
    fields: [
      { key: "retry_429_enabled", label: "Aktifkan Retry Otomatis", type: "bool", note: "Mencoba ulang permintaan saat menemui batas laju (Rate Limit / 429)" },
      { key: "retry_429_max_retries", label: "Maksimal Percobaan", type: "number", note: "Jumlah maksimal pengulangan permintaan" },
      { key: "retry_429_interval", label: "Jeda Waktu Antar Percobaan (Detik)", type: "number", note: "Waktu tunggu sebelum mencoba ulang (0 untuk langsung)" },
    ],
  },
  {
    title: "Metode Pemilihan Kredensial",
    fields: [
      {
        key: "credential_select_mode",
        label: "Mode Pemilihan",
        type: "select",
        note: "Menentukan bagaimana akun/kredensial dipilih untuk tiap panggilan API",
        options: [
          { value: "random", label: "Acak Seimbang (Random)" },
          { value: "cache", label: "Pencocokan Cache (Rekomendasi)" },
          { value: "sticky", label: "Tetap pada Satu Akun (Sticky)" },
        ],
        descriptions: {
          random: "Acak Seimbang: Memilih kredensial aktif secara acak pada setiap request untuk membagi beban secara merata.",
          cache: "Pencocokan Cache: Mengelompokkan sesi obrolan yang sama ke kredensial yang sama agar memanfaatkan prompt caching upstream Google, menghemat token dan mempercepat respons.",
          sticky: "Sticky: Mengunci seluruh request ke satu kredensial sampai akun tersebut terkena cooldown (429) atau dinonaktifkan.",
        },
      },
    ],
  },
  {
    title: "Konfigurasi Respons",
    fields: [
      { key: "return_thoughts_to_frontend", label: "Kirim Reasoning / Thinking ke Klien", type: "bool", note: "Jika aktif, proses berpikir internal (thinking chain) akan disertakan dalam respons" },
    ],
  },
  {
    title: "Anti-Pemotongan Respons (Anti-Truncation)",
    fields: [
      { key: "anti_truncation_max_attempts", label: "Batas Maksimal Percobaan Penyambungan", type: "number", note: "Jumlah maksimal percobaan menyambung jawaban panjang yang terpotong (1-10)" },
    ],
  },
  {
    title: "Filter Kata Sensitif",
    fields: [
      { key: "sensitive_words_enabled", label: "Aktifkan Filter Kata Sensitif", type: "bool", note: "Menyaring kata sensitif agar tidak memicu pemblokiran upstream Google" },
      { key: "sensitive_words", label: "Daftar Kata Sensitif", type: "textarea", showIf: (cfg) => !!cfg.sensitive_words_enabled, note: "Satu kata/frasa per baris (tidak membedakan huruf besar/kecil)", placeholder: "kata1\nkata2" },
    ],
  },
  {
    title: "Pemetaan Nama Model (Model Rewrite)",
    fields: [
      { key: "model_rewrite_enabled", label: "Aktifkan Pemetaan Nama Model", type: "bool", note: "Memetakan nama model dari klien ke model aktual upstream yang tersedia" },
      {
        key: "model_rewrite_rules",
        label: "Daftar Aturan (Regex)",
        type: "rules",
        showIf: (cfg) => !!cfg.model_rewrite_enabled,
        note: "Cocokkan nama model (Regex) → Gantikan dengan model upstream",
      },
    ],
  },
  {
    title: "Log Permintaan & Analitik",
    fields: [
      { key: "usage_log_enabled", label: "Aktifkan Pencatatan Log", type: "bool", note: "Mencatat setiap panggilan API (model, token, durasi, status) ke database" },
      { key: "request_log_enabled", label: "Simpan Detail Request Body saat Terjadi Error", type: "bool", note: "Menyimpan payload JSON permintaan saat menemui status error untuk keperluan debugging" },
      { key: "request_log_error_codes", label: "Kode Status Error yang Direkam Rinci", type: "csv_numbers", showIf: (cfg) => !!cfg.request_log_enabled, note: "Pisahkan dengan koma (contoh: 400, 429)", placeholder: "400, 429" },
    ],
  },
];

export default function Config() {
  const [config, setConfig] = useState({});
  const [envLocked, setEnvLocked] = useState([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState(null);

  useEffect(() => {
    loadConfig();
  }, []);

  const loadConfig = async ({ silent = false } = {}) => {
    setLoading(true);
    try {
      const res = await api.get("/config/get");
      setConfig(res.data.config || {});
      setEnvLocked(res.data.env_locked || []);
      if (!silent) setMessage(null);
    } catch (err) {
      setMessage({ type: "error", text: err.response?.data?.detail || "Gagal memuat konfigurasi" });
    } finally {
      setLoading(false);
    }
  };

  const saveConfig = async () => {
    setSaving(true);
    try {
      const res = await api.post("/config/save", { config });
      setMessage({ type: "success", text: res.data.message || "Pengaturan berhasil disimpan" });
      await loadConfig({ silent: true });
    } catch (err) {
      setMessage({ type: "error", text: err.response?.data?.detail || "Gagal menyimpan pengaturan" });
    } finally {
      setSaving(false);
    }
  };

  const setField = (key, value) => {
    setConfig((prev) => ({ ...prev, [key]: value }));
  };

  const OFFICIAL_ENDPOINTS = {
    oauth_proxy_url: "https://oauth2.googleapis.com",
    googleapis_proxy_url: "https://www.googleapis.com",
    antigravity_api_url: "https://daily-cloudcode-pa.googleapis.com",
  };

  const restoreOfficialUrls = () => {
    setConfig((prev) => {
      const next = { ...prev };
      for (const [key, url] of Object.entries(OFFICIAL_ENDPOINTS)) {
        if (!envLocked.includes(key)) next[key] = url;
      }
      return next;
    });
  };

  const renderField = (field) => {
    const isLocked = envLocked.includes(field.key);
    const value = config[field.key] ?? "";

    if (isLocked) {
      return (
        <div className="text-xs text-amber-400/80 bg-amber-500/10 border border-amber-500/20 rounded-lg px-3 py-2">
          Nilai ini terkunci oleh variabel environment (.env / OS). Ubah variabel environment untuk menggantinya.
        </div>
      );
    }

    if (field.type === "bool") {
      return (
        <label className="flex items-center gap-3 cursor-pointer select-none">
          <button
            type="button"
            onClick={() => setField(field.key, !value)}
            className={`relative w-11 h-6 rounded-full transition-colors ${
              value ? "bg-purple-600" : "bg-dark-600"
            }`}
          >
            <span
              className={`absolute top-0.5 left-0.5 w-5 h-5 bg-white rounded-full transition-transform ${
                value ? "translate-x-5" : ""
              }`}
            />
          </button>
          <span className="text-sm text-gray-300">{value ? "Aktif" : "Nonaktif"}</span>
        </label>
      );
    }

    if (field.type === "select") {
      const current = field.options.find((o) => o.value === value) || field.options[0];
      return (
        <div className="space-y-2">
          <Select
            value={current?.value ?? ""}
            onChange={(v) => setField(field.key, v)}
            options={field.options}
            className="w-full sm:w-72"
          />
          {field.descriptions && current && (
            <div className="bg-dark-800/60 border border-dark-600 rounded-lg p-3 text-xs sm:text-sm text-gray-300 leading-relaxed">
              {field.descriptions[current.value]}
            </div>
          )}
        </div>
      );
    }

    if (field.type === "csv_numbers") {
      return (
        <CsvNumbersField
          value={value}
          onChange={(v) => setField(field.key, v)}
          placeholder={field.placeholder}
        />
      );
    }

    if (field.type === "rules") {
      const rules = Array.isArray(value)
        ? value.map((r) => (Array.isArray(r) ? [String(r[0] ?? ""), String(r[1] ?? "")] : ["", ""]))
        : [];
      const updateRule = (idx, col, val) => {
        const next = rules.map((r) => [...r]);
        next[idx][col] = val;
        setField(field.key, next);
      };
      const removeRule = (idx) => {
        setField(field.key, rules.filter((_, i) => i !== idx));
      };
      const addRule = () => {
        setField(field.key, [...rules, ["", ""]]);
      };
      return (
        <div className="space-y-2">
          {rules.length === 0 && (
            <div className="text-xs text-gray-500 bg-dark-800/60 border border-dark-700 rounded-lg px-3 py-2">
              Belum ada aturan pemetaan. Klik tombol di bawah untuk menambah.
            </div>
          )}
          {rules.map((rule, idx) => (
            <div key={idx} className="flex items-center gap-2">
              <input
                type="text"
                value={rule[0]}
                onChange={(e) => updateRule(idx, 0, e.target.value)}
                placeholder="Pola Regex (cth: ^gpt-4$)"
                className="flex-1 min-w-0 px-3 py-2 bg-dark-800 border border-dark-600 rounded-lg text-sm text-white placeholder-gray-500 font-mono"
              />
              <span className="text-gray-500 text-sm shrink-0">→</span>
              <input
                type="text"
                value={rule[1]}
                onChange={(e) => updateRule(idx, 1, e.target.value)}
                placeholder="Model Target (cth: gemini-2.5-pro)"
                className="flex-1 min-w-0 px-3 py-2 bg-dark-800 border border-dark-600 rounded-lg text-sm text-white placeholder-gray-500 font-mono"
              />
              <button
                type="button"
                onClick={() => removeRule(idx)}
                className="shrink-0 p-2 text-gray-500 hover:text-red-400 transition-colors"
                title="Hapus aturan ini"
              >
                <Trash2 size={16} />
              </button>
            </div>
          ))}
          <button
            type="button"
            onClick={addRule}
            className="btn btn-secondary text-xs px-3 py-1.5 flex items-center gap-1.5"
          >
            <Plus size={14} />
            Tambah Aturan Pemetaan
          </button>
        </div>
      );
    }

    if (field.type === "textarea") {
      return (
        <textarea
          value={Array.isArray(value) ? value.join("\n") : value || ""}
          onChange={(e) => {
            const lines = e.target.value === "" ? [] : e.target.value.split("\n");
            setField(field.key, lines.map((w) => w.replace(/\s+$/, "")).filter((w) => w.trim() !== ""))
          }}
          placeholder={field.placeholder}
          rows={6}
          className="w-full px-3 py-2 bg-dark-800 border border-dark-600 rounded-lg text-sm text-white placeholder-gray-500 font-mono"
        />
      );
    }

    return (
      <input
        type={field.type}
        value={value}
        onChange={(e) =>
          setField(
            field.key,
            field.type === "number" ? Number(e.target.value) : e.target.value
          )
        }
        placeholder={field.placeholder}
        className="w-full px-3 py-2 bg-dark-800 border border-dark-600 rounded-lg text-sm text-white placeholder-gray-500"
      />
    );
  };

  return (
    <div className="space-y-6">
      {/* Tombol Aksi Tetap di Atas */}
      <div className="sticky top-0 z-30 -mx-1 px-1 py-2 bg-dark-950/95 backdrop-blur border-b border-dark-700 rounded-lg">
        <div className="flex items-center gap-2">
          <button
            onClick={loadConfig}
            disabled={loading}
            className="btn btn-secondary text-sm flex items-center gap-1.5"
          >
            <RefreshCw size={15} className={loading ? "animate-spin" : ""} />
            Segarkan Pengaturan
          </button>
          <button
            onClick={saveConfig}
            disabled={saving || loading}
            className="btn btn-primary text-sm flex items-center gap-1.5 disabled:opacity-50"
          >
            {saving ? <Loader2 size={15} className="animate-spin" /> : <Save size={15} />}
            {saving ? "Menyimpan..." : "Simpan Pengaturan"}
          </button>
        </div>
      </div>

      {/* Modal Notifikasi */}
      {message && (
        <Modal type={message.type} title={message.type === "success" ? "Berhasil" : "Gagal"} onClose={() => setMessage(null)}>
          <span className="whitespace-pre-wrap break-all">{message.text}</span>
        </Modal>
      )}

      {loading ? (
        <div className="flex items-center justify-center py-12">
          <Loader2 className="animate-spin text-purple-500" size={28} />
        </div>
      ) : (
        <div className="space-y-6">
          {CONFIG_GROUPS.map((group) => (
            <div key={group.title} className="card">
              <h3 className="text-base font-semibold text-purple-400 mb-4 border-b border-dark-700 pb-3">
                {group.title}
              </h3>

              {group.title === "Konfigurasi Endpoint" && (
                <div className="flex flex-wrap gap-2 mb-4">
                  <button
                    type="button"
                    onClick={restoreOfficialUrls}
                    className="btn btn-secondary text-xs px-3 py-1.5"
                  >
                    🔄 Kembalikan ke Endpoint Resmi Google
                  </button>
                </div>
              )}

              <div className="space-y-5">
                {group.fields
                  .filter((field) => !field.showIf || field.showIf(config))
                  .map((field) => (
                    <div key={field.key}>
                      <label className="block text-sm font-medium text-gray-300 mb-1.5">
                        {field.label}
                      </label>
                      {renderField(field)}
                      {field.note && (
                        <p className="text-xs text-gray-500 mt-1.5">{field.note}</p>
                      )}
                    </div>
                  ))}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
