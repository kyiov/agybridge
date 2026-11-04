import axios from "axios";
import { getBasePath } from "./basePath.js";

const api = axios.create({
  // Use relative base path to ensure reverse proxies operate on identical subpaths
  baseURL: getBasePath(),
  timeout: 120000,
});

// Request interceptor - inject authorization token
api.interceptors.request.use((config) => {
  const token = localStorage.getItem("panelToken");
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// Response interceptor - handle unauthorized redirects
api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      localStorage.removeItem("panelToken");
      window.location.href = getBasePath();
    }
    return Promise.reject(error);
  }
);

export default api;
