import subprocess, time, sys, os, json, urllib.request
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

proc = subprocess.Popen(
    [sys.executable, "-m", "uvicorn", "geoia.api.main:app",
     "--host", "0.0.0.0", "--port", "8013", "--workers", "1", "--log-level", "warning"],
    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    env={**os.environ, "PYTHONPATH": os.path.dirname(os.path.dirname(os.path.abspath(__file__)))}
)

try:
    for i in range(120):
        time.sleep(2)
        try:
            r = urllib.request.urlopen("http://localhost:8013/health", timeout=5)
            if r.status == 200:
                print("Server ready", flush=True)
                break
        except Exception:
            continue
    else:
        print("Server failed to start", flush=True)
        sys.exit(1)

    # Test chatbot with RAG + web
    payload = json.dumps({"message": "dame la definicion completa de formacion catastral segun la resolucion 1040 de 2023 incluyendo sus fundamentos legales", "session_id": "test_002"}).encode()
    req = urllib.request.Request(
        "http://localhost:8013/api/v1/chatbot/chat",
        data=payload,
        headers={"Content-Type": "application/json"}
    )
    t0 = time.time()
    r = urllib.request.urlopen(req, timeout=300)
    result = json.loads(r.read())
    t1 = time.time()
    print(f"Chatbot took {t1-t0:.1f}s", flush=True)
    response = result.get("response", "")
    print(f"Response length: {len(response)} chars", flush=True)
    print("=" * 60, flush=True)
    print(response, flush=True)
    print("=" * 60, flush=True)
    print("\nSUCCESS", flush=True)
except Exception as e:
    print(f"ERROR: {e}", flush=True)
    import traceback
    traceback.print_exc()
finally:
    proc.terminate()
    time.sleep(2)
    try:
        proc.kill()
    except:
        pass
