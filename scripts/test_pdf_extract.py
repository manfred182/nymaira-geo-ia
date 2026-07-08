"""Test PDF extraction - quick check."""
import sys, os, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
os.chdir(str(Path(__file__).parent.parent))  # Ensure working dir is project root

pdf_path = Path(__file__).parent.parent / "data" / "documents" / "resolucion_1040_de_2023.pdf"
print(f"PDF exists: {pdf_path.exists()}, size: {pdf_path.stat().st_size / 1024 / 1024:.1f} MB")

# Just test PyMuPDF extraction
import fitz
doc = fitz.open(str(pdf_path))
print(f"Pages: {doc.page_count}")

# Extract first 3 pages
text_parts = []
for i in range(min(3, doc.page_count)):
    t = doc[i].get_text()
    text_parts.append(t)
    print(f"Page {i+1}: {len(t)} chars")

# Extract all pages
start = time.time()
all_text = []
for page in doc:
    t = page.get_text()
    if t.strip():
        all_text.append(t)
full_text = "\n\n".join(all_text)
elapsed = time.time() - start
print(f"\nFull extraction: {len(full_text)} chars in {elapsed:.2f}s")
print(f"Pages with text: {len(all_text)}")

# Test chunking
from langchain_text_splitters import RecursiveCharacterTextSplitter
splitter = RecursiveCharacterTextSplitter(
    chunk_size=1500,
    chunk_overlap=200,
    length_function=len,
    separators=["\n\n", "\n", ". ", "; "],
)
chunks = splitter.split_text(full_text)
print(f"Chunks: {len(chunks)}")
print(f"First chunk: {chunks[0][:200]}...")
print(f"Last chunk: {chunks[-1][:200]}...")

# Embed first 5 chunks only to test speed
from sentence_transformers import SentenceTransformer
model = SentenceTransformer(str(Path(__file__).parent.parent / "models" / "sentence-transformers" / "all-MiniLM-L6-v2"))
start = time.time()
emb = model.encode(chunks[:5])
elapsed = time.time() - start
print(f"\n5 embeddings: {elapsed:.2f}s ({elapsed/5*1000:.0f}ms each)")
print(f"Estimated total: {elapsed/5*len(chunks)/60:.0f} minutes for all {len(chunks)} chunks")
