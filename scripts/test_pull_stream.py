#!/usr/bin/env python3
"""Test Ollama pull stream directly"""
import asyncio
import httpx
import json

async def test_pull_stream(model: str = "phi3:mini"):
    print(f"Testing pull stream for {model}...")
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            async with client.stream(
                "POST",
                "http://localhost:11434/api/pull",
                json={"name": model, "stream": True}
            ) as response:
                print(f"Status: {response.status_code}")
                if response.status_code != 200:
                    text = await response.aread()
                    print(f"Error: {text.decode()[:500]}")
                    return
                
                async for line in response.aiter_lines():
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                        status = data.get("status", "")
                        completed = data.get("completed", 0)
                        total = data.get("total", 0)
                        
                        if total > 0:
                            pct = round((completed / total) * 100, 1)
                            mb = completed / 1024 / 1024
                            total_mb = total / 1024 / 1024
                            print(f"[{pct:>5.1f}%] {status} | {mb:.1f}MB / {total_mb:.1f}MB")
                        else:
                            print(f"       {status}")
                            
                        if data.get("status") == "success":
                            print("✅ Download complete!")
                            break
                    except Exception as e:
                        print(f"Parse error: {e} - line: {line[:100]}")
                        
    except httpx.ConnectError:
        print("❌ Cannot connect to Ollama. Make sure 'ollama serve' is running.")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(test_pull_stream("phi3:mini"))