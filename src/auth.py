"""
Authentication API module (Antigravity credential mode only)
"""

import asyncio
import socket
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Dict, Optional
from urllib.parse import parse_qs, urlparse

import oauthlib.oauth2.rfc6749.parameters

from config import get_config_value, get_antigravity_api_url, get_panel_password
from log import log

from .google_oauth_api import (
    Credentials,
    Flow,
    fetch_project_id_and_tier,
    get_user_email,
)
from .storage.database import get_database
from .utils import (
    ANTIGRAVITY_CLIENT_ID,
    ANTIGRAVITY_CLIENT_SECRET,
    ANTIGRAVITY_SCOPES,
    ANTIGRAVITY_USER_AGENT,
    CALLBACK_HOST,
    TOKEN_URL,
)


async def get_callback_port():
    """Get OAuth callback port"""
    return int(await get_config_value("oauth_callback_port", "11451", "OAUTH_CALLBACK_PORT"))


def _prepare_credentials_data(credentials: Credentials, project_id: str, subscription_tier: str = None) -> Dict[str, Any]:
    """Prepare credential data dictionary (Antigravity mode)"""
    creds_data = {
        "client_id": ANTIGRAVITY_CLIENT_ID,
        "client_secret": ANTIGRAVITY_CLIENT_SECRET,
        "token": credentials.access_token,
        "refresh_token": credentials.refresh_token,
        "project_id": project_id,
    }

    if credentials.expires_at:
        if credentials.expires_at.tzinfo is None:
            expiry_utc = credentials.expires_at.replace(tzinfo=timezone.utc)
        else:
            expiry_utc = credentials.expires_at
        creds_data["expiry"] = expiry_utc.isoformat()

    return creds_data


def _cleanup_auth_flow_server(state: str):
    """Cleanup server resources for an authentication flow"""
    if state in auth_flows:
        flow_data_to_clean = auth_flows[state]
        try:
            if flow_data_to_clean.get("server"):
                server = flow_data_to_clean["server"]
                port = flow_data_to_clean.get("callback_port")
                async_shutdown_server(server, port)
        except Exception as e:
            log.debug(f"Error shutting down server: {e}")
        del auth_flows[state]


@contextmanager
def _patch_oauthlib_validation():
    """Temporarily relax oauthlib token parameter validation (warnings do not interrupt)"""
    module = oauthlib.oauth2.rfc6749.parameters
    original_validate = module.validate_token_parameters

    def patched_validate(params):
        try:
            return original_validate(params)
        except Warning:
            pass

    module.validate_token_parameters = patched_validate
    try:
        yield
    finally:
        module.validate_token_parameters = original_validate


# Global state management - strictly limited in size
auth_flows = {}  # Active auth flows
MAX_AUTH_FLOWS = 20  # Limit max flows
DEFAULT_PROJECT_ID = "aicode-consumers"  # Fallback project ID


def cleanup_auth_flows_for_memory():
    """Cleanup auth flows to free memory"""
    global auth_flows
    cleanup_expired_flows()
    if len(auth_flows) > 10:
        sorted_flows = sorted(
            auth_flows.items(), key=lambda x: x[1].get("created_at", 0), reverse=True
        )
        new_auth_flows = dict(sorted_flows[:10])

        for state, flow_data in auth_flows.items():
            if state not in new_auth_flows:
                try:
                    if flow_data.get("server"):
                        server = flow_data["server"]
                        port = flow_data.get("callback_port")
                        async_shutdown_server(server, port)
                except Exception:
                    pass
                flow_data.clear()

        auth_flows = new_auth_flows
        log.info(f"Cleaned auth flows, keeping {len(auth_flows)} latest flows")

    return len(auth_flows)


def cleanup_expired_flows():
    """Cleanup expired auth flows"""
    current_time = time.time()
    EXPIRY_TIME = 600  # 10 minutes expiry

    states_to_remove = [
        state
        for state, flow_data in auth_flows.items()
        if current_time - flow_data["created_at"] > EXPIRY_TIME
    ]

    cleaned_count = 0
    for state in states_to_remove:
        flow_data = auth_flows.get(state)
        if flow_data:
            try:
                if flow_data.get("server"):
                    server = flow_data["server"]
                    port = flow_data.get("callback_port")
                    async_shutdown_server(server, port)
            except Exception as e:
                log.debug(f"Failed to shutdown server while cleaning expired flow: {e}")

            cleaned_count += 1

    if cleaned_count > 0:
        for state in states_to_remove:
            auth_flows.pop(state, None)
        log.info(f"Cleaned {cleaned_count} expired auth flows")


