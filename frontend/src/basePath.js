// Compute base path for the control panel (starting and ending with "/")
// Handles subpath deployments and reverse proxies gracefully
export function getBasePath() {
  const { pathname } = window.location;
  return pathname.endsWith("/") ? pathname : pathname + "/";
}
