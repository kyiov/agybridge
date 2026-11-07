import {
  AlertCircle,
  BarChart3,
  Check,
  CheckCircle2,
  Copy,
  Cpu,
  Eye,
  EyeOff,
  Filter,
  Info,
  Loader2,
  Lock,
  Network,
  Plus,
  RefreshCw,
  Save,
  Search,
  Shield,
  Sliders,
  Trash2,
  Zap,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
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
      className="w-full px-3.5 py-2.5 bg-dark-900 border border-dark-600 rounded-xl text-sm text-white placeholder-gray-500 font-mono focus:outline-none focus:border-purple-500 transition-colors"
    />
  );
}

function LinesField({ value, onChange, placeholder }) {
  const toText = (v) => (Array.isArray(v) ? v.join("\n") : v ?? "");
  const [text, setText] = useState(() => toText(value));
  const focusedRef = useRef(false);

  useEffect(() => {
    if (!focusedRef.current) setText(toText(value));
  }, [value]);

  const commitText = (raw) => {
    const lines = raw
      .split(/\r?\n/)
      .map((w) => w.replace(/\s+$/, ""))
      .filter((w) => w.trim() !== "");
    onChange(lines);
  };

  return (
    <textarea
      value={text}
      onFocus={() => {
        focusedRef.current = true;
      }}
      onChange={(e) => {
        const raw = e.target.value;
        setText(raw);
        commitText(raw);
      }}
      onBlur={() => {
        focusedRef.current = false;
        commitText(text);
      }}
      placeholder={placeholder}
      rows={5}
      className="w-full px-3.5 py-2.5 bg-dark-900 border border-dark-600 rounded-xl text-xs text-white placeholder-gray-500 font-mono focus:outline-none focus:border-purple-500"
    />
  );
}

// 5 Kategori Terstruktur & Bersih
const CATEGORIES = [
  { id: "all", label: "Semua", icon: Sliders },
  { id: "security", label: "Keamanan & Server", icon: Shield },
  { id: "routing", label: "Jaringan & Routing", icon: Network },
  { id: "models", label: "Model & Respons", icon: Cpu },
  { id: "stability", label: "Stabilitas & Retry", icon: RefreshCw },
  { id: "logs", label: "Log & Analitik", icon: BarChart3 },
];