async def find_available_port(start_port: int = None) -> int:
    """Find available port dynamically"""
    if start_port is None:
        start_port = await get_callback_port()

    # Try default range
    for port in range(start_port, start_port + 100):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                s.bind(("0.0.0.0", port))
                log.info(f"Found available port: {port}")
                return port
        except OSError:
            continue

    # Let OS assign if none in range
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("0.0.0.0", 0))
            port = s.getsockname()[1]
            log.info(f"OS assigned available port: {port}")
            return port
    except OSError as e:
        log.error(f"Cannot find available port: {e}")
        raise RuntimeError("No available port found")


def create_callback_server(port: int) -> HTTPServer:
    """Create callback HTTP server on specified port"""
    try:
        server = HTTPServer(("0.0.0.0", port), AuthCallbackHandler)
        server.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.timeout = 1.0
        log.info(f"Created OAuth callback server on port: {port}")
        return server
    except OSError as e:
        log.error(f"Failed to create server on port {port}: {e}")
        raise


class AuthCallbackHandler(BaseHTTPRequestHandler):
    """OAuth callback HTTP handler"""

    def do_GET(self):
        query_components = parse_qs(urlparse(self.path).query)
        code = query_components.get("code", [None])[0]
        state = query_components.get("state", [None])[0]

        log.info(f"OAuth callback received: code={'obtained' if code else 'missing'}, state={state}")

        if code and state and state in auth_flows:
            auth_flows[state]["code"] = code
            auth_flows[state]["completed"] = True

            log.info(f"OAuth callback successfully handled: state={state}")

            html_content = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>AGYBridge - Autentikasi Berhasil</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #0f172a; color: #f8fafc; display: flex; align-items: center; justify-content: center; height: 100vh; margin: 0; text-align: center; }}
    .card {{ background: #1e293b; padding: 2.5rem; border-radius: 1rem; border: 1px solid #334155; box-shadow: 0 20px 25px -5px rgba(0,0,0,0.5); max-width: 420px; }}
    h1 {{ color: #10b981; font-size: 1.5rem; margin-bottom: 0.5rem; }}
    p {{ color: #94a3b8; font-size: 0.95rem; line-height: 1.5; }}
    .badge {{ display: inline-block; background: #064e3b; color: #34d399; padding: 0.25rem 0.75rem; border-radius: 9999px; font-size: 0.8rem; font-weight: 600; margin-bottom: 1rem; }}
  </style>
</head>
<body>
  <div class="card">
    <div class="badge">AGYBridge OAuth</div>
    <h1>Autentikasi Berhasil!</h1>
    <p>Akun Google Anda berhasil diverifikasi. Jendela ini akan tertutup otomatis dalam beberapa detik.</p>
  </div>
  <script>
    if (window.opener) {{
      try {{
        window.opener.postMessage({{ type: 'AGYBRIDGE_OAUTH_SUCCESS', state: '{state}' }}, '*');
      }} catch (e) {{}}
      setTimeout(function() {{ window.close(); }}, 2000);
    }}
  </script>
</body>
</html>"""
            self.send_response(200)
            self.send_header("Content-type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(html_content.encode("utf-8"))
        else:
            self.send_response(400)
            self.send_header("Content-type", "text/html; charset=utf-8")
            self.end_headers()
            fail_html = """<!DOCTYPE html>
<html><body style="font-family: sans-serif; background: #0f172a; color: #f8fafc; text-align: center; padding-top: 100px;">
  <h1 style="color: #ef4444;">Autentikasi Gagal</h1>
  <p style="color: #94a3b8;">Parameter alur autentikasi tidak valid atau telah kedaluwarsa. Silakan coba kembali dari panel.</p>
</body></html>"""
            self.wfile.write(fail_html.encode("utf-8"))

    def log_message(self, format, *args):
        pass


async def create_auth_url(
    project_id: Optional[str] = None, user_session: str = None
) -> Dict[str, Any]:
    """Create authentication URL with dynamic port assignment (Antigravity mode)"""
    try:
        callback_port = await find_available_port()
        callback_url = f"http://{CALLBACK_HOST}:{callback_port}"

        try:
            callback_server = create_callback_server(callback_port)
            server_thread = threading.Thread(
                target=callback_server.serve_forever,
                daemon=True,
                name=f"OAuth-Server-{callback_port}",
            )
            server_thread.start()
            log.info(f"OAuth callback server started on port: {callback_port}")
        except Exception as e:
            log.error(f"Failed to start callback server: {e}")
            return {
                "success": False,
                "error": f"Failed to start OAuth callback server on port {callback_port}: {str(e)}",
            }

        flow = Flow(
            client_id=ANTIGRAVITY_CLIENT_ID,
            client_secret=ANTIGRAVITY_CLIENT_SECRET,
            scopes=ANTIGRAVITY_SCOPES,
            redirect_uri=callback_url,
        )

        if user_session:
            state = f"{user_session}_{str(uuid.uuid4())}"
        else:
            state = str(uuid.uuid4())

        auth_url = flow.get_auth_url(state=state)

        if len(auth_flows) >= MAX_AUTH_FLOWS:
            oldest_state = min(auth_flows.keys(), key=lambda k: auth_flows[k].get("created_at", 0))
            try:
                old_flow = auth_flows[oldest_state]
                if old_flow.get("server"):
                    server = old_flow["server"]
                    port = old_flow.get("callback_port")
                    async_shutdown_server(server, port)
            except Exception as e:
                log.warning(f"Failed to cleanup old auth flow {oldest_state}: {e}")

            del auth_flows[oldest_state]
            log.debug(f"Removed oldest auth flow: {oldest_state}")

        auth_flows[state] = {
            "flow": flow,
            "project_id": project_id,
            "user_session": user_session,
            "callback_port": callback_port,
            "callback_url": callback_url,
            "server": callback_server,
            "server_thread": server_thread,
            "code": None,
            "completed": False,
            "created_at": time.time(),
            "auto_project_detection": project_id is None,
        }

        cleanup_expired_flows()

        log.info(f"OAuth flow created: state={state}, project_id={project_id}")
        log.info(f"Auth URL will redirect to {callback_url}")
        log.info(f"Port allocated: {callback_port}")

        return {
            "auth_url": auth_url,
            "state": state,
            "callback_port": callback_port,
            "success": True,
            "auto_project_detection": project_id is None,
            "detected_project_id": project_id,
        }

    except Exception as e:
        log.error(f"Failed to create auth URL: {e}")
        return {"success": False, "error": str(e)}


async def _save_antigravity_credential(
    credentials: Credentials,
    state: str,
    flow_data: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Antigravity mode: Fetch email, project_id, tier and persist credential.
    """
    email = None
    try:
        email = await get_user_email(credentials)
    except Exception as e:
        log.warning(f"Failed to obtain user email: {e}")

    if not email:
        _cleanup_auth_flow_server(state)
        log.error("Antigravity OAuth failed: unable to fetch account email")
        return {"success": False, "error": "Gagal mendapatkan email akun, autentikasi gagal"}

    log.info("Antigravity mode: Fetching project_id and tier from API...")
    antigravity_url = await get_antigravity_api_url()
    project_id, subscription_tier = await fetch_project_id_and_tier(
        credentials.access_token,
        ANTIGRAVITY_USER_AGENT,
        antigravity_url
    )
    if project_id:
        log.info(f"Successfully fetched project_id: {project_id}, tier: {subscription_tier}")
    else:
        project_id = DEFAULT_PROJECT_ID
        log.warning(f"Unable to fetch project_id from API, fallback to default: {project_id}")

    if not subscription_tier:
        subscription_tier = "free"
        log.warning("Unable to fetch subscription tier, fallback to free")

    database = await get_database()
    creds_data = _prepare_credentials_data(
        credentials, project_id, subscription_tier=subscription_tier
    )
    creds_data["tier"] = subscription_tier
    await database.store_credential(email, creds_data)

    try:
        default_state = {
            "error_codes": [],
            "disabled": False,
            "last_success": time.time(),
            "tier": subscription_tier,
            "project_id": project_id,
        }
        await database.update_credential_state(email, default_state)
        log.info(f"Credential saved: {email} (tier={subscription_tier})")
    except Exception as e:
        log.warning(f"Failed to create default state for {email}: {e}")

    _cleanup_auth_flow_server(state)

    log.info("Antigravity OAuth successful, credentials persisted")
    return {
        "success": True,
        "credentials": creds_data,
        "email": email,
        "tier": subscription_tier,
        "auto_detected_project": bool(project_id),
    }


def wait_for_callback_sync(state: str, timeout: int = 300) -> Optional[str]:
    """Wait synchronously for OAuth callback to complete"""
    if state not in auth_flows:
        log.error(f"Auth flow with state {state} not found")
        return None

    flow_data = auth_flows[state]
    callback_port = flow_data["callback_port"]

    log.info(f"Waiting for OAuth callback on port: {callback_port}")

    start_time = time.time()
    while time.time() - start_time < timeout:
        if flow_data.get("code"):
            log.info("OAuth callback successfully received")
            return flow_data["code"]
        time.sleep(0.5)

        if state in auth_flows:
            flow_data = auth_flows[state]

    log.warning(f"Timeout waiting for OAuth callback ({timeout}s)")
    return None


async def asyncio_complete_auth_flow(
    project_id: Optional[str] = None, user_session: str = None
) -> Dict[str, Any]:
    """Complete authentication flow asynchronously (Antigravity mode)"""
    try:
        log.info(
            f"asyncio_complete_auth_flow execution started: project_id={project_id}, user_session={user_session}"
        )

        state = None
        flow_data = None

        log.debug(f"Current auth_flows: {list(auth_flows.keys())}")

        if project_id:
            log.info(f"Attempting to match project ID: {project_id}")
            for s, data in auth_flows.items():
                if data["project_id"] == project_id:
                    if user_session and data.get("user_session") == user_session:
                        state = s
                        flow_data = data
                        log.info(f"Found matching user session: {s}")
                        break
                    elif not state:
                        state = s
                        flow_data = data
                        log.info(f"Found matching project ID: {s}")

        if not state:
            log.info("No matching project ID found, looking for auto-detection flows")
            completed_flows = []
            for s, data in auth_flows.items():
                if data.get("auto_project_detection", False):
                    if user_session and data.get("user_session") == user_session:
                        if data.get("code"):
                            completed_flows.append((s, data, data.get("created_at", 0)))

            if completed_flows:
                completed_flows.sort(key=lambda x: x[2], reverse=True)
                state, flow_data, _ = completed_flows[0]
                log.info(f"Found completed auth flow: {state}")
            else:
                pending_flows = []
                for s, data in auth_flows.items():
                    if data.get("auto_project_detection", False):
                        if user_session and data.get("user_session") == user_session:
                            pending_flows.append((s, data, data.get("created_at", 0)))
                        elif not user_session:
                            pending_flows.append((s, data, data.get("created_at", 0)))

                if pending_flows:
                    pending_flows.sort(key=lambda x: x[2], reverse=True)
                    state, flow_data, _ = pending_flows[0]
                    log.info(f"Found pending auth flow: {state}")

        if not state or not flow_data:
            log.error(f"Auth flow not found: state={state}, flow_data exists={bool(flow_data)}")
            log.debug(f"All flow_data: {list(auth_flows.keys())}")
            return {"success": False, "error": "Alur autentikasi tidak ditemukan, silakan klik tombol Dapatkan URL terlebih dahulu"}

        log.info(f"Auth flow selected: state={state}")

        log.info("Checking OAuth authorization code...")
        max_wait_time = 60
        wait_interval = 1
        waited = 0

        while waited < max_wait_time:
            if flow_data.get("code"):
                log.info(f"OAuth authorization code detected, processing credentials (waited {waited}s)")
                break

            if waited % 5 == 0 and waited > 0:
                log.info(f"Still waiting for OAuth authorization... ({waited}/{max_wait_time}s)")

            await asyncio.sleep(wait_interval)
            waited += wait_interval

            if state in auth_flows:
                flow_data = auth_flows[state]

        if not flow_data.get("code"):
            log.error(f"Timeout waiting for OAuth callback after {waited}s")
            return {
                "success": False,
                "error": "Waktu tunggu callback OAuth habis, pastikan Anda telah menyelesaikan autentikasi di peramban dan melihat pesan sukses",
            }

        flow = flow_data["flow"]
        auth_code = flow_data["code"]

        log.info(f"Using auth code: {'***' + auth_code[-4:] if auth_code else 'None'}")

        with _patch_oauthlib_validation():
            try:
                log.info("Calling flow.exchange_code...")
                credentials = await flow.exchange_code(auth_code)
                log.info(
                    f"Successfully obtained credentials, token prefix: {credentials.access_token[:20] if credentials.access_token else 'None'}..."
                )
                return await _save_antigravity_credential(credentials, state, flow_data)

            except Exception as e:
                log.error(f"Failed to obtain credentials: {e}")
                return {"success": False, "error": f"Gagal mendapatkan kredensial: {str(e)}"}

    except Exception as e:
        log.error(f"asyncio_complete_auth_flow failed: {e}")
        return {"success": False, "error": str(e)}


async def complete_auth_flow_from_callback_url(
    callback_url: str, project_id: Optional[str] = None
) -> Dict[str, Any]:
    """Complete auth flow directly from callback URL without running local server"""
    try:
        log.info(f"Completing authentication from callback URL: {callback_url}")

        parsed_url = urlparse(callback_url)
        query_params = parse_qs(parsed_url.query)

        if "state" not in query_params or "code" not in query_params:
            return {"success": False, "error": "URL callback tidak memiliki parameter yang diperlukan (state atau code)"}

        state = query_params["state"][0]
        code = query_params["code"][0]

        log.info(f"Parsed from URL: state={state}, code=***")

        if state not in auth_flows:
            return {
                "success": False,
                "error": f"Alur autentikasi tidak ditemukan, silakan mulai autentikasi terlebih dahulu (state: {state})",
            }

        flow_data = auth_flows[state]
        flow = flow_data["flow"]

        log.info(f"Using redirect_uri: {flow.redirect_uri}")

        try:
            credentials = await flow.exchange_code(code)
            log.info("Successfully exchanged code for access token")
            return await _save_antigravity_credential(credentials, state, flow_data)

        except Exception as e:
            log.error(f"Failed to obtain credentials from callback URL: {e}")
            return {"success": False, "error": f"Gagal mendapatkan kredensial: {str(e)}"}

    except Exception as e:
        log.error(f"complete_auth_flow_from_callback_url failed: {e}")
        return {"success": False, "error": str(e)}


def async_shutdown_server(server, port):
    """Shutdown OAuth callback server asynchronously without blocking main loop"""

    def shutdown_server_async():
        try:
            shutdown_completed = threading.Event()

            def do_shutdown():
                try:
                    server.shutdown()
                    server.server_close()
                except Exception:
                    pass
                finally:
                    shutdown_completed.set()

            shutdown_thread = threading.Thread(target=do_shutdown, daemon=True)
            shutdown_thread.start()

            shutdown_completed.wait(timeout=2.0)

            if not shutdown_completed.is_set():
                try:
                    server.socket.close()
                except Exception:
                    pass

            log.info(f"OAuth callback server shut down (port: {port})")

        except Exception as e:
            log.debug(f"Error shutting down server: {e}")

    shutdown_thread = threading.Thread(target=shutdown_server_async, daemon=True)
    shutdown_thread.start()


def get_auth_status(project_id: str) -> Dict[str, Any]:
    """Get authentication status"""
    for state, flow_data in auth_flows.items():
        if flow_data["project_id"] == project_id:
            return {
                "status": "completed" if flow_data["completed"] else "pending",
                "state": state,
                "created_at": flow_data["created_at"],
            }

    return {"status": "not_found"}


async def verify_password(password: str) -> bool:
    """Verify panel password"""
    correct_password = await get_panel_password()
    return password == correct_password
