import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["PYTHONPATH"] = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

from geoia.rag.engine import RAGEngine

engine = RAGEngine()
print(f"Vector store exists: {engine.vector_store is not None}")
if engine.vector_store:
    try:
        count = engine.vector_store.count()
        print(f"Collection count: {count}")
        if count > 0:
            result = engine.vector_store.query(
                query_texts=["definicion de formacion catastral"],
                n_results=3,
                include=["documents", "metadatas", "distances"],
            )
            print(f"Docs: {len(result['documents'][0]) if result['documents'] else 0}")
            for i, (doc, meta) in enumerate(zip(result['documents'][0], result['metadatas'][0])):
                print(f"Chunk {i}: source={meta.get('source')}, len={len(doc)}")
                print(f"  Preview: {doc[:100]}...")
    except Exception as e:
        print(f"Error: {e}")

result = engine.query("definicion de formacion catastral segun resolucion 1040", top_k=5)
print(f"\nQuery sources: {result['sources']}")
print(f"Number of chunks: {len(result['chunks'])}")
if result['chunks']:
    print(f"First chunk preview: {result['chunks'][0][:200]}")
