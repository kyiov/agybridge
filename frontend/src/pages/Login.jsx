import { Eye, EyeOff } from "lucide-react";
import { useState } from "react";
import Logo from "../components/Logo";
import api from "../api";

export default function Login({ onSuccess }) {
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError("");
    setLoading(true);

    try {
      const res = await api.post("/auth/login", { password });
      localStorage.setItem("panelToken", res.data.token);
      onSuccess();
    } catch (err) {
      setError(err.response?.data?.detail || "Gagal masuk");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center p-4">
      <div className="w-full max-w-md">
        {/* Logo Minimalis */}
        <div className="text-center mb-8">
          <div className="inline-flex items-center justify-center w-16 h-16 rounded-2xl bg-purple-600/15 border border-purple-500/20 mb-4 shadow-lg shadow-purple-500/10">
            <Logo size={36} />
          </div>
          <h1 className="text-3xl font-bold text-white tracking-tight">AGYBridge</h1>
          <p className="text-gray-400 mt-2 text-sm">Panel Kontrol Proksi API Antigravity</p>
        </div>

        {/* Kartu Login */}
        <div className="card">
          <h2 className="text-xl font-semibold mb-6 text-center">Masuk ke Panel Kontrol</h2>

          {error && (
            <div className="bg-red-500/10 border border-red-500/30 text-red-400 px-4 py-3 rounded-lg mb-4">
              {error}
            </div>
          )}

          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-gray-300 mb-2">
                Kata Sandi
              </label>
              <div className="relative">
                <input
                  type={showPassword ? "text" : "password"}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  className="w-full px-4 py-3 bg-dark-800 border border-dark-600 rounded-lg text-white placeholder-gray-500 pr-12"
                  placeholder="Masukkan kata sandi panel kontrol"
                  required
                />
                <button
                  type="button"
                  onClick={() => setShowPassword(!showPassword)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-300"
                >
                  {showPassword ? <EyeOff size={20} /> : <Eye size={20} />}
                </button>
              </div>
            </div>

            <button
              type="submit"
              disabled={loading}
              className="w-full btn btn-primary py-3 flex items-center justify-center disabled:opacity-50"
            >
              {loading ? (
                <span className="animate-spin rounded-full h-5 w-5 border-b-2 border-white"></span>
              ) : (
                "Masuk"
              )}
            </button>
          </form>
        </div>
      </div>
    </div>
  );
}
