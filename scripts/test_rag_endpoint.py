import subprocess, time, sys, os, signal, json, urllib.request
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

proc = subprocess.Popen(
    [sys.executable, "-m", "uvicorn", "geoia.api.main:app",
     "--host", "0.0.0.0", "--port", "8011", "--workers", "1", "--log-level", "warning"],
    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    env={**os.environ, "PYTHONPATH": os.path.dirname(os.path.dirname(os.path.abspath(__file__)))}
)

try:
    start = time.time()
    ready = False
    for i in range(180):
        time.sleep(2)
        try:
            r = urllib.request.urlopen("http://localhost:8011/health", timeout=5)
            if r.status == 200:
                ready = True
                elapsed = time.time() - start
                print(f"Server ready after {elapsed:.0f}s", flush=True)
                break
        except Exception:
            continue
    
    if not ready:
        print("Server failed to start in 360s", flush=True)
        proc.terminate()
        sys.exit(1)
    
    payload = json.dumps({"query": "definicion de formacion catastral segun resolucion 1040", "top_k": 5}).encode()
    req = urllib.request.Request(
        "http://localhost:8011/api/v1/rag/query",
        data=payload,
        headers={"Content-Type": "application/json"}
    )
    t0 = time.time()
    r = urllib.request.urlopen(req, timeout=180)
    t1 = time.time()
    result = json.loads(r.read())
    print(f"RAG query took {t1-t0:.1f}s", flush=True)
    print(f"Sources: {result.get('sources', [])}", flush=True)
    print(f"Response length: {len(result.get('response', ''))}", flush=True)
    print(f"Response preview: {result.get('response', '')[:200]}", flush=True)
    print("SUCCESS", flush=True)
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