const CONFIG_GROUPS = [
  {
    category: "security",
    title: "Konfigurasi Host & Kunci Akses",
    description: "Pengaturan identitas jaringan dan kata sandi otorisasi akses API serta panel.",
    fields: [
      {
        key: "host",
        label: "Host Binding Server",
        type: "text",
        note: "Gunakan 0.0.0.0 untuk mendengarkan seluruh antarmuka jaringan (berlaku setelah restart)",
      },
      {
        key: "port",
        label: "Port Layanan HTTP",
        type: "number",
        note: "Port layanan web dan gateway (berlaku setelah restart)",
      },
      {
        key: "api_password",
        label: "Kunci Akses API (API Password)",
        type: "password_toggle",
        note: "Kunci akses Bearer token untuk endpoint OpenAI, Claude, dan Gemini",
      },
      {
        key: "panel_password",
        label: "Kata Sandi Panel Web",
        type: "password_toggle",
        note: "Kata sandi yang digunakan saat login ke panel dashboard ini",
      },
    ],
  },
  {
    category: "security",
    title: "Whitelist Alamat IP",
    description: "Batasi akses masuk hanya ke alamat IP atau subnet CIDR tepercaya.",
    fields: [
      {
        key: "ip_whitelist_enabled",
        label: "Aktifkan Proteksi Whitelist IP",
        type: "bool",
        note: "Jika diaktifkan, IP di luar daftar akan langsung ditolak (HTTP 403)",
      },
      {
        key: "ip_whitelist",
        label: "Daftar Alamat IP / CIDR yang Diizinkan",
        type: "textarea",
        showIf: (cfg) => !!cfg.ip_whitelist_enabled,
        note: "Satu IP atau CIDR per baris (mendukung IPv4 dan IPv6). Contoh: 127.0.0.1 atau 192.168.1.0/24",
        placeholder: "127.0.0.1\n192.168.1.0/24\n::1",
      },
    ],
  },
  {
    category: "security",
    title: "Filter Kata Sensitif",
    description: "Cegah kata atau frasa tertentu agar tidak memicu pembatasan upstream.",
    fields: [
      {
        key: "sensitive_words_enabled",
        label: "Aktifkan Filter Kata Sensitif",
        type: "bool",
        note: "Menyaring kata sensitif pada payload pertanyaan sebelum diteruskan",
      },
      {
        key: "sensitive_words",
        label: "Daftar Kata Sensitif",
        type: "textarea",
        showIf: (cfg) => !!cfg.sensitive_words_enabled,
        note: "Satu kata/frasa per baris (tidak membedakan huruf besar/kecil)",
        placeholder: "kata1\nkata2",
      },
    ],
  },
  {
    category: "routing",
    title: "Metode Pemilihan Kredensial (Load Balancing)",
    description: "Atur strategi pemilihan akun upstream Google Antigravity untuk setiap request masuk.",
    fields: [
      {
        key: "credential_select_mode",
        label: "Strategi Rotasi Akun",
        type: "select",
        note: "Pilih metode distribusi beban antar akun Google yang terdaftar",
        options: [
          { value: "cache", label: "Pencocokan Cache Hash (Sangat Direkomendasikan)" },
          { value: "random", label: "Acak Seimbang (Random Balance)" },
          { value: "sticky", label: "Kunci Satu Akun (Sticky Mode)" },
        ],
        descriptions: {
          cache: "Cache Hash: Mengelompokkan sesi obrolan yang sama ke kredensial yang sama agar memanfaatkan prompt caching upstream Google secara optimal, menghemat token dan mempercepat respons.",
          random: "Random Balance: Memilih akun aktif secara acak pada setiap request untuk membagi beban secara merata ke seluruh akun.",
          sticky: "Sticky Mode: Mengunci seluruh request ke satu akun sampai akun tersebut terkena cooldown (429) atau dinonaktifkan.",
        },
      },
    ],
  },
  {
    category: "routing",
    title: "Koneksi Proksi & Direktori Kredensial",
    description: "Konfigurasi rute keluar (outbound proxy) dan lokasi penyimpanan akun.",
    fields: [
      {
        key: "credentials_dir",
        label: "Direktori Berkas Kredensial",
        type: "text",
        note: "Lokasi folder penyimpanan kredensial akun JSON di server",
      },
      {
        key: "proxy",
        label: "Proksi Keluar (Outbound Proxy)",
        type: "text",
        note: "Mendukung http/https/socks5/socks5h. Kosongkan jika server terhubung langsung ke internet.",
        placeholder: "http://user:pass@proxy:port atau socks5h://127.0.0.1:1080",
      },
    ],
  },
  {
    category: "routing",
    title: "Konfigurasi Endpoint Upstream Google",
    description: "Titik akhir layanan Google APIs dan Antigravity.",
    hasRestoreButton: true,
    fields: [
      {
        key: "oauth_proxy_url",
        label: "Endpoint Google OAuth2",
        type: "text",
        note: "URL endpoint untuk pembuatan dan penyegaran access token",
      },
      {
        key: "googleapis_proxy_url",
        label: "Endpoint Google APIs",
        type: "text",
        note: "URL endpoint upstream Google APIs",
      },
      {
        key: "antigravity_api_url",
        label: "Endpoint API Antigravity",
        type: "text",
        note: "URL endpoint layanan Cloud Code / Antigravity",
      },
    ],
  },
  {
    category: "models",
    title: "Pemetaan Nama Model (Model Rewrite)",
    description: "Aliaskan atau ubah nama model klien ke model upstream yang tersedia secara transparan.",
    fields: [
      {
        key: "model_rewrite_enabled",
        label: "Aktifkan Pemetaan Nama Model",
        type: "bool",
        note: "Memetakan request model dari klien (misal gpt-4o) ke model upstream (misal gemini-3.8-flash-high)",
      },
      {
        key: "model_rewrite_rules",
        label: "Daftar Aturan Regex Pemetaan",
        type: "rules",
        showIf: (cfg) => !!cfg.model_rewrite_enabled,
        note: "Format: Cocokkan Pola Regex → Gantikan dengan Model Target Upstream",
      },
    ],
  },
  {
    category: "models",
    title: "Perilaku Respons & Anti-Pemotongan",
    description: "Pengaturan pemrosesan token penalaran dan perpanjangan respons teks panjang.",
    fields: [
      {
        key: "return_thoughts_to_frontend",
        label: "Kirim Reasoning / Thinking Process ke Klien",
        type: "bool",
        note: "Jika aktif, proses berpikir internal model disertakan pada output reasoning",
      },
      {
        key: "anti_truncation_max_attempts",
        label: "Batas Maksimal Percobaan Sambung Teks (Anti-Truncate)",
        type: "number",
        note: "Batas pengulangan penyambungan otomatis jika jawaban terpotong batas token (1 - 10)",
      },
    ],
  },
  {
    category: "stability",
    title: "Percobaan Ulang Otomatis (Retry 429)",
    description: "Penanganan otomatis saat menghadapi batas laju request (Rate Limit) dari Google.",
    fields: [
      {
        key: "retry_429_enabled",
        label: "Aktifkan Retry Otomatis pada HTTP 429",
        type: "bool",
        note: "Otomatis mengulangi permintaan jika terkena pembatasan laju",
      },
      {
        key: "retry_429_max_retries",
        label: "Maksimal Percobaan Pengulangan",
        type: "number",
        note: "Jumlah pengulangan maksimal sebelum mengembalikan error ke klien (1 - 10)",
      },
      {
        key: "retry_429_interval",
        label: "Jeda Waktu Antar Percobaan (Detik)",
        type: "number",
        note: "Waktu tunggu sebelum mencoba akun berikutnya (0 untuk langsung)",
      },
    ],
  },
  {
    category: "stability",
    title: "Pemblokiran Akun Otomatis (Auto-Ban)",
    description: "Lindungi rotasi dari akun yang sudah tidak valid atau diblokir.",
    fields: [
      {
        key: "auto_ban_enabled",
        label: "Aktifkan Auto-Ban Otomatis",
        type: "bool",
        note: "Otomatis menonaktifkan kredensial jika terus-menerus mengembalikan kode error kritis",
      },
      {
        key: "auto_ban_error_codes",
        label: "Daftar Kode Status Error Pemicu Auto-Ban",
        type: "text",
        note: "Format array JSON kode error, contoh: [403, 400]",
      },
    ],
  },
  {
    category: "logs",
    title: "Pencatatan Riwayat & Debugging",
    description: "Pantau penggunaan token, waktu respons, dan payload permintaan untuk audit.",
    fields: [
      {
        key: "usage_log_enabled",
        label: "Aktifkan Pencatatan Riwayat Permintaan (Usage Logs)",
        type: "bool",
        note: "Mencatat timestamp, nama model, jumlah token, dan durasi ke database SQLite",
      },
      {
        key: "request_log_enabled",
        label: "Rekam Rinci Body Permintaan saat Terjadi Error",
        type: "bool",
        note: "Berguna untuk investigasi dan debugging saat terjadi kegagalan pemanggilan API",
      },
      {
        key: "request_log_error_codes",
        label: "Kode Status Error yang Direkam Rinci",
        type: "csv_numbers",
        showIf: (cfg) => !!cfg.request_log_enabled,
        note: "Pisahkan dengan koma kode status HTTP (contoh: 400, 429)",
        placeholder: "400, 429",
      },
    ],
  },
];

