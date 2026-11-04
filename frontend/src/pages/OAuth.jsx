import { Check, ChevronDown, Copy, ExternalLink, Loader2, Rocket } from "lucide-react";
import { useState } from "react";
import Modal from "../components/Modal";
import api from "../api";

export default function OAuth() {
  const [loading, setLoading] = useState(false);
  const [fetching, setFetching] = useState(false);
  const [authUrl, setAuthUrl] = useState("");
  const [callbackUrl, setCallbackUrl] = useState("");
  const [showCallbackInput, setShowCallbackInput] = useState(false);
  const [credsContent, setCredsContent] = useState("");
  const [message, setMessage] = useState(null);
  const [copied, setCopied] = useState(false);

  const startAuth = async () => {
    setLoading(true);
    setMessage(null);
    setAuthUrl("");
    setCredsContent("");

    try {
      const res = await api.post("/auth/start", {});
      setAuthUrl(res.data.auth_url);
      setMessage({ type: "info", text: "Tautan autentikasi berhasil dibuat. Buka di jendela baru untuk mengizinkan akun Google." });
    } catch (err) {
      setMessage({
        type: "error",
        text: err.response?.data?.detail || "Gagal membuat tautan autentikasi",
      });
    } finally {
      setLoading(false);
    }
  };

  const fetchCredentials = async () => {
    setFetching(true);
    try {
      const res = await api.post("/auth/callback", {});
      setCredsContent(JSON.stringify(res.data.credentials, null, 2));
      setMessage({
        type: "success",
        text: `Autentikasi berhasil! Kredensial tersimpan: ${res.data.email || "Email tidak diketahui"}`,
      });
    } catch (err) {
      setMessage({
        type: "error",
        text: err.response?.data?.detail || "Gagal mengambil kredensial. Pastikan Anda telah menyelesaikan izin Google.",
      });
    } finally {
      setFetching(false);
    }
  };

  const processCallbackUrl = async () => {
    if (!callbackUrl.trim()) {
      setMessage({ type: "error", text: "Tempelkan URL callback lengkap terlebih dahulu" });
      return;
    }
    setFetching(true);
    try {
      const res = await api.post("/auth/callback-url", {
        callback_url: callbackUrl.trim(),
      });
      setCredsContent(JSON.stringify(res.data.credentials, null, 2));
      setMessage({
        type: "success",
        text: `Autentikasi berhasil! Kredensial tersimpan: ${res.data.email || "Email tidak diketahui"}`,
      });
    } catch (err) {
      setMessage({
        type: "error",
        text: err.response?.data?.detail || "Gagal memproses kredensial dari URL callback",
      });
    } finally {
      setFetching(false);
    }
  };

  const copyUrl = () => {
    navigator.clipboard.writeText(authUrl);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  const downloadCreds = () => {
    const blob = new Blob([credsContent], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "antigravity-credentials.json";
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="space-y-6">
      {/* Kartu Penjelasan */}
      <div className="bg-gradient-to-br from-orange-900/30 to-orange-800/10 border border-orange-700/30 rounded-xl p-5">
        <div className="flex items-center gap-2 mb-2">
          <Rocket className="w-5 h-5 text-orange-400" />
          <h3 className="text-lg font-semibold text-orange-400">Mode Autentikasi Antigravity</h3>
        </div>
        <p className="text-sm text-gray-400">
          Dapatkan kredensial Antigravity melalui Google OAuth resmi. Setelah izin diberikan, sistem akan otomatis
          mendeteksi Project ID dan tier langganan akun Anda, lalu menyimpannya ke database.
        </p>
      </div>

      {/* Pop-up Pesan */}
      {message && (
        <Modal
          type={message.type}
          title={message.type === "success" ? "Berhasil" : message.type === "error" ? "Gagal" : "Informasi"}
          onClose={() => setMessage(null)}
        >
          <span className="whitespace-pre-wrap break-all">{message.text}</span>
        </Modal>
      )}

      {/* Tombol Buat Tautan */}
      <button
        onClick={startAuth}
        disabled={loading}
        className="btn btn-primary flex items-center gap-2 disabled:opacity-50"
      >
        {loading ? (
          <Loader2 className="animate-spin" size={18} />
        ) : (
          <Rocket size={18} />
        )}
        Buat Tautan Autentikasi Antigravity
      </button>

      {/* Kotak Tautan Autentikasi */}
      {authUrl && (
        <div className="card space-y-4">
          <h3 className="font-semibold">Tautan Autentikasi</h3>
          <div className="bg-dark-800 border border-purple-500/30 rounded-lg p-4 flex items-center justify-between gap-3">
            <a
              href={authUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="text-purple-400 hover:text-purple-300 break-all text-sm flex items-center gap-1"
            >
              Klik di sini untuk login akun Google <ExternalLink size={14} />
            </a>
            <button
              onClick={copyUrl}
              className="btn btn-secondary text-xs px-3 py-1.5 flex items-center gap-1 flex-shrink-0"
            >
              {copied ? <Check size={14} /> : <Copy size={14} />}
              {copied ? "Tersalin" : "Salin"}
            </button>
          </div>

          <div className="bg-blue-500/10 border border-blue-500/30 rounded-lg p-4 text-sm text-gray-400">
            <p className="font-medium text-blue-400 mb-2">Petunjuk Penggunaan</p>
            <ol className="list-decimal list-inside space-y-1">
              <li>Klik tautan di atas dan selesaikan login serta izin di akun Google Anda pada tab baru.</li>
              <li>Jika browser mencoba redirect ke localhost, jangan panik jika halaman menampilkan gagal koneksi.</li>
              <li>Tutup tab Google dan kembali ke halaman ini.</li>
              <li>Klik tombol "Ambil Kredensial" di bawah untuk menyelesaikan.</li>
            </ol>
          </div>

          {/* Shortcut URL Callback */}
          <div className="border border-dark-600 rounded-lg">
            <button
              onClick={() => setShowCallbackInput(!showCallbackInput)}
              className="w-full flex items-center justify-between px-4 py-3 text-sm text-gray-400 hover:text-gray-200"
            >
              <span>🚀 Gagal redirect callback? Gunakan cara cepat (Tempel URL Callback)</span>
              <ChevronDown
                size={16}
                className={`transition-transform ${showCallbackInput ? "rotate-180" : ""}`}
              />
            </button>
            {showCallbackInput && (
              <div className="px-4 pb-4 space-y-3">
                <p className="text-xs text-gray-500">
                  Cocok untuk server VPS, cloud, atau container Docker: Setelah mengizinkan akun Google,
                  salin seluruh URL dari address bar browser (yang berawalan http://localhost:...) lalu tempel di bawah ini.
                </p>
                <textarea
                  value={callbackUrl}
                  onChange={(e) => setCallbackUrl(e.target.value)}
                  placeholder="http://localhost:11451/?state=xxx&code=xxx&scope=xxx..."
                  className="w-full px-3 py-2 bg-dark-800 border border-dark-600 rounded-lg text-sm text-white placeholder-gray-500"
                  rows={3}
                />
                <button
                  onClick={processCallbackUrl}
                  disabled={fetching}
                  className="btn btn-secondary text-sm flex items-center gap-2 disabled:opacity-50"
                >
                  {fetching && <Loader2 className="animate-spin" size={14} />}
                  Ambil Kredensial dari URL Callback
                </button>
              </div>
            )}
          </div>

          {/* Tombol Ambil Kredensial */}
          <button
            onClick={fetchCredentials}
            disabled={fetching}
            className="btn btn-primary flex items-center gap-2 disabled:opacity-50"
          >
            {fetching && <Loader2 className="animate-spin" size={18} />}
            Ambil Kredensial Antigravity
          </button>
        </div>
      )}

      {/* Isi Kredensial */}
      {credsContent && (
        <div className="card space-y-4">
          <h3 className="font-semibold">Detail Kredensial</h3>
          <pre className="bg-dark-800 border border-dark-600 rounded-lg p-4 text-xs text-gray-300 overflow-x-auto max-h-96 overflow-y-auto">
            {credsContent}
          </pre>
          <button onClick={downloadCreds} className="btn btn-secondary text-sm">
            Unduh Berkas Kredensial
          </button>
        </div>
      )}
    </div>
  );
}
