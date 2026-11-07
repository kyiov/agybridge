import {
  AlertCircle,
  ArrowRight,
  Check,
  Code2,
  Copy,
  Cpu,
  Download,
  ExternalLink,
  Eye,
  EyeOff,
  Globe,
  Laptop,
  Layers,
  Loader2,
  RefreshCw,
  Sparkles,
  Terminal,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import api from "../api";

export default function Presets() {
  const [loading, setLoading] = useState(true);
  const [configData, setConfigData] = useState({
    api_password: "",
    port: 7861,
    host: "0.0.0.0",
    default_local_base_url: "http://127.0.0.1:7861/",
    models: [],
  });

  const [activeAgent, setActiveAgent] = useState("cursor");
  const [urlMode, setUrlMode] = useState("local"); // 'local' | 'origin' | 'custom'
  const [customUrl, setCustomUrl] = useState("");
  const [selectedModel, setSelectedModel] = useState("gemini-3.8-flash-high");
  const [showPassword, setShowPassword] = useState(false);
  const [enableCaveman, setEnableCaveman] = useState(false);
  const [copiedKey, setCopiedKey] = useState(null);

  const fetchPresetsConfig = async () => {
    setLoading(true);
    try {
      const res = await api.get("/config/presets");
      setConfigData(res.data);
      if (res.data.models && res.data.models.length > 0) {
        setSelectedModel(res.data.models[0].id);
      }
    } catch (err) {
      console.error("Gagal memuat preset konfigurasi:", err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchPresetsConfig();
  }, []);

  const apiKey = configData.api_password || "sk-";

  // Calculate Base URL
  const baseUrl = useMemo(() => {
    let raw = "";
    if (urlMode === "local") {
      raw = configData.default_local_base_url || `http://127.0.0.1:${configData.port || 7861}/`;
    } else if (urlMode === "origin") {
      raw = `${window.location.protocol}//${window.location.host}/`;
    } else {
      raw = customUrl.trim() || `http://127.0.0.1:${configData.port || 7861}/`;
    }
    return raw.endsWith("/") ? raw : `${raw}/`;
  }, [urlMode, customUrl, configData]);

  const v1Url = `${baseUrl}v1`;

  const copyToClipboard = (text, key) => {
    navigator.clipboard.writeText(text);
    setCopiedKey(key);
    setTimeout(() => setCopiedKey(null), 2000);
  };

  const downloadFile = (filename, content, mime = "text/plain") => {
    const blob = new Blob([content], { type: mime });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(url);
  };

  // Agent tabs list
  const agents = [
    { id: "cursor", name: "Cursor", badge: "Populer", icon: Code2 },
    { id: "claude-code", name: "Claude Code", badge: "CLI Pro", icon: Terminal },
    { id: "cline", name: "Cline / Roo Code", badge: "VS Code", icon: Layers },
    { id: "continue", name: "Continue.dev", badge: "Open Source", icon: Cpu },
    { id: "aider-sdk", name: "Aider & SDK", badge: "Multi-Tool", icon: Sparkles },
  ];

  // Templates generation
  const cursorRulesContent = `# Cursor Rules - AGYBridge Integration
# Model: ${selectedModel}
# Endpoint: ${v1Url}

You are an expert AI software engineer connected via AGYBridge.
- Code style: Modern, concise, and clean.
- Always write high-quality code with proper error handling.
${enableCaveman ? "- Mode Caveman: Kompres jawaban, hemat token, langsung beri solusi kode tanpa basa-basi berlebih." : ""}
`;

  const cursorSettingsJson = JSON.stringify(
    {
      "cursor.general.customOpenAIBaseUrl": v1Url,
      "cursor.general.customOpenAIKey": apiKey,
      "cursor.general.defaultModel": selectedModel,
    },
    null,
    2
  );

  const claudeCodeBash = `# Setup Claude Code CLI dengan AGYBridge
export ANTHROPIC_BASE_URL="${v1Url}"
export ANTHROPIC_AUTH_TOKEN="${apiKey}"
export CLAUDE_MODEL="${selectedModel}"

# Jalankan Claude Code di terminal proyek Anda
claude
`;

  const claudeCodePowerShell = `# Setup Claude Code di Windows PowerShell
$env:ANTHROPIC_BASE_URL="${v1Url}"
$env:ANTHROPIC_AUTH_TOKEN="${apiKey}"
$env:CLAUDE_MODEL="${selectedModel}"

# Jalankan Claude Code
claude
`;

  const clineSettingsJson = JSON.stringify(
    {
      "apiProvider": "openai-native",
      "openAiBaseUrl": v1Url,
      "openAiApiKey": apiKey,
      "openAiModelId": selectedModel,
      "customModelId": selectedModel,
    },
    null,
    2
  );

  const continueConfigJson = JSON.stringify(
    {
      "models": [
        {
          "title": `AGYBridge - ${selectedModel}`,
          "provider": "openai",
          "model": selectedModel,
          "apiKey": apiKey,
          "apiBase": v1Url,
        },
        {
          "title": "AGYBridge - Claude Sonnet 4.6",
          "provider": "openai",
          "model": "claude-sonnet-4-6",
          "apiKey": apiKey,
          "apiBase": v1Url,
        },
        {
          "title": "AGYBridge - Gemini 3.8 Flash High",
          "provider": "openai",
          "model": "gemini-3.8-flash-high",
          "apiKey": apiKey,
          "apiBase": v1Url,
        },
      ],
      "tabAutocompleteModel": {
        "title": "AGYBridge Autocomplete",
        "provider": "openai",
        "model": "gemini-3.8-flash-high",
        "apiKey": apiKey,
        "apiBase": v1Url,
      },
    },
    null,
    2
  );

  const aiderCommand = `aider --openai-api-base "${v1Url}" --openai-api-key "${apiKey}" --model "openai/${selectedModel}"`;

  const pythonSdkSnippet = `from openai import OpenAI

# Inisialisasi klien OpenAI yang diarahkan ke AGYBridge
client = OpenAI(
    base_url="${v1Url}",
    api_key="${apiKey}"
)

response = client.chat.completions.create(
    model="${selectedModel}",
    messages=[
        {"role": "system", "content": "Anda adalah asisten AI yang cerdas dan solutif.${enableCaveman ? ' Mode Caveman: berikan jawaban ringkas & padat.' : ''}"},
        {"role": "user", "content": "Halo! Tuliskan contoh fungsi Python untuk parsing JSON."}
    ],
    temperature=0.7
)

print(response.choices[0].message.content)
`;

  const curlSnippet = `curl -X POST "${v1Url}/chat/completions" \\
  -H "Content-Type: application/json" \\
  -H "Authorization: Bearer ${apiKey}" \\
  -d '{
    "model": "${selectedModel}",
    "messages": [
      {"role": "user", "content": "Halo AGYBridge!"}
    ]
  }'`;

  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center py-20 text-gray-400 gap-3">
        <Loader2 className="animate-spin text-purple-500" size={32} />
        <p className="text-sm">Memuat preset konfigurasi agent...</p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Header Banner */}
      <div className="bg-gradient-to-r from-purple-900/40 via-indigo-900/30 to-dark-800 border border-purple-500/30 rounded-2xl p-6 shadow-xl relative overflow-hidden">
        <div className="relative z-10 flex flex-col md:flex-row md:items-center justify-between gap-4">
          <div>
            <div className="flex items-center gap-2 mb-2">
              <span className="px-2.5 py-0.5 rounded-full text-xs font-semibold bg-purple-500/20 text-purple-300 border border-purple-500/30">
                Integrasi 1-Klik
              </span>
              <span className="text-xs text-gray-400">OpenAI Compatible Endpoint</span>
            </div>
            <h2 className="text-2xl font-bold text-white tracking-tight flex items-center gap-2">
              Preset Export Coding Agent
            </h2>
            <p className="text-sm text-gray-300 mt-1 max-w-2xl leading-relaxed">
              Gunakan akun Google Antigravity Anda langsung di Cursor, Claude Code, Cline, Continue.dev,
              dan tool coding lainnya tanpa konfigurasi manual yang rumit.
            </p>
          </div>

          <button
            onClick={fetchPresetsConfig}
            className="btn btn-secondary text-xs self-start md:self-center flex items-center gap-1.5"
          >
            <RefreshCw size={14} />
            Segarkan Kunci
          </button>
        </div>
      </div>

      {/* Kontrol Konfigurasi Global */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {/* Pilihan Host / Base URL */}
        <div className="card p-4 space-y-3">
          <div className="flex items-center justify-between">
            <label className="text-xs font-semibold uppercase tracking-wider text-gray-400 flex items-center gap-1.5">
              <Laptop size={14} className="text-purple-400" />
              Target Base URL
            </label>
            <span className="text-[11px] text-gray-500">{baseUrl}</span>
          </div>

          <div className="grid grid-cols-2 gap-2">
            <button
              onClick={() => setUrlMode("local")}
              className={`px-3 py-2 text-xs font-medium rounded-lg border transition-all text-left ${
                urlMode === "local"
                  ? "bg-purple-600/20 border-purple-500 text-purple-200"
                  : "bg-dark-800 border-dark-600 text-gray-400 hover:text-white"
              }`}
            >
              <div className="font-semibold">Local (127.0.0.1)</div>
              <div className="text-[10px] text-gray-500">Satu PC / VPS lokal</div>
            </button>

            <button
              onClick={() => setUrlMode("origin")}
              className={`px-3 py-2 text-xs font-medium rounded-lg border transition-all text-left ${
                urlMode === "origin"
                  ? "bg-purple-600/20 border-purple-500 text-purple-200"
                  : "bg-dark-800 border-dark-600 text-gray-400 hover:text-white"
              }`}
            >
              <div className="font-semibold">Web Host ({window.location.hostname})</div>
              <div className="text-[10px] text-gray-500">Akses remote / IP publik</div>
            </button>
          </div>

          {urlMode === "custom" && (
            <input
              type="text"
              value={customUrl}
              onChange={(e) => setCustomUrl(e.target.value)}
              placeholder="http://domain-atau-ip:7861/"
              className="w-full px-3 py-1.5 text-xs bg-dark-900 border border-dark-600 rounded-lg text-white"
            />
          )}
        </div>

        {/* Kunci API Password */}
        <div className="card p-4 space-y-3">
          <div className="flex items-center justify-between">
            <label className="text-xs font-semibold uppercase tracking-wider text-gray-400 flex items-center gap-1.5">
              <Sparkles size={14} className="text-amber-400" />
              API Key (Kata Sandi API)
            </label>
            <button
              onClick={() => setShowPassword(!showPassword)}
              className="text-gray-400 hover:text-white text-xs flex items-center gap-1"
            >
              {showPassword ? <EyeOff size={13} /> : <Eye size={13} />}
              {showPassword ? "Sembunyikan" : "Tampilkan"}
            </button>
          </div>

          <div className="flex items-center gap-2">
            <input
              type={showPassword ? "text" : "password"}
              readOnly
              value={apiKey}
              className="w-full px-3 py-2 bg-dark-800 border border-dark-600 rounded-lg text-xs font-mono text-purple-300 select-all"
            />
            <button
              onClick={() => copyToClipboard(apiKey, "apiKey")}
              className="btn btn-secondary px-3 py-2 text-xs flex-shrink-0"
              title="Salin API Key"
            >
              {copiedKey === "apiKey" ? <Check size={14} className="text-emerald-400" /> : <Copy size={14} />}
            </button>
          </div>
        </div>

        {/* Model Default & Caveman */}
        <div className="card p-4 space-y-3">
          <div className="flex items-center justify-between">
            <label className="text-xs font-semibold uppercase tracking-wider text-gray-400 flex items-center gap-1.5">
              <Cpu size={14} className="text-emerald-400" />
              Pilihan Model Utama
            </label>
            <span className="text-[10px] text-emerald-400 font-medium">Auto-Failover</span>
          </div>

          <select
            value={selectedModel}
            onChange={(e) => setSelectedModel(e.target.value)}
            className="w-full px-3 py-2 bg-dark-800 border border-dark-600 rounded-lg text-xs text-white focus:outline-none focus:border-purple-500"
          >
            {(configData.models || []).map((m) => (
              <option key={m.id} value={m.id}>
                {m.name} ({m.badge})
              </option>
            ))}
          </select>

          <label className="flex items-center gap-2 cursor-pointer pt-0.5 select-none text-xs text-gray-300">
            <input
              type="checkbox"
              checked={enableCaveman}
              onChange={(e) => setEnableCaveman(e.target.checked)}
              className="rounded bg-dark-800 border-dark-600 text-purple-600 focus:ring-0 focus:ring-offset-0"
            />
            <span>Aktifkan instruksi <strong>Caveman</strong> (Hemat token)</span>
          </label>
        </div>
      </div>

      {/* Navigasi Tab Agent */}
      <div className="flex items-center gap-2 border-b border-dark-700 pb-2 overflow-x-auto">
        {agents.map((agent) => {
          const Icon = agent.icon;
          const isActive = activeAgent === agent.id;
          return (
            <button
              key={agent.id}
              onClick={() => setActiveAgent(agent.id)}
              className={`px-4 py-2.5 rounded-xl font-medium text-xs sm:text-sm flex items-center gap-2 whitespace-nowrap transition-all ${
                isActive
                  ? "bg-purple-600 text-white shadow-lg shadow-purple-600/20"
                  : "bg-dark-800/80 hover:bg-dark-700 text-gray-400 hover:text-white border border-dark-700"
              }`}
            >
              <Icon size={16} />
              <span>{agent.name}</span>
              <span
                className={`text-[10px] px-1.5 py-0.5 rounded-full ${
                  isActive ? "bg-white/20 text-white" : "bg-dark-900 text-gray-400"
                }`}
              >
                {agent.badge}
              </span>
            </button>
          );
        })}
      </div>

      {/* Konten Tab Agent */}
      <div className="space-y-6">
        {/* 1. CURSOR */}
        {activeAgent === "cursor" && (
          <div className="space-y-5">
            <div className="card p-5 space-y-4">
              <div className="flex items-center justify-between flex-wrap gap-2">
                <div>
                  <h3 className="text-base font-semibold text-white flex items-center gap-2">
                    <Code2 className="text-purple-400" size={18} />
                    Konfigurasi Cursor IDE
                  </h3>
                  <p className="text-xs text-gray-400 mt-0.5">
                    Gunakan AGYBridge sebagai OpenAI-compatible provider kustom di Cursor.
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  <button
                    onClick={() => copyToClipboard(cursorRulesContent, "cursorRules")}
                    className="btn btn-secondary text-xs flex items-center gap-1.5"
                  >
                    {copiedKey === "cursorRules" ? <Check size={14} className="text-emerald-400" /> : <Copy size={14} />}
                    Salin .cursorrules
                  </button>
                  <button
                    onClick={() => downloadFile(".cursorrules", cursorRulesContent)}
                    className="btn btn-primary text-xs flex items-center gap-1.5"
                  >
                    <Download size={14} />
                    Unduh .cursorrules
                  </button>
                </div>
              </div>

              {/* Panduan Langkah Cursor */}
              <div className="grid grid-cols-1 md:grid-cols-3 gap-3 text-xs">
                <div className="bg-dark-900 border border-dark-700 p-3.5 rounded-xl space-y-1">
                  <div className="font-semibold text-purple-400 flex items-center gap-1.5">
                    <span className="w-4 h-4 rounded-full bg-purple-600/30 text-purple-300 flex items-center justify-center text-[10px]">1</span>
                    Buka Settings Cursor
                  </div>
                  <p className="text-gray-400">Tekan <kbd className="px-1 py-0.5 bg-dark-800 rounded text-gray-300">Ctrl/Cmd + Shift + J</kbd> lalu pilih tab <strong>Models</strong>.</p>
                </div>

                <div className="bg-dark-900 border border-dark-700 p-3.5 rounded-xl space-y-1">
                  <div className="font-semibold text-purple-400 flex items-center gap-1.5">
                    <span className="w-4 h-4 rounded-full bg-purple-600/30 text-purple-300 flex items-center justify-center text-[10px]">2</span>
                    Override OpenAI Base URL
                  </div>
                  <p className="text-gray-400">Aktifkan <strong>OpenAI API Key</strong>, masukkan Base URL: <code className="text-purple-300">{v1Url}</code></p>
                </div>

                <div className="bg-dark-900 border border-dark-700 p-3.5 rounded-xl space-y-1">
                  <div className="font-semibold text-purple-400 flex items-center gap-1.5">
                    <span className="w-4 h-4 rounded-full bg-purple-600/30 text-purple-300 flex items-center justify-center text-[10px]">3</span>
                    Tambah Model Kustom
                  </div>
                  <p className="text-gray-400">Tambahkan nama model: <code className="text-emerald-300 font-mono">{selectedModel}</code> atau model lainnya.</p>
                </div>
              </div>

              {/* Pratinjau .cursorrules */}
              <div className="space-y-2">
                <div className="flex items-center justify-between text-xs text-gray-400">
                  <span>Pratinjau berkas <code>.cursorrules</code> (simpan di root project):</span>
                </div>
                <pre className="bg-dark-900 border border-dark-700 rounded-xl p-4 text-xs font-mono text-gray-300 overflow-x-auto leading-relaxed">
                  {cursorRulesContent}
                </pre>
              </div>

              {/* VS Code settings snippet */}
              <div className="space-y-2 pt-2 border-t border-dark-700">
                <div className="flex items-center justify-between text-xs text-gray-400">
                  <span>Konfigurasi <code>.cursor/settings.json</code> atau <code>settings.json</code>:</span>
                  <button
                    onClick={() => copyToClipboard(cursorSettingsJson, "cursorSettings")}
                    className="text-purple-400 hover:text-purple-300 flex items-center gap-1"
                  >
                    {copiedKey === "cursorSettings" ? <Check size={12} className="text-emerald-400" /> : <Copy size={12} />}
                    Salin JSON
                  </button>
                </div>
                <pre className="bg-dark-900 border border-dark-700 rounded-xl p-3 text-xs font-mono text-purple-300 overflow-x-auto">
                  {cursorSettingsJson}
                </pre>
              </div>
            </div>
          </div>
        )}

        {/* 2. CLAUDE CODE */}
        {activeAgent === "claude-code" && (
          <div className="space-y-5">
            <div className="card p-5 space-y-4">
              <div className="flex items-center justify-between flex-wrap gap-2">
                <div>
                  <h3 className="text-base font-semibold text-white flex items-center gap-2">
                    <Terminal className="text-purple-400" size={18} />
                    Anthropic Claude Code CLI
                  </h3>
                  <p className="text-xs text-gray-400 mt-0.5">
                    Hubungkan CLI resmi Claude Code ke AGYBridge menggunakan variabel lingkungan.
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  <button
                    onClick={() => copyToClipboard(claudeCodeBash, "claudeBash")}
                    className="btn btn-secondary text-xs flex items-center gap-1.5"
                  >
                    {copiedKey === "claudeBash" ? <Check size={14} className="text-emerald-400" /> : <Copy size={14} />}
                    Salin Bash
                  </button>
                  <button
                    onClick={() => downloadFile(".env.claude", claudeCodeBash)}
                    className="btn btn-primary text-xs flex items-center gap-1.5"
                  >
                    <Download size={14} />
                    Unduh .env.claude
                  </button>
                </div>
              </div>

              {/* Terminal Bash Snippet */}
              <div className="space-y-2">
                <div className="flex items-center justify-between text-xs text-gray-400">
                  <span className="font-semibold text-gray-300">Linux / macOS / Git Bash:</span>
                </div>
                <pre className="bg-dark-900 border border-dark-700 rounded-xl p-4 text-xs font-mono text-emerald-400 overflow-x-auto leading-relaxed">
                  {claudeCodeBash}
                </pre>
              </div>

              {/* Windows PowerShell Snippet */}
              <div className="space-y-2">
                <div className="flex items-center justify-between text-xs text-gray-400">
                  <span className="font-semibold text-gray-300">Windows PowerShell:</span>
                  <button
                    onClick={() => copyToClipboard(claudeCodePowerShell, "claudePs")}
                    className="text-purple-400 hover:text-purple-300 flex items-center gap-1"
                  >
                    {copiedKey === "claudePs" ? <Check size={12} className="text-emerald-400" /> : <Copy size={12} />}
                    Salin PowerShell
                  </button>
                </div>
                <pre className="bg-dark-900 border border-dark-700 rounded-xl p-4 text-xs font-mono text-blue-300 overflow-x-auto leading-relaxed">
                  {claudeCodePowerShell}
                </pre>
              </div>

              <div className="bg-purple-900/20 border border-purple-500/20 rounded-xl p-3.5 text-xs text-gray-300 flex items-start gap-2.5">
                <Sparkles size={16} className="text-purple-400 flex-shrink-0 mt-0.5" />
                <p>
                  <strong>Tips Claude Code:</strong> Anda dapat menggunakan model <code>claude-sonnet-4-6</code> atau <code>gemini-3.8-flash-high</code>. AGYBridge secara transparan menerjemahkan format request dan response sehingga semua fitur Claude Code CLI berjalan mulus.
                </p>
              </div>
            </div>
          </div>
        )}

        {/* 3. CLINE / ROO CODE */}
        {activeAgent === "cline" && (
          <div className="space-y-5">
            <div className="card p-5 space-y-4">
              <div className="flex items-center justify-between flex-wrap gap-2">
                <div>
                  <h3 className="text-base font-semibold text-white flex items-center gap-2">
                    <Layers className="text-purple-400" size={18} />
                    Cline &amp; Roo Code (VS Code Extension)
                  </h3>
                  <p className="text-xs text-gray-400 mt-0.5">
                    Ekstensi autonomous coding agent terbaik untuk Visual Studio Code.
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  <button
                    onClick={() => copyToClipboard(clineSettingsJson, "clineSettings")}
                    className="btn btn-secondary text-xs flex items-center gap-1.5"
                  >
                    {copiedKey === "clineSettings" ? <Check size={14} className="text-emerald-400" /> : <Copy size={14} />}
                    Salin Pengaturan
                  </button>
                  <button
                    onClick={() => downloadFile("cline_settings.json", clineSettingsJson)}
                    className="btn btn-primary text-xs flex items-center gap-1.5"
                  >
                    <Download size={14} />
                    Unduh JSON
                  </button>
                </div>
              </div>

              {/* Form Ringkasan Pengaturan Cline */}
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-xs">
                <div className="bg-dark-900 border border-dark-700 p-3 rounded-lg">
                  <div className="text-gray-500 mb-1">API Provider:</div>
                  <div className="font-semibold text-white">OpenAI-Compatible</div>
                </div>
                <div className="bg-dark-900 border border-dark-700 p-3 rounded-lg">
                  <div className="text-gray-500 mb-1">Base URL:</div>
                  <div className="font-mono text-purple-300 font-semibold">{v1Url}</div>
                </div>
                <div className="bg-dark-900 border border-dark-700 p-3 rounded-lg">
                  <div className="text-gray-500 mb-1">API Key:</div>
                  <div className="font-mono text-amber-300 font-semibold">{showPassword ? apiKey : "••••••••••••••••"}</div>
                </div>
                <div className="bg-dark-900 border border-dark-700 p-3 rounded-lg">
                  <div className="text-gray-500 mb-1">Model ID:</div>
                  <div className="font-mono text-emerald-300 font-semibold">{selectedModel}</div>
                </div>
              </div>

              {/* Pratinjau JSON Pengaturan */}
              <div className="space-y-2">
                <div className="flex items-center justify-between text-xs text-gray-400">
                  <span>Nilai konfigurasi siap tempel:</span>
                </div>
                <pre className="bg-dark-900 border border-dark-700 rounded-xl p-4 text-xs font-mono text-gray-300 overflow-x-auto">
                  {clineSettingsJson}
                </pre>
              </div>
            </div>
          </div>
        )}

        {/* 4. CONTINUE.DEV */}
        {activeAgent === "continue" && (
          <div className="space-y-5">
            <div className="card p-5 space-y-4">
              <div className="flex items-center justify-between flex-wrap gap-2">
                <div>
                  <h3 className="text-base font-semibold text-white flex items-center gap-2">
                    <Cpu className="text-purple-400" size={18} />
                    Continue.dev (VS Code &amp; JetBrains)
                  </h3>
                  <p className="text-xs text-gray-400 mt-0.5">
                    Asisten AI open source untuk autocomplete dan chat di editor favorit Anda.
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  <button
                    onClick={() => copyToClipboard(continueConfigJson, "continueConfig")}
                    className="btn btn-secondary text-xs flex items-center gap-1.5"
                  >
                    {copiedKey === "continueConfig" ? <Check size={14} className="text-emerald-400" /> : <Copy size={14} />}
                    Salin config.json
                  </button>
                  <button
                    onClick={() => downloadFile("config.json", continueConfigJson)}
                    className="btn btn-primary text-xs flex items-center gap-1.5"
                  >
                    <Download size={14} />
                    Unduh config.json
                  </button>
                </div>
              </div>

              <div className="bg-blue-500/10 border border-blue-500/20 rounded-xl p-3.5 text-xs text-gray-300">
                Lokasi berkas: Simpan atau gabungkan ke <code>~/.continue/config.json</code> di komputer lokal Anda.
              </div>

              {/* JSON Editor continue */}
              <div className="space-y-2">
                <pre className="bg-dark-900 border border-dark-700 rounded-xl p-4 text-xs font-mono text-purple-300 overflow-x-auto max-h-[380px] overflow-y-auto leading-relaxed">
                  {continueConfigJson}
                </pre>
              </div>
            </div>
          </div>
        )}

        {/* 5. AIDER & SDK */}
        {activeAgent === "aider-sdk" && (
          <div className="space-y-5">
            {/* Aider CLI */}
            <div className="card p-5 space-y-4">
              <div className="flex items-center justify-between flex-wrap gap-2">
                <h3 className="text-base font-semibold text-white flex items-center gap-2">
                  <Sparkles className="text-amber-400" size={18} />
                  Aider AI Pair Programming
                </h3>
                <button
                  onClick={() => copyToClipboard(aiderCommand, "aiderCmd")}
                  className="btn btn-secondary text-xs flex items-center gap-1.5"
                >
                  {copiedKey === "aiderCmd" ? <Check size={14} className="text-emerald-400" /> : <Copy size={14} />}
                  Salin Perintah
                </button>
              </div>
              <pre className="bg-dark-900 border border-dark-700 rounded-xl p-3.5 text-xs font-mono text-emerald-400 overflow-x-auto">
                {aiderCommand}
              </pre>
            </div>

            {/* Python OpenAI SDK */}
            <div className="card p-5 space-y-4">
              <div className="flex items-center justify-between flex-wrap gap-2">
                <h3 className="text-base font-semibold text-white flex items-center gap-2">
                  <Code2 className="text-purple-400" size={18} />
                  Python (OpenAI SDK)
                </h3>
                <div className="flex items-center gap-2">
                  <button
                    onClick={() => copyToClipboard(pythonSdkSnippet, "pySdk")}
                    className="btn btn-secondary text-xs flex items-center gap-1.5"
                  >
                    {copiedKey === "pySdk" ? <Check size={14} className="text-emerald-400" /> : <Copy size={14} />}
                    Salin Kode Python
                  </button>
                  <button
                    onClick={() => downloadFile("test_agybridge.py", pythonSdkSnippet)}
                    className="btn btn-primary text-xs flex items-center gap-1.5"
                  >
                    <Download size={14} />
                    Unduh .py
                  </button>
                </div>
              </div>
              <pre className="bg-dark-900 border border-dark-700 rounded-xl p-4 text-xs font-mono text-gray-300 overflow-x-auto leading-relaxed">
                {pythonSdkSnippet}
              </pre>
            </div>

            {/* cURL API Direct */}
            <div className="card p-5 space-y-4">
              <div className="flex items-center justify-between flex-wrap gap-2">
                <h3 className="text-base font-semibold text-white flex items-center gap-2">
                  <Terminal className="text-blue-400" size={18} />
                  Direct cURL Request
                </h3>
                <button
                  onClick={() => copyToClipboard(curlSnippet, "curlCmd")}
                  className="btn btn-secondary text-xs flex items-center gap-1.5"
                >
                  {copiedKey === "curlCmd" ? <Check size={14} className="text-emerald-400" /> : <Copy size={14} />}
                  Salin cURL
                </button>
              </div>
              <pre className="bg-dark-900 border border-dark-700 rounded-xl p-4 text-xs font-mono text-blue-300 overflow-x-auto leading-relaxed">
                {curlSnippet}
              </pre>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
