import {
  AlertCircle,
  ArrowRight,
  Check,
  CheckCircle2,
  ChevronDown,
  Copy,
  ExternalLink,
  KeyRound,
  Laptop,
  Loader2,
  Plus,
  RefreshCw,
  Rocket,
  ShieldCheck,
  Sparkles,
  Terminal,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
import Modal from "../components/Modal";
import api from "../api";

export default function OAuth({ onNavigateTab }) {
  const [status, setStatus] = useState("idle"); // 'idle' | 'authenticating' | 'success' | 'error'
  const [authUrl, setAuthUrl] = useState("");
  const [callbackUrl, setCallbackUrl] = useState("");
  const [showRemoteHelper, setShowRemoteHelper] = useState(false);
  const [successData, setSuccessData] = useState(null);
  const [errorMessage, setErrorMessage] = useState("");
  const [copiedUrl, setCopiedUrl] = useState(false);
  const [currentStep, setCurrentStep] = useState(1); // 1: init, 2: wait google, 3: storing

  const popupRef = useRef(null);
  const pollIntervalRef = useRef(null);

  // Bersihkan listener dan popup saat unmount
  useEffect(() => {
    return () => {
      if (pollIntervalRef.current) clearInterval(pollIntervalRef.current);
      if (popupRef.current && !popupRef.current.closed) popupRef.current.close();
    };
  }, []);

  // Listener window postMessage dari popup callback backend
  useEffect(() => {
    const handleMessage = async (event) => {
      if (event.data?.type === "AGYBRIDGE_OAUTH_SUCCESS") {
        if (pollIntervalRef.current) clearInterval(pollIntervalRef.current);
        setCurrentStep(3);
        try {
          const res = await api.post("/auth/callback", {});
          if (res.data) {
            handleAuthSuccess(res.data);
          }
        } catch (err) {
          console.error("Gagal finalisasi callback setelah postMessage:", err);
        }
      }
    };

    window.addEventListener("message", handleMessage);
    return () => window.removeEventListener("message", handleMessage);
  }, []);

  const handleAuthSuccess = (data) => {
    if (pollIntervalRef.current) clearInterval(pollIntervalRef.current);
    if (popupRef.current && !popupRef.current.closed) {
      popupRef.current.close();
    }
    setSuccessData(data);
    setStatus("success");
    setCurrentStep(3);
  };

  const startOneClickAuth = async () => {
    setStatus("authenticating");
    setErrorMessage("");
    setSuccessData(null);
    setCurrentStep(1);

    try {
      const res = await api.post("/auth/start", {});
      const url = res.data.auth_url;
      setAuthUrl(url);
      setCurrentStep(2);

      // Buka popup Google OAuth di tengah layar
      const width = 560;
      const height = 720;
      const left = window.screenX + (window.outerWidth - width) / 2;
      const top = window.screenY + (window.outerHeight - height) / 2;

      popupRef.current = window.open(
        url,
        "AGYBridge_Google_OAuth",
        `width=${width},height=${height},left=${left},top=${top},status=no,menubar=no,toolbar=no`
      );

      // Mulai polling backend untuk menunggu autorisasi
      let attempts = 0;
      const maxAttempts = 60; // 60 x 1.5s = 90 detik timeout

      pollIntervalRef.current = setInterval(async () => {
        attempts += 1;
        if (attempts > maxAttempts) {
          clearInterval(pollIntervalRef.current);
          setStatus("error");
          setErrorMessage("Waktu tunggu autentikasi habis (90 detik). Silakan coba lagi.");
          return;
        }

        try {
          // Callback endpoint di backend menunggu proses code jika sedang berlangsung
          const callbackRes = await api.post("/auth/callback", {});
          if (callbackRes.data && callbackRes.data.credentials) {
            clearInterval(pollIntervalRef.current);
            handleAuthSuccess(callbackRes.data);
          }
        } catch (err) {
          // Masih menunggu, abaikan 400 error sementara sampai selesai
          const detail = err.response?.data?.detail || err.response?.data?.error || "";
          if (detail.includes("Alur autentikasi tidak ditemukan")) {
            // Flow mungkin belum diinisialisasi atau sudah kadaluarsa
          }
        }
      }, 1500);
    } catch (err) {
      setStatus("error");
      setErrorMessage(
        err.response?.data?.detail || "Gagal menghubungi server untuk memulai autentikasi Google."
      );
    }
  };

  const processCallbackUrl = async () => {
    if (!callbackUrl.trim()) {
      setErrorMessage("Tempelkan URL callback lengkap terlebih dahulu");
      return;
    }
    setStatus("authenticating");
    setCurrentStep(3);
    setErrorMessage("");

    try {
      const res = await api.post("/auth/callback-url", {
        callback_url: callbackUrl.trim(),
      });
      handleAuthSuccess(res.data);
    } catch (err) {
      setStatus("error");
      setErrorMessage(
        err.response?.data?.detail || "Gagal memproses kredensial dari URL callback yang ditempel."
      );
    }
  };

  const copyUrl = () => {
    if (!authUrl) return;
    navigator.clipboard.writeText(authUrl);
    setCopiedUrl(true);
    setTimeout(() => setCopiedUrl(false), 2000);
  };

  const resetFlow = () => {
    if (pollIntervalRef.current) clearInterval(pollIntervalRef.current);
    if (popupRef.current && !popupRef.current.closed) popupRef.current.close();
    setStatus("idle");
    setAuthUrl("");
    setCallbackUrl("");
    setSuccessData(null);
    setErrorMessage("");
    setCurrentStep(1);
  };

  const downloadBackupCreds = () => {
    if (!successData?.credentials) return;
    const blob = new Blob([JSON.stringify(successData.credentials, null, 2)], {
      type: "application/json",
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `antigravity-${successData.email || "account"}.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="space-y-6">
      {/* Banner Penjelasan Modern */}
      <div className="bg-gradient-to-r from-orange-900/30 via-purple-900/20 to-dark-800 border border-orange-500/30 rounded-2xl p-6 shadow-xl relative overflow-hidden">
        <div className="relative z-10 flex flex-col md:flex-row md:items-center justify-between gap-4">
          <div className="space-y-1">
            <div className="flex items-center gap-2">
              <span className="px-2.5 py-0.5 rounded-full text-xs font-semibold bg-orange-500/20 text-orange-300 border border-orange-500/30 flex items-center gap-1">
                <Rocket size={12} />
                OAuth 2.0 Web Flow
              </span>
              <span className="text-xs text-gray-400">Resmi Google Antigravity</span>
            </div>
            <h2 className="text-2xl font-bold text-white tracking-tight">
              One-Click Google Authentication
            </h2>
            <p className="text-sm text-gray-300 max-w-2xl leading-relaxed">
              Hubungkan akun Google Antigravity Anda hanya dengan 1-klik. Kredensial, refresh token,
              dan Project ID otomatis diverifikasi dan langsung tersimpan ke database proxy.
            </p>
          </div>

          {status !== "idle" && (
            <button
              onClick={resetFlow}
              className="btn btn-secondary text-xs flex items-center gap-1.5 self-start md:self-center"
            >
              <RefreshCw size={14} />
              Mulai Ulang
            </button>
          )}
        </div>
      </div>

      {/* Modal Pesan Error jika terjadi kendala */}
      {errorMessage && (
        <Modal type="error" title="Kendala Autentikasi" onClose={() => setErrorMessage("")}>
          <div className="space-y-3">
            <p className="text-sm text-gray-300 whitespace-pre-wrap">{errorMessage}</p>
            <div className="text-xs text-gray-400 bg-dark-900 p-3 rounded-lg border border-dark-700">
              💡 <strong>Solusi cepat:</strong> Jika browser tidak dapat membuka popup atau redirect gagal di remote VPS, gunakan mode <strong>Remote Callback Helper</strong> di bawah ini.
            </div>
          </div>
        </Modal>
      )}

      {/* TAMPILAN STATUS: 1. IDLE (TOMBOL UTAMA 1-KLIK) */}
      {status === "idle" && (
        <div className="space-y-6">
          <div className="card p-8 text-center space-y-6 bg-gradient-to-b from-dark-800 to-dark-900/90 border-purple-500/30 shadow-2xl">
            <div className="w-16 h-16 rounded-2xl bg-gradient-to-tr from-purple-600 to-indigo-500 flex items-center justify-center mx-auto shadow-lg shadow-purple-600/30">
              <Rocket className="text-white" size={32} />
            </div>

            <div className="max-w-md mx-auto space-y-2">
              <h3 className="text-xl font-bold text-white">Hubungkan Akun Google Anda</h3>
              <p className="text-sm text-gray-400 leading-relaxed">
                Klik tombol di bawah ini. Jendela resmi Google akan terbuka untuk meminta izin akun Antigravity. Setelah Anda setujui, akun langsung aktif tanpa unduh file JSON.
              </p>
            </div>

            <div className="flex flex-col sm:flex-row items-center justify-center gap-3 pt-2">
              <button
                onClick={startOneClickAuth}
                className="w-full sm:w-auto px-8 py-3.5 bg-gradient-to-r from-purple-600 via-indigo-600 to-purple-600 hover:from-purple-500 hover:to-indigo-500 text-white font-semibold rounded-xl shadow-lg shadow-purple-600/30 hover:shadow-purple-600/50 flex items-center justify-center gap-2.5 transition-all text-sm group"
              >
                <Rocket size={18} className="group-hover:scale-110 transition-transform" />
                Login dengan Akun Google (Satu Klik)
              </button>

              <button
                onClick={() => setShowRemoteHelper(!showRemoteHelper)}
                className="w-full sm:w-auto px-5 py-3.5 bg-dark-800 hover:bg-dark-700 border border-dark-600 text-gray-300 font-medium rounded-xl flex items-center justify-center gap-2 text-sm transition-all"
              >
                <Laptop size={16} />
                Mode VPS / Remote
                <ChevronDown
                  size={14}
                  className={`transition-transform ${showRemoteHelper ? "rotate-180" : ""}`}
                />
              </button>
            </div>

            {/* Fitur Highlights */}
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 pt-4 border-t border-dark-700/60 max-w-2xl mx-auto text-left text-xs">
              <div className="flex items-start gap-2.5 p-2 rounded-lg bg-dark-900/50">
                <ShieldCheck size={16} className="text-emerald-400 flex-shrink-0 mt-0.5" />
                <div>
                  <div className="font-semibold text-white">OAuth 2.0 Resmi</div>
                  <div className="text-gray-500">Token langsung dari Google Cloud</div>
                </div>
              </div>

              <div className="flex items-start gap-2.5 p-2 rounded-lg bg-dark-900/50">
                <Sparkles size={16} className="text-purple-400 flex-shrink-0 mt-0.5" />
                <div>
                  <div className="font-semibold text-white">Deteksi Tier Otomatis</div>
                  <div className="text-gray-500">Free, Pro, atau Ultra siap pakai</div>
                </div>
              </div>

              <div className="flex items-start gap-2.5 p-2 rounded-lg bg-dark-900/50">
                <CheckCircle2 size={16} className="text-blue-400 flex-shrink-0 mt-0.5" />
                <div>
                  <div className="font-semibold text-white">Auto Simpan DB</div>
                  <div className="text-gray-500">Tanpa repot upload berkas manual</div>
                </div>
              </div>
            </div>
          </div>

          {/* Remote / VPS Helper Collapsible */}
          {showRemoteHelper && (
            <div className="card p-5 space-y-4 border-dark-600 bg-dark-850">
              <div className="flex items-center gap-2">
                <Laptop size={18} className="text-indigo-400" />
                <h4 className="font-semibold text-white text-sm">
                  Panduan Autentikasi Remote VPS (Jika Browser Laptop Menampilkan Koneksi Gagal)
                </h4>
              </div>

              <p className="text-xs text-gray-400 leading-relaxed">
                Saat Anda mengakses AGYBridge di VPS melalui IP publik, Google akan mencoba mengarahkan callback kembali ke <code>http://localhost:11451</code> di laptop Anda. Salin tautan dari address bar jendela tersebut lalu tempel di bawah ini:
              </p>

              <div className="space-y-3">
                <textarea
                  value={callbackUrl}
                  onChange={(e) => setCallbackUrl(e.target.value)}
                  placeholder="Tempelkan URL callback di sini (misal: http://localhost:11451/?state=xxx&code=xxx...)"
                  className="w-full px-3.5 py-2.5 bg-dark-900 border border-dark-600 rounded-xl text-xs text-white placeholder-gray-500 font-mono focus:outline-none focus:border-purple-500"
                  rows={3}
                />

                <button
                  onClick={processCallbackUrl}
                  className="btn btn-primary text-xs flex items-center gap-2"
                >
                  <Rocket size={14} />
                  Proses &amp; Simpan dari URL Callback
                </button>
              </div>
            </div>
          )}
        </div>
      )}

      {/* TAMPILAN STATUS: 2. AUTHENTICATING (PROGRESS ANIMASI) */}
      {status === "authenticating" && (
        <div className="card p-8 space-y-6 text-center max-w-xl mx-auto border-purple-500/40 shadow-2xl">
          <div className="relative w-16 h-16 mx-auto">
            <div className="absolute inset-0 rounded-full border-4 border-purple-500/20 animate-pulse"></div>
            <div className="w-16 h-16 rounded-full border-4 border-purple-500 border-t-transparent animate-spin flex items-center justify-center"></div>
          </div>

          <div className="space-y-2">
            <h3 className="text-lg font-bold text-white">Menghubungkan ke Akun Google...</h3>
            <p className="text-xs text-gray-400 max-w-md mx-auto">
              Silakan selesaikan proses login dan persetujuan akun di jendela popup yang telah terbuka.
            </p>
          </div>

          {/* Stepper Indikator */}
          <div className="space-y-3 max-w-sm mx-auto text-left text-xs">
            <div className="flex items-center gap-3 p-2.5 rounded-lg bg-dark-900 border border-dark-700">
              <span className="w-5 h-5 rounded-full bg-emerald-500/20 text-emerald-400 flex items-center justify-center font-bold text-[11px]">
                ✓
              </span>
              <span className="text-gray-300">1. Inisialisasi Tautan Google OAuth</span>
            </div>

            <div className="flex items-center gap-3 p-2.5 rounded-lg bg-purple-900/30 border border-purple-500/40">
              <Loader2 size={16} className="animate-spin text-purple-400" />
              <span className="text-purple-200 font-medium">
                2. Menunggu Persetujuan di Jendela Google...
              </span>
            </div>

            <div className="flex items-center gap-3 p-2.5 rounded-lg bg-dark-900/60 border border-dark-800 text-gray-500">
              <span className="w-5 h-5 rounded-full bg-dark-800 text-gray-500 flex items-center justify-center font-bold text-[11px]">
                3
              </span>
              <span>3. Simpan Kredensial &amp; Konfigurasi Akun</span>
            </div>
          </div>

          {/* Opsi Tautan Terbuka Manual */}
          {authUrl && (
            <div className="pt-4 border-t border-dark-700 space-y-3">
              <div className="text-xs text-gray-400">
                Jendela popup tidak muncul atau terblokir browser?
              </div>
              <div className="flex items-center justify-center gap-2">
                <a
                  href={authUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="btn btn-secondary text-xs flex items-center gap-1.5"
                >
                  <ExternalLink size={13} />
                  Buka di Tab Baru
                </a>
                <button
                  onClick={copyUrl}
                  className="btn btn-secondary text-xs flex items-center gap-1.5"
                >
                  {copiedUrl ? <Check size={13} className="text-emerald-400" /> : <Copy size={13} />}
                  {copiedUrl ? "Tersalin!" : "Salin Tautan"}
                </button>
              </div>
            </div>
          )}

          {/* Remote URL fallback during wait */}
          <div className="pt-2 text-center">
            <button
              onClick={() => setShowRemoteHelper(!showRemoteHelper)}
              className="text-xs text-purple-400 hover:text-purple-300 underline"
            >
              Menggunakan Remote VPS &amp; popup gagal redirect? Klik di sini untuk tempel callback URL
            </button>
          </div>

          {showRemoteHelper && (
            <div className="pt-2 text-left space-y-2">
              <textarea
                value={callbackUrl}
                onChange={(e) => setCallbackUrl(e.target.value)}
                placeholder="Tempelkan URL callback di sini (http://localhost:11451/?state=xxx&code=xxx...)"
                className="w-full px-3 py-2 bg-dark-900 border border-dark-600 rounded-lg text-xs text-white placeholder-gray-500 font-mono"
                rows={2}
              />
              <button
                onClick={processCallbackUrl}
                className="btn btn-primary text-xs w-full py-2 flex items-center justify-center gap-1.5"
              >
                <Rocket size={13} />
                Selesaikan dengan Callback URL
              </button>
            </div>
          )}
        </div>
      )}

      {/* TAMPILAN STATUS: 3. SUCCESS (KARTU SUKSES & TINDAKAN SELANJUTNYA) */}
      {status === "success" && (
        <div className="card p-8 space-y-6 max-w-xl mx-auto border-emerald-500/40 bg-gradient-to-b from-dark-800 to-dark-900 shadow-2xl">
          <div className="w-16 h-16 rounded-2xl bg-emerald-500/20 border border-emerald-500/30 flex items-center justify-center mx-auto text-emerald-400 shadow-lg shadow-emerald-500/20">
            <CheckCircle2 size={36} />
          </div>

          <div className="text-center space-y-1">
            <h3 className="text-xl font-bold text-white">Akun Google Berhasil Terhubung!</h3>
            <p className="text-xs text-gray-400">
              Kredensial dan refresh token telah disimpan dengan aman ke database AGYBridge.
            </p>
          </div>

          {/* Rincian Akun */}
          <div className="bg-dark-900 border border-dark-700 rounded-xl p-4 space-y-2.5 text-xs">
            <div className="flex items-center justify-between">
              <span className="text-gray-500">Email Akun:</span>
              <span className="font-semibold text-white font-mono">{successData?.email || "-"}</span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-gray-500">Langganan / Tier:</span>
              <span className="px-2 py-0.5 rounded-full font-bold uppercase text-[10px] bg-purple-500/20 text-purple-300 border border-purple-500/30">
                {successData?.tier || "Free"}
              </span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-gray-500">Status Rotasi:</span>
              <span className="text-emerald-400 font-medium flex items-center gap-1">
                <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse"></span>
                Aktif &amp; Siap Melayani Permintaan
              </span>
            </div>
          </div>

          {/* Tombol Aksi Lanjutan */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 pt-2">
            <button
              onClick={() => onNavigateTab && onNavigateTab("credentials")}
              className="btn btn-primary py-2.5 text-xs flex items-center justify-center gap-2"
            >
              <KeyRound size={15} />
              Buka Daftar Kredensial
            </button>

            <button
              onClick={() => onNavigateTab && onNavigateTab("presets")}
              className="btn btn-secondary py-2.5 text-xs flex items-center justify-center gap-2"
            >
              <Terminal size={15} />
              Setup di Coding Agent
            </button>
          </div>

          <div className="flex items-center justify-between pt-3 border-t border-dark-700 text-xs">
            <button
              onClick={startOneClickAuth}
              className="text-purple-400 hover:text-purple-300 flex items-center gap-1"
            >
              <Plus size={14} />
              + Hubungkan Akun Lain
            </button>

            <button
              onClick={downloadBackupCreds}
              className="text-gray-400 hover:text-white flex items-center gap-1"
            >
              Unduh Berkas Backup JSON
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
