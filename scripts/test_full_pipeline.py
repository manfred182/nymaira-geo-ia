import subprocess, time, sys, os, json, urllib.request
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

proc = subprocess.Popen(
    [sys.executable, "-m", "uvicorn", "geoia.api.main:app",
     "--host", "0.0.0.0", "--port", "8012", "--workers", "1", "--log-level", "warning"],
    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    env={**os.environ, "PYTHONPATH": os.path.dirname(os.path.dirname(os.path.abspath(__file__)))}
)

try:
    start = time.time()
    for i in range(120):
        time.sleep(2)
        try:
            r = urllib.request.urlopen("http://localhost:8012/health", timeout=5)
            if r.status == 200:
                elapsed = time.time() - start
                print(f"Server ready after {elapsed:.0f}s", flush=True)
                break
        except Exception:
            continue
    else:
        print("Server failed to start", flush=True)
        sys.exit(1)

    # Test RAG endpoint
    print("\n=== RAG endpoint ===", flush=True)
    payload = json.dumps({"query": "definicion de formacion catastral segun resolucion 1040", "top_k": 5}).encode()
    req = urllib.request.Request(
        "http://localhost:8012/api/v1/rag/query",
        data=payload,
        headers={"Content-Type": "application/json"}
    )
    t0 = time.time()
    r = urllib.request.urlopen(req, timeout=180)
    t1 = time.time()
    result = json.loads(r.read())
    print(f"RAG query took {t1-t0:.1f}s", flush=True)
    print(f"Sources: {result.get('sources', [])}", flush=True)

    # Test chatbot endpoint
    print("\n=== Chatbot endpoint ===", flush=True)
    payload = json.dumps({"message": "dame la definicion completa de formacion catastral segun la resolucion 1040 de 2023", "session_id": "test_001"}).encode()
    req = urllib.request.Request(
        "http://localhost:8012/api/v1/chatbot/chat",
        data=payload,
        headers={"Content-Type": "application/json"}
    )
    t0 = time.time()
    r = urllib.request.urlopen(req, timeout=300)
    result = json.loads(r.read())
    t1 = time.time()
    print(f"Chatbot took {t1-t0:.1f}s", flush=True)
    response = result.get("response", "")
    sources = result.get("sources", result.get("fuentes", []))
    print(f"Response length: {len(response)} chars", flush=True)
    print(f"Sources: {sources}", flush=True)
    print(f"Response preview: {response[:500]}", flush=True)
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
