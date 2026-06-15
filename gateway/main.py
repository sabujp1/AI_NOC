import asyncio
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends, HTTPException, status, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Dict, Any, List
from gateway.auth import verify_token, create_access_token
from gateway.client import librenms_client
from gateway.config import settings
from ai_engine.analyzer import analyze_alert_with_llm

# Mock User database for demo authentication
USERS_DB = {"admin": "admin123"}

# Mock in-memory background queue for alert events
alert_remediation_queue = asyncio.Queue()
background_task = None
active_connections: List[WebSocket] = []

def mask_key(key: str, suffix_len: int = 4) -> str:
    """Mask sensitive security API keys/tokens"""
    if not key or len(key) <= 8:
        return "****"
    return f"{key[:4]}...{key[-suffix_len:]}"

def update_env_file(updates: Dict[str, str]):
    """Rewrite `.env` file with updated key-value settings"""
    env_path = ".env"
    if not os.path.exists(env_path):
        env_path = ".env.example"
        
    lines = []
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
            
    updated_keys = set()
    new_lines = []
    
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key, val = stripped.split("=", 1)
            key = key.strip()
            if key in updates:
                new_lines.append(f"{key}={updates[key]}\n")
                updated_keys.add(key)
                continue
        new_lines.append(line)
        
    for key, val in updates.items():
        if key not in updated_keys:
            new_lines.append(f"{key}={val}\n")
            
    with open(".env", "w", encoding="utf-8") as f:
        f.writelines(new_lines)

async def broadcast_alert(alert: dict):
    """Broadcast alert event to all connected WebSockets"""
    for connection in active_connections:
        try:
            await connection.send_json(alert)
        except Exception:
            pass

async def process_remediation_queue():
    """Background worker processing alerts from the queue"""
    while True:
        try:
            alert = await alert_remediation_queue.get()
            print(f"[Queue Worker] Processing alert #{alert.get('alert_id')} from host: {alert.get('hostname')}")
            await asyncio.sleep(0.5)
            alert_remediation_queue.task_done()
        except asyncio.CancelledError:
            break
        except Exception as e:
            print(f"[Queue Worker] Error processing alert: {e}")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Start queue processing task
    global background_task
    background_task = asyncio.create_task(process_remediation_queue())
    yield
    # Shutdown: Cancel task
    if background_task:
        background_task.cancel()
        try:
            await background_task
        except asyncio.CancelledError:
            pass

app = FastAPI(title="AIOps NOC API Gateway", version="1.0.0", lifespan=lifespan)

class TokenRequest(BaseModel):
    username: str
    password: str

class AlertWebhookPayload(BaseModel):
    alert_id: int
    device_id: int
    hostname: str
    severity: str
    rule_name: str
    msg: str
    timestamp: str

class AIQueryRequest(BaseModel):
    query: str

class SettingsResponse(BaseModel):
    librenms_api_url: str
    librenms_api_token_masked: str
    openai_api_key_masked: str
    gemini_api_key_masked: str
    llm_provider: str
    llm_model: str

class SettingsUpdateRequest(BaseModel):
    librenms_api_url: str
    librenms_api_token: str
    openai_api_key: str
    gemini_api_key: str
    llm_provider: str
    llm_model: str

@app.post("/api/v1/auth/token")
def login(payload: TokenRequest):
    username = payload.username
    password = payload.password
    if USERS_DB.get(username) == password:
        token = create_access_token(data={"sub": username})
        return {"access_token": token, "token_type": "bearer"}
    raise HTTPException(status_code=400, detail="Incorrect username or password")

@app.get("/api/v1/devices")
async def get_devices(current_user: dict = Depends(verify_token)):
    """Proxies request to LibreNMS to fetch device list"""
    try:
        devices = await librenms_client.get_devices()
        return devices
    except Exception as e:
        raise HTTPException(status_code=520, detail=f"LibreNMS API connection error: {str(e)}")