export default function Config() {
  const [config, setConfig] = useState({});
  const [envLocked, setEnvLocked] = useState([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState(null);
  const [activeCategory, setActiveCategory] = useState("all");
  const [searchQuery, setSearchQuery] = useState("");
  const [showPasswords, setShowPasswords] = useState({});
  const [copiedKey, setCopiedKey] = useState(null);

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
      setMessage({
        type: "error",
        text: err.response?.data?.detail || "Gagal memuat konfigurasi server",
      });
    } finally {
      setLoading(false);
    }
  };

  const saveConfig = async () => {
    setSaving(true);
    try {
      const res = await api.post("/config/save", { config });
      setMessage({
        type: "success",
        text: res.data.message || "Pengaturan berhasil diperbarui dan disimpan",
      });
      await loadConfig({ silent: true });
    } catch (err) {
      setMessage({
        type: "error",
        text: err.response?.data?.detail || "Gagal menyimpan perubahan pengaturan",
      });
    } finally {
      setSaving(false);
    }
  };

  const setField = (key, value) => {
    setConfig((prev) => ({ ...prev, [key]: value }));
  };

  const togglePasswordVisibility = (key) => {
    setShowPasswords((prev) => ({ ...prev, [key]: !prev[key] }));
  };

  const copyValue = (text, key) => {
    navigator.clipboard.writeText(String(text || ""));
    setCopiedKey(key);
    setTimeout(() => setCopiedKey(null), 2000);
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

  // Filter kelompok berdasarkan kategori aktif dan pencarian
  const filteredGroups = useMemo(() => {
    let groups = CONFIG_GROUPS;
    if (activeCategory !== "all") {
      groups = groups.filter((g) => g.category === activeCategory);
    }
    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase();
      groups = groups
        .map((g) => {
          const matchedFields = g.fields.filter(
            (f) =>
              f.label.toLowerCase().includes(q) ||
              f.key.toLowerCase().includes(q) ||
              (f.note && f.note.toLowerCase().includes(q))
          );
          if (
            g.title.toLowerCase().includes(q) ||
            g.description?.toLowerCase().includes(q) ||
            matchedFields.length > 0
          ) {
            return { ...g, fields: matchedFields.length > 0 ? matchedFields : g.fields };
          }
          return null;
        })
        .filter(Boolean);
    }
    return groups;
  }, [activeCategory, searchQuery]);

  const renderField = (field) => {
    const isLocked = envLocked.includes(field.key);
    const value = config[field.key] ?? "";

    if (isLocked) {
      return (
        <div className="flex items-center gap-2 text-xs text-amber-400 bg-amber-500/10 border border-amber-500/20 rounded-xl px-3.5 py-2.5">
          <Lock size={14} className="shrink-0" />
          <span>Nilai ini dikunci melalui variabel lingkungan (.env / OS).</span>
        </div>
      );
    }

    if (field.type === "bool") {
      return (
        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={() => setField(field.key, !value)}
            className={`relative w-12 h-6 rounded-full transition-colors focus:outline-none ${
              value ? "bg-purple-600 shadow-sm shadow-purple-600/50" : "bg-dark-700"
            }`}
          >
            <span
              className={`absolute top-0.5 left-0.5 w-5 h-5 bg-white rounded-full transition-transform shadow-md ${
                value ? "translate-x-6" : ""
              }`}
            />
          </button>
          <span
            className={`text-xs font-semibold px-2.5 py-1 rounded-full border ${
              value
                ? "bg-purple-500/15 text-purple-300 border-purple-500/30"
                : "bg-dark-800 text-gray-500 border-dark-600"
            }`}
          >
            {value ? "Aktif" : "Nonaktif"}
          </span>
        </div>
      );
    }

    if (field.type === "password_toggle") {
      const isVisible = !!showPasswords[field.key];
      return (
        <div className="flex items-center gap-2 max-w-lg">
          <div className="relative flex-1">
            <input
              type={isVisible ? "text" : "password"}
              value={value}
              onChange={(e) => setField(field.key, e.target.value)}
              className="w-full px-3.5 py-2.5 bg-dark-900 border border-dark-600 rounded-xl text-sm font-mono text-purple-300 focus:outline-none focus:border-purple-500 pr-10"
            />
            <button
              type="button"
              onClick={() => togglePasswordVisibility(field.key)}
              className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-white"
            >
              {isVisible ? <EyeOff size={15} /> : <Eye size={15} />}
            </button>
          </div>
          <button
            type="button"
            onClick={() => copyValue(value, field.key)}
            className="btn btn-secondary px-3 py-2.5 text-xs shrink-0"
            title="Salin nilai"
          >
            {copiedKey === field.key ? <Check size={14} className="text-emerald-400" /> : <Copy size={14} />}
          </button>
        </div>
      );
    }

    if (field.type === "select") {
      const current = field.options.find((o) => o.value === value) || field.options[0];
      return (
        <div className="space-y-2.5 max-w-xl">
          <Select
            value={current?.value ?? ""}
            onChange={(v) => setField(field.key, v)}
            options={field.options}
            className="w-full"
          />
          {field.descriptions && current && (
            <div className="bg-dark-900/90 border border-purple-500/20 rounded-xl p-3.5 text-xs text-purple-200 leading-relaxed shadow-sm">
              <span className="font-semibold text-purple-300 mr-1.5">Penjelasan:</span>
              {field.descriptions[current.value]}
            </div>
          )}
        </div>
      );
    }

    if (field.type === "csv_numbers") {
      return (
        <div className="max-w-lg">
          <CsvNumbersField
            value={value}
            onChange={(v) => setField(field.key, v)}
            placeholder={field.placeholder}
          />
        </div>
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
        <div className="space-y-3">
          {rules.length === 0 && (
            <div className="text-xs text-gray-500 bg-dark-900 border border-dark-700 rounded-xl px-4 py-3">
              Belum ada aturan pemetaan. Klik tombol di bawah untuk menambah pemetaan nama model kustom.
            </div>
          )}
          {rules.map((rule, idx) => (
            <div key={idx} className="flex items-center gap-2">
              <input
                type="text"
                value={rule[0]}
                onChange={(e) => updateRule(idx, 0, e.target.value)}
                placeholder="Pola Regex Klien (cth: ^gpt-4o$)"
                className="flex-1 min-w-0 px-3.5 py-2 bg-dark-900 border border-dark-600 rounded-xl text-xs text-white placeholder-gray-500 font-mono"
              />
              <span className="text-purple-400 text-sm shrink-0 font-bold">→</span>
              <input
                type="text"
                value={rule[1]}
                onChange={(e) => updateRule(idx, 1, e.target.value)}
                placeholder="Model Target (cth: gemini-3.8-flash-high)"
                className="flex-1 min-w-0 px-3.5 py-2 bg-dark-900 border border-dark-600 rounded-xl text-xs text-white placeholder-gray-500 font-mono"
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
            className="btn btn-secondary text-xs px-3.5 py-2 flex items-center gap-1.5"
          >
            <Plus size={14} />
            Tambah Aturan Pemetaan
          </button>
        </div>
      );
    }

    if (field.type === "textarea") {
      return (
        <LinesField
          value={value}
          onChange={(v) => setField(field.key, v)}
          placeholder={field.placeholder}
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
        className="w-full max-w-lg px-3.5 py-2.5 bg-dark-900 border border-dark-600 rounded-xl text-sm text-white placeholder-gray-500 focus:outline-none focus:border-purple-500 transition-colors"
      />
    );
  };

  return (
    <div className="space-y-6">
      {/* Header Sticky Action Bar */}
      <div className="sticky top-[73px] z-20 bg-dark-900/95 backdrop-blur-md border border-dark-700/80 rounded-2xl p-4 shadow-xl">
        <div className="flex flex-col sm:flex-row items-center justify-between gap-3">
          <div className="flex items-center gap-2.5 w-full sm:w-auto">
            <div className="p-2 rounded-xl bg-purple-600/20 text-purple-400 border border-purple-500/30">
              <Sliders size={18} />
            </div>
            <div>
              <h2 className="text-base font-bold text-white tracking-tight">Pengaturan Gateway</h2>
              <p className="text-xs text-gray-400">Konfigurasi jaringan, keamanan, rotasi akun, dan perilaku model</p>
            </div>
          </div>

          <div className="flex items-center gap-2 w-full sm:w-auto justify-end">
            <button
              onClick={() => loadConfig()}
              disabled={loading || saving}
              className="btn btn-secondary text-xs sm:text-sm px-3.5 py-2 flex items-center gap-1.5"
            >
              <RefreshCw size={14} className={loading ? "animate-spin" : ""} />
              Segarkan
            </button>
            <button
              onClick={saveConfig}
              disabled={saving || loading}
              className="btn btn-primary text-xs sm:text-sm px-4 py-2 flex items-center gap-1.5 shadow-lg shadow-purple-600/20"
            >
              {saving ? <Loader2 size={15} className="animate-spin" /> : <Save size={15} />}
              {saving ? "Menyimpan..." : "Simpan Perubahan"}
            </button>
          </div>
        </div>

        {/* Baris Kategori & Pencarian */}
        <div className="flex flex-col md:flex-row items-center justify-between gap-3 mt-4 pt-3 border-t border-dark-700/60">
          <div className="flex items-center gap-1.5 overflow-x-auto w-full md:w-auto pb-1">
            {CATEGORIES.map((cat) => {
              const Icon = cat.icon;
              const isActive = activeCategory === cat.id;
              return (
                <button
                  key={cat.id}
                  onClick={() => setActiveCategory(cat.id)}
                  className={`px-3 py-1.5 rounded-lg text-xs font-medium flex items-center gap-1.5 whitespace-nowrap transition-all ${
                    isActive
                      ? "bg-purple-600 text-white shadow-sm"
                      : "bg-dark-800 text-gray-400 hover:text-white hover:bg-dark-700"
                  }`}
                >
                  <Icon size={13} />
                  {cat.label}
                </button>
              );
            })}
          </div>

          <div className="relative w-full md:w-64">
            <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-500" />
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Cari pengaturan..."
              className="w-full pl-8 pr-3 py-1.5 bg-dark-800 border border-dark-600 rounded-lg text-xs text-white placeholder-gray-500 focus:outline-none focus:border-purple-500"
            />
          </div>
        </div>
      </div>

      {/* Modal Notifikasi */}
      {message && (
        <Modal
          type={message.type}
          title={message.type === "success" ? "Berhasil Disimpan" : "Gagal Memperbarui"}
          onClose={() => setMessage(null)}
        >
          <span className="whitespace-pre-wrap break-all text-sm">{message.text}</span>
        </Modal>
      )}

      {loading ? (
        <div className="flex flex-col items-center justify-center py-20 text-gray-400 gap-3">
          <Loader2 className="animate-spin text-purple-500" size={32} />
          <p className="text-sm">Memuat pengaturan dari database...</p>
        </div>
      ) : (
        <div className="space-y-6">
          {filteredGroups.length === 0 ? (
            <div className="card text-center py-12 text-gray-400 space-y-2">
              <Filter size={28} className="mx-auto text-gray-600" />
              <p className="text-sm">Tidak ada pengaturan yang cocok dengan kata kunci "{searchQuery}".</p>
              <button
                onClick={() => {
                  setSearchQuery("");
                  setActiveCategory("all");
                }}
                className="text-xs text-purple-400 hover:underline pt-1"
              >
                Reset Filter Pencarian
              </button>
            </div>
          ) : (
            filteredGroups.map((group) => (
              <div key={group.title} className="card p-6 space-y-5">
                <div className="flex flex-col sm:flex-row sm:items-center justify-between pb-4 border-b border-dark-700 gap-2">
                  <div>
                    <h3 className="text-base font-bold text-white tracking-tight">{group.title}</h3>
                    {group.description && (
                      <p className="text-xs text-gray-400 mt-0.5">{group.description}</p>
                    )}
                  </div>

                  {group.hasRestoreButton && (
                    <button
                      type="button"
                      onClick={restoreOfficialUrls}
                      className="btn btn-secondary text-xs px-3 py-1.5 flex items-center gap-1.5 self-start"
                    >
                      <RefreshCw size={12} />
                      Kembalikan Endpoint Resmi
                    </button>
                  )}
                </div>

                <div className="space-y-5">
                  {group.fields
                    .filter((field) => !field.showIf || field.showIf(config))
                    .map((field) => (
                      <div key={field.key} className="space-y-1.5">
                        <label className="block text-xs font-semibold uppercase tracking-wider text-gray-300">
                          {field.label}
                        </label>
                        {renderField(field)}
                        {field.note && (
                          <p className="text-[11px] text-gray-500 leading-normal">{field.note}</p>
                        )}
                      </div>
                    ))}
                </div>
              </div>
            ))
          )}
        </div>
      )}
    </div>
  );
}
