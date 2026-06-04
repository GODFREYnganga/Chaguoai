# RAG (Retrieval Augmented Generation) Setup for Contraception DSS

To ensure Gemini provides accurate medical advice based on the Kenya Ministry of Health guidelines, we use a RAG pipeline.

## 1. Data Ingestion
- **Source:** The official MoH/WHO family planning guidelines (e.g., Kenya National Family Planning Guideline 7th Edition 2025, WHO MEC 6th Edition).
- **Process:**
    1.  **Parsing:** Extract text from the PDFs.
    2.  **Chunking:** Split text into smaller chunks (approx. 500-1000 characters) with overlap.
    3.  **Embedding:** Generate vector embeddings for each chunk using the `text-embedding-004` model.

## 2. Vector Search (Vertex AI)
- **Database:** **Vertex AI Vector Search** (matching engine).
- **Index:** Create an index with the generated embeddings.
- **Querying:** 
    1.  When a user asks a question, generate an embedding for their query.
    2.  Perform a similarity search in the Vector Search index.
    3.  Retrieve the top 3-5 most relevant chunks.

## 3. Augmentation & Generation
- **Prompt Construction:**
    ```
    System: Use the following context to answer the user's question. If the answer isn't in the context, say "I don't know based on the official guidelines, please consult a doctor."
    Context: {Retrieved_Chunks}
    User: {Scrubbed_User_Query}
    ```
- **Execution:** Send the augmented prompt to Gemini Pro.