@app.get("/api/v1/alerts")
async def get_alerts(current_user: dict = Depends(verify_token)):
    """Proxies request to LibreNMS to fetch active alerts"""
    try:
        alerts = await librenms_client.get_alerts()
        return alerts
    except Exception as e:
        raise HTTPException(status_code=520, detail=f"LibreNMS API connection error: {str(e)}")

@app.post("/api/v1/alerts/webhook")
async def receive_webhook(payload: AlertWebhookPayload):
    """
    Ingests alerts from LibreNMS Webhook Integration.
    Pushes alert to the mock remediation/AI queue and broadcasts via WebSocket.
    """
    alert_data = payload.dict()
    print(f"[Webhook] Received Alert: {alert_data['rule_name']} on {alert_data['hostname']}")
    
    # Enqueue alert for remediation worker
    await alert_remediation_queue.put(alert_data)
    
    # Stream alert real-time to the dashboard
    await broadcast_alert(alert_data)
    
    return {"status": "enqueued", "alert_id": payload.alert_id}

@app.post("/api/v1/ai/query")
async def query_ai(payload: AIQueryRequest):
    """Runs Natural Language queries against the AI Operations Analyzer with Live Network Context"""
    try:
        provider = settings.LLM_PROVIDER.lower()
        api_key = settings.GEMINI_API_KEY if provider == "gemini" else settings.OPENAI_API_KEY
        model_name = "gemini-1.5-flash" if provider == "gemini" and "gpt" in settings.LLM_MODEL else settings.LLM_MODEL
        
        # Retrieve live context from LibreNMS client
        devices_ctx = "No live devices retrieved."
        alerts_ctx = "No live alerts retrieved."
        bgp_ctx = "No BGP sessions retrieved."
        
        try:
            dev_data = await librenms_client.get_devices()
            devices = dev_data.get("devices", []) if isinstance(dev_data, dict) else dev_data
            if devices:
                # Format to a compact list of name, IP, OS, hardware, status (1/0)
                devices_ctx = "\n".join([
                    f"- Device: {d.get('sysName') or d.get('hostname')} | IP: {d.get('ip')} | OS: {d.get('os')} | Hardware: {d.get('hardware')} | Status: {'UP' if str(d.get('status')) in ('1', 'True', 'active') else 'DOWN'}"
                    for d in devices
                ])
        except Exception as e:
            devices_ctx = f"Error fetching devices: {str(e)}"
            
        try:
            al_data = await librenms_client.get_alerts()
            alerts = al_data.get("alerts", []) if isinstance(al_data, dict) else al_data
            if alerts:
                alerts_ctx = "\n".join([
                    f"- Alert ID: {a.get('alert_id')} | Device ID: {a.get('device_id')} | Rule: {a.get('rule_name')} | Severity: {a.get('severity')} | Message: {a.get('msg')}"
                    for a in alerts
                ])
            else:
                alerts_ctx = "No active alerts in the network."
        except Exception as e:
            alerts_ctx = f"Error fetching alerts: {str(e)}"

        try:
            bgp_data = await librenms_client.get_bgp_sessions()
            sessions = bgp_data.get("bgp_sessions", []) if isinstance(bgp_data, dict) else bgp_data
            if sessions:
                total_bgp = len(sessions)
                down_sessions = [s for s in sessions if s.get("bgpPeerState") != "established"]
                down_bgp = len(down_sessions)
                up_bgp = total_bgp - down_bgp
                bgp_summary = f"Total BGP Sessions: {total_bgp} | Established (Up): {up_bgp} | Down (Idle/Active/Connect): {down_bgp}"
                
                if down_sessions:
                    down_details = "\n".join([
                        f"- Down BGP Peer Identifier: {s.get('bgpPeerIdentifier')} | Remote AS: {s.get('bgpPeerRemoteAs')} | Current State: {s.get('bgpPeerState')} | Device ID: {s.get('device_id')}"
                        for s in down_sessions
                    ])
                    bgp_ctx = f"{bgp_summary}\nDown BGP Sessions List:\n{down_details}"
                else:
                    bgp_ctx = f"{bgp_summary}\nAll BGP sessions are operational and established."
        except Exception as e:
            bgp_ctx = f"Error fetching BGP sessions: {str(e)}"
            
        full_query = (
            f"User Inquiry: {payload.query}\n\n"
            f"--- LIVE NETWORK STATE CONTEXT FROM LIBRENMS ---\n"
            f"Active Devices List:\n{devices_ctx}\n\n"
            f"Active Alerts List:\n{alerts_ctx}\n\n"
            f"BGP Sessions Status:\n{bgp_ctx}\n"
        )
        
        analysis = analyze_alert_with_llm(
            alert_string=full_query,
            api_key=api_key,
            model_name=model_name,
            provider=provider
        )
        return analysis
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI Engine failed to run query: {str(e)}")

