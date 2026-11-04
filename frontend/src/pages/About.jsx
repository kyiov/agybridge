import { ExternalLink, Github, Info, RefreshCw, Zap } from "lucide-react";
import Logo from "../components/Logo";
import { getBasePath } from "../basePath.js";

export default function About({ version, onCheckUpdate, checkingUpdate }) {
  const apiBase = `${window.location.origin}${getBasePath()}`;
  const apiEndpoints = [
    { label: "Format OpenAI", value: `${apiBase}v1/chat/completions` },
    { label: "Format Gemini", value: `${apiBase}v1beta/models` },
    { label: "Format Claude", value: `${apiBase}v1/messages` },
  ];

  const copyText = (text) => {
    navigator.clipboard.writeText(text);
  };

  return (
    <div className="space-y-6">
      {/* Endpoint API */}
      <div className="card p-4 sm:p-6">
        <h3 className="text-sm font-medium text-gray-400 mb-3 flex items-center gap-2">
          <Zap size={16} className="text-amber-400" />
          Endpoint API (Klik tautan untuk menyalin)
        </h3>
        <div className="space-y-2">
          {apiEndpoints.map((ep) => (
            <div key={ep.label} className="flex flex-col sm:flex-row sm:items-center gap-1 sm:gap-3 text-sm">
              <span className="text-gray-500 sm:w-28 flex-shrink-0">{ep.label}</span>
              <code
                className="bg-dark-800 border border-dark-600 rounded px-2 py-1 text-xs text-gray-300 cursor-pointer hover:text-white break-all"
                onClick={() => copyText(ep.value)}
              >
                {ep.value}
              </code>
            </div>
          ))}
        </div>
      </div>

      {/* Ringkasan Proyek */}
      <div className="card">
        <div className="flex items-center gap-3 mb-4">
          <div className="inline-flex items-center justify-center w-12 h-12 rounded-2xl bg-purple-600/15 border border-purple-500/20 shadow-md">
            <Logo size={30} />
          </div>
          <div>
            <h2 className="text-2xl font-bold text-white tracking-tight">AGYBridge</h2>
            <p className="text-gray-400 text-sm">
              {version?.version ? `Versi: ${version.version}` : "Layanan Proksi Gateway API"}
            </p>
          </div>
        </div>
        <p className="text-gray-400 text-sm leading-relaxed">
          Gateway proksi berkinerja tinggi untuk menjembatani Google Antigravity ke antarmuka standar OpenAI,
          Gemini, dan Anthropic Claude. Dilengkapi sistem manajemen multi-akun, rotasi beban otomatis,
          pencegahan batas laju (rate-limit cooldown), dan pemantauan penggunaan kuota secara real-time.
        </p>
        <div className="flex flex-wrap items-center gap-4 mt-4">
          <button
            onClick={onCheckUpdate}
            disabled={checkingUpdate}
            className="text-blue-400 hover:text-blue-300 text-sm flex items-center gap-1.5 disabled:opacity-50"
          >
            {checkingUpdate ? (
              <Info size={14} className="animate-pulse" />
            ) : (
              <RefreshCw size={14} />
            )}
            {checkingUpdate ? "Memeriksa..." : "Periksa Pembaruan"}
          </button>
          {version?.check_update && version?.has_update && (
            <span className="text-emerald-400 text-sm flex items-center gap-1.5">
              <Info size={14} />
              Versi baru tersedia: {version.latest_version}
            </span>
          )}
          {version?.check_update && version?.has_update === false && (
            <span className="text-gray-400 text-sm flex items-center gap-1.5">
              <Info size={14} />
              Sistem menggunakan versi terbaru
            </span>
          )}
        </div>
      </div>

      {/* Fitur Utama */}
      <div className="card">
        <h3 className="text-lg font-semibold text-blue-400 mb-4">✨ Fitur Unggulan</h3>
        <div className="grid md:grid-cols-2 gap-4 text-sm">
          <div className="space-y-3">
            <div className="text-gray-300">
              <span className="text-amber-400">⚡</span>{" "}
              <strong>Kompatibilitas Multi-Format:</strong> Mendukung format OpenAI, Gemini, dan Claude.
            </div>
            <div className="text-gray-300">
              <span className="text-cyan-400">🔄</span>{" "}
              <strong>Rotasi Cerdas:</strong> Penyeimbangan beban otomatis dengan isolasi akun yang terkena limit.
            </div>
            <div className="text-gray-300">
              <span className="text-emerald-400">🛡️</span>{" "}
              <strong>Proteksi Otomatis:</strong> Mendeteksi error kritis dan menonaktifkan kredensial bermasalah.
            </div>
            <div className="text-gray-300">
              <span className="text-purple-400">❄️</span>{" "}
              <strong>Cooldown Tingkat Model:</strong> Menangani error 429 secara independen per keluarga model.
            </div>
          </div>
          <div className="space-y-3">
            <div className="text-gray-300">
              <span className="text-red-400">✂️</span>{" "}
              <strong>Anti-Pemotongan Respons:</strong> Mencegah teks terpotong di tengah jalan pada respon panjang.
            </div>
            <div className="text-gray-300">
              <span className="text-emerald-400">📊</span>{" "}
              <strong>Log & Metrik Real-time:</strong> Pelacakan token, latensi, dan histori panggilan API lengkap.
            </div>
            <div className="text-gray-300">
              <span className="text-gray-400">📱</span>{" "}
              <strong>Desain Responsif:</strong> Tampilan optimal di perangkat desktop maupun seluler.
            </div>
          </div>
        </div>
      </div>

      {/* Informasi Sistem */}
      {version && (
        <div className="card">
          <h3 className="text-base font-semibold text-gray-300 mb-3">Informasi Sistem</h3>
          <div className="grid grid-cols-2 gap-3 text-sm">
            <div className="text-gray-500">
              Versi Saat Ini: <span className="text-gray-300">{version.version || "-"}</span>
            </div>
            <div className="text-gray-500">
              Commit Hash: <span className="text-gray-300">{version.full_hash || "-"}</span>
            </div>
            <div className="text-gray-500">
              Status Build: <span className="text-gray-300">{version.message || "-"}</span>
            </div>
            <div className="text-gray-500">
              Tanggal Rilis: <span className="text-gray-300">{version.date || "-"}</span>
            </div>
          </div>
        </div>
      )}

      {/* Pengakuan & Atribusi */}
      <div className="card text-xs text-gray-500 space-y-1.5 border-dark-600/60">
        <div className="text-gray-400 font-medium">Atribusi & Pengakuan:</div>
        <p className="leading-relaxed">
          AGYBridge merupakan fork independen yang dimodernisasi dari proyek upstream{" "}
          <a
            href="https://github.com/su-kaka/agy2api"
            target="_blank"
            rel="noopener noreferrer"
            className="text-blue-400 hover:text-blue-300 inline-flex items-center gap-0.5"
          >
            agy2api <ExternalLink size={11} />
          </a>{" "}
          karya su-kaka. Dikembangkan mandiri dengan pembersihan total kode, antarmuka baru berstandar Inter & JetBrains Mono, serta lisensi terbuka MIT © 2026.
        </p>
      </div>
    </div>
  );
}
