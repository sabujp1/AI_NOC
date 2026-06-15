import subprocess
import time
import httpx
import sys
from ai_engine.analyzer import analyze_alert_with_llm

def run_tests():
    print("=== Launching FastAPI API Gateway Server ===")
    # Run uvicorn gateway.main:app --host 127.0.0.1 --port 8000
    server_process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "gateway.main:app", "--host", "127.0.0.1", "--port", "8000"]
    )
    
    # Wait for server to start
    time.sleep(2)
    
    client = httpx.Client(base_url="http://127.0.0.1:8000", timeout=60.0)
    
    # Wait dynamically for server to start
    print("Waiting for server to start...")
    server_ready = False
    for i in range(20): # up to 10 seconds max
        try:
            res = client.get("/")
            server_ready = True
            print("-> Server is up and listening!")
            break
        except (httpx.ConnectError, httpx.ConnectTimeout):
            time.sleep(0.5)
            
    if not server_ready:
        print("-> ERROR: Server failed to start and bind within 10 seconds.")
        server_process.terminate()
        sys.exit(1)
    
    success = True
    try:
        # Test 1: Authenticate
        print("\nTest 1: Authenticating to API Gateway...")
        login_res = client.post("/api/v1/auth/token", json={"username": "admin", "password": "admin123"})
        if login_res.status_code == 200:
            token = login_res.json()["access_token"]
            headers = {"Authorization": f"Bearer {token}"}
            print(f"-> SUCCESS: Received token: {token[:20]}...")
        else:
            print(f"-> FAILURE: Login failed with code {login_res.status_code}: {login_res.text}")
            success = False
            token = None
            headers = {}
            
        # Test 2: Ingest Webhook
        print("\nTest 2: Submitting webhook alert...")
        webhook_payload = {
            "alert_id": 1042,
            "device_id": 4,
            "hostname": "core-sw-01.headquarters.net",
            "severity": "critical",
            "rule_name": "BGP Session Down",
            "msg": "BGP Session to peer 10.254.0.2 is down.",
            "timestamp": "2026-06-15T16:40:00Z"
        }
        webhook_res = client.post("/api/v1/alerts/webhook", json=webhook_payload)
        if webhook_res.status_code == 200 and webhook_res.json().get("status") == "enqueued":
            print(f"-> SUCCESS: Webhook enqueued alert #{webhook_res.json().get('alert_id')}")
        else:
            print(f"-> FAILURE: Webhook status {webhook_res.status_code}: {webhook_res.text}")
            success = False

        # Test 3: Run AI Analyzer API endpoint
        print("\nTest 3: Querying AI Copilot REST Endpoint...")
        ai_payload = {"query": "Analyze alert for border-router-01: Interface gigabitethernet0/0/0 down"}
        ai_res = client.post("/api/v1/ai/query", json=ai_payload)
        if ai_res.status_code == 200:
            res_data = ai_res.json()
            if "possible_root_cause" in res_data:
                safe_cause = res_data['possible_root_cause'].encode('ascii', errors='replace').decode('ascii')
                print(f"-> SUCCESS: AI REST returned root cause: {safe_cause}")
            else:
                print(f"-> FAILURE: AI REST response data incomplete: {res_data}")
                success = False
        else:
            print(f"-> FAILURE: AI REST endpoint status {ai_res.status_code}: {ai_res.text}")
            success = False

        # Test 4: Verify Dashboard Static Files Mounting
        print("\nTest 4: Verifying Dashboard static routing...")
        root_res = client.get("/")
        css_res = client.get("/static/style.css")
        if root_res.status_code == 200 and css_res.status_code == 200:
            print("-> SUCCESS: Serve index.html and style.css correctly mounted!")
        else:
            print(f"-> FAILURE: Root status: {root_res.status_code}, CSS status: {css_res.status_code}")
            success = False

        # Test 5: Verify Settings GET/POST endpoints
        if token:
            print("\nTest 5: Verifying API Settings Configuration Management...")
            # 5.1 GET settings
            get_res = client.get("/api/v1/settings", headers=headers)
            if get_res.status_code == 200:
                settings_data = get_res.json()
                print(f"-> SUCCESS: Retrieved masked token: {settings_data['librenms_api_token_masked']}")
                
                # 5.2 POST updates
                update_payload = {
                    "librenms_api_url": settings_data["librenms_api_url"],
                    "librenms_api_token": settings_data["librenms_api_token_masked"],
                    "openai_api_key": settings_data["openai_api_key_masked"],
                    "gemini_api_key": settings_data["gemini_api_key_masked"],
                    "llm_provider": settings_data["llm_provider"],
                    "llm_model": "gpt-4o-mini-test"
                }
                post_res = client.post("/api/v1/settings", json=update_payload, headers=headers)
                if post_res.status_code == 200:
                    print("-> SUCCESS: Updated settings payload accepted!")
                    
                    # 5.3 GET verify update
                    verify_res = client.get("/api/v1/settings", headers=headers)
                    if verify_res.status_code == 200 and verify_res.json().get("llm_model") == "gpt-4o-mini-test":
                        print("-> SUCCESS: Settings correctly persisted & verified!")
                    else:
                        print(f"-> FAILURE: Update verification mismatch: {verify_res.text}")
                        success = False
                        
                    # 5.4 Restore settings to original model
                    restore_payload = update_payload.copy()
                    restore_payload["llm_model"] = settings_data["llm_model"]
                    client.post("/api/v1/settings", json=restore_payload, headers=headers)
                else:
                    print(f"-> FAILURE: Updating settings failed with code {post_res.status_code}: {post_res.text}")
                    success = False
            else:
                print(f"-> FAILURE: Retrieving settings failed with code {get_res.status_code}: {get_res.text}")
                success = False

    except Exception as e:
        print(f"\nExecution Error: {e}")
        success = False
    finally:
        print("\n=== Shutting down FastAPI Gateway Server ===")
        server_process.terminate()
        try:
            server_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server_process.kill()
            
    if success:
        print("\nALL SYSTEM TESTS PASSED SUCCESSFULLY!")
        sys.exit(0)
    else:
        print("\nSYSTEM TESTS FAILED.")
        sys.exit(1)

if __name__ == "__main__":
    run_tests()
