import { CheckCircle, FileJson, Loader2, Trash2, Upload, X } from "lucide-react";
import { useRef, useState } from "react";
import api from "../api";

export default function UploadPage() {
  const [files, setFiles] = useState([]);
  const [uploading, setUploading] = useState(false);
  const [results, setResults] = useState(null);
  const [dragOver, setDragOver] = useState(false);
  const inputRef = useRef(null);

  const addFiles = (fileList) => {
    const valid = Array.from(fileList).filter(
      (f) => f.name.endsWith(".json") || f.name.endsWith(".zip")
    );
    setFiles((prev) => {
      const names = new Set(prev.map((f) => f.name));
      return [...prev, ...valid.filter((f) => !names.has(f.name))];
    });
    setResults(null);
  };

  const removeFile = (name) => {
    setFiles((prev) => prev.filter((f) => f.name !== name));
  };

  const upload = async () => {
    if (files.length === 0) return;
    setUploading(true);
    setResults(null);

    try {
      const formData = new FormData();
      files.forEach((f) => formData.append("files", f));

      const res = await api.post("/creds/upload", formData, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      setResults(res.data);
    } catch (err) {
      setResults({
        error: err.response?.data?.detail || "Gagal mengunggah berkas",
      });
    } finally {
      setUploading(false);
    }
  };

  const successCount = results?.uploaded_count || 0;
  const totalCount = results?.total_count || 0;

  return (
    <div className="space-y-6">
      <div className="bg-gradient-to-br from-emerald-900/30 to-emerald-800/10 border border-emerald-700/30 rounded-xl p-5">
        <h3 className="text-lg font-semibold text-emerald-400 mb-2">Impor Kredensial Massal</h3>
        <p className="text-sm text-gray-400">
          Mendukung impor berkas kredensial Antigravity (.json atau arsip .zip berisi berkas JSON).
        </p>
        <div className="mt-3 text-xs text-gray-500 bg-dark-800/60 rounded-lg p-3">
          <p className="mb-1 font-medium text-gray-400">Format JSON Baku:</p>
          <pre className="text-emerald-300/80 whitespace-pre-wrap font-mono">{`{
  "refresh_token": "Wajib",
  "email": "Opsional (diambil otomatis jika kosong)",
  "tier": "Opsional (diambil otomatis jika kosong)",
  "project_id": "Opsional (diambil otomatis jika kosong)"
}`}</pre>
          <p className="mt-2">Kredensial dengan refresh_token tidak valid akan gagal; kredensial dengan email sama akan diperbarui otomatis.</p>
        </div>
      </div>

      {/* Area Unggah */}
      <div
        className={`border-2 border-dashed rounded-xl p-10 text-center cursor-pointer transition-colors ${
          dragOver
            ? "border-purple-500 bg-purple-500/10"
            : "border-dark-600 hover:border-dark-500"
        }`}
        onClick={() => inputRef.current?.click()}
        onDragOver={(e) => {
          e.preventDefault();
          setDragOver(true);
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragOver(false);
          addFiles(e.dataTransfer.files);
        }}
      >
        <Upload className="mx-auto text-purple-400 mb-3" size={32} />
        <p className="text-gray-300">Klik untuk memilih berkas atau seret berkas ke sini</p>
        <p className="text-gray-500 text-sm mt-1">Mendukung format .json dan .zip (arsip zip akan diekstrak otomatis)</p>
        <input
          ref={inputRef}
          type="file"
          multiple
          accept=".json,.zip"
          className="hidden"
          onChange={(e) => {
            addFiles(e.target.files);
            e.target.value = "";
          }}
        />
      </div>

      {/* Daftar Berkas */}
      {files.length > 0 && (
        <div className="card space-y-3">
          <div className="flex items-center justify-between">
            <h4 className="text-sm font-medium text-gray-300">
              {files.length} berkas dipilih
            </h4>
            <div className="flex gap-2">
              <button
                onClick={upload}
                disabled={uploading}
                className="btn btn-primary text-sm flex items-center gap-1.5 disabled:opacity-50"
              >
                {uploading ? (
                  <Loader2 size={14} className="animate-spin" />
                ) : (
                  <Upload size={14} />
                )}
                {uploading ? "Mengunggah..." : "Unggah Berkas"}
              </button>
              <button
                onClick={() => setFiles([])}
                disabled={uploading}
                className="btn btn-secondary text-sm"
              >
                Kosongkan
              </button>
            </div>
          </div>
          <div className="space-y-1.5 max-h-64 overflow-y-auto">
            {files.map((f) => (
              <div
                key={f.name}
                className="flex items-center justify-between bg-dark-800 border border-dark-600 rounded-lg px-3 py-2 text-sm"
              >
                <div className="flex items-center gap-2 text-gray-300 min-w-0">
                  <FileJson size={15} className="text-purple-400 flex-shrink-0" />
                  <span className="truncate">{f.name}</span>
                </div>
                <div className="flex items-center gap-3 flex-shrink-0">
                  <span className="text-gray-500 text-xs">
                    {(f.size / 1024).toFixed(1)} KB
                  </span>
                  <button
                    onClick={() => removeFile(f.name)}
                    className="text-gray-500 hover:text-red-400"
                  >
                    <X size={14} />
                  </button>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Hasil Unggah */}
      {results && (
        <div className="card space-y-3">
          {results.error ? (
            <div className="bg-red-500/10 border border-red-500/30 text-red-400 px-4 py-3 rounded-lg">
              {results.error}
            </div>
          ) : (
            <>
              <div className="bg-green-500/10 border border-green-500/30 text-green-400 px-4 py-3 rounded-lg flex items-center gap-2">
                <CheckCircle size={16} />
                {results.message ||
                  `Selesai: Berhasil mengunggah ${successCount}/${totalCount} berkas`}
              </div>
              {results.results?.some((r) => r.status === "error") && (
                <div className="space-y-1.5">
                  <div className="text-sm text-gray-400">Rincian Gagal:</div>
                  {results.results
                    .filter((r) => r.status === "error")
                    .map((r, i) => (
                      <div
                        key={i}
                        className="bg-red-500/10 border border-red-500/20 text-red-400 text-xs px-3 py-2 rounded-lg"
                      >
                        <span className="font-medium">{r.filename}</span>: {r.message}
                      </div>
                    ))}
                </div>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}