@app.get("/api/v1/settings", response_model=SettingsResponse)
def get_settings(current_user: dict = Depends(verify_token)):
    """Retrieves current config parameters with masked secrets"""
    return SettingsResponse(
        librenms_api_url=settings.LIBRENMS_API_URL,
        librenms_api_token_masked=mask_key(settings.LIBRENMS_API_TOKEN),
        openai_api_key_masked=mask_key(settings.OPENAI_API_KEY),
        gemini_api_key_masked=mask_key(settings.GEMINI_API_KEY),
        llm_provider=settings.LLM_PROVIDER,
        llm_model=settings.LLM_MODEL
    )

@app.post("/api/v1/settings")
def save_settings(payload: SettingsUpdateRequest, current_user: dict = Depends(verify_token)):
    """Updates runtime config and persists values to the .env file"""
    updates = {}
    
    settings.LIBRENMS_API_URL = payload.librenms_api_url
    updates["LIBRENMS_API_URL"] = payload.librenms_api_url
    
    if "..." not in payload.librenms_api_token and payload.librenms_api_token != "****":
        settings.LIBRENMS_API_TOKEN = payload.librenms_api_token
        updates["LIBRENMS_API_TOKEN"] = payload.librenms_api_token
        
    if "..." not in payload.openai_api_key and payload.openai_api_key != "****":
        settings.OPENAI_API_KEY = payload.openai_api_key
        updates["OPENAI_API_KEY"] = payload.openai_api_key

    if "..." not in payload.gemini_api_key and payload.gemini_api_key != "****":
        settings.GEMINI_API_KEY = payload.gemini_api_key
        updates["GEMINI_API_KEY"] = payload.gemini_api_key
        
    settings.LLM_PROVIDER = payload.llm_provider
    updates["LLM_PROVIDER"] = payload.llm_provider
    
    settings.LLM_MODEL = payload.llm_model
    updates["LLM_MODEL"] = payload.llm_model
    
    try:
        update_env_file(updates)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save environment file: {str(e)}")
        
    # Reinitialize client attributes
    librenms_client.base_url = settings.LIBRENMS_API_URL.rstrip('/')
    librenms_client.headers["X-Auth-Token"] = settings.LIBRENMS_API_TOKEN
    
    return {"status": "success", "message": "API Settings successfully updated and saved"}

# Real-time WebSocket connection point for Dashboard
@app.websocket("/api/v1/ws/alerts")
async def websocket_alerts(websocket: WebSocket):
    await websocket.accept()
    active_connections.append(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        active_connections.remove(websocket)

# Serve static dashboard files
try:
    app.mount("/static", StaticFiles(directory="gateway/static"), name="static")
except Exception:
    pass

@app.get("/")
@app.get("/dashboard")
async def serve_dashboard():
    """Serves the main single page dashboard index.html"""
    return FileResponse("gateway/static/index.html")
