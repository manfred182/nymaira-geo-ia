import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from geoia.rag.engine import RAGEngine

engine = RAGEngine()
count = engine.vector_store.count()
print(f"Count: {count}")

result = engine.query("definicion de formacion catastral segun resolucion 1040", top_k=3)
print(f"Sources: {result['sources']}")
print(f"Chunks: {len(result['chunks'])}")
for i, c in enumerate(result['chunks']):
    print(f"--- Chunk {i} ({len(c)} chars) ---")
    print(c[:400])
    print()
