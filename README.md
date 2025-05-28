# RAG

# step 1 data ingestion and indexing (building you knowledge base) 
# step1.1 load document
docs = [] # a list of potential relevant documents
raw_docs = load_documents(docs)
# step 1.2 split the docs into chunks
chunks = split_documents(raw_docs, chunk_size, chunk_overlap)
# step 1.3 create embedding for your chunks ( capture semitic meanings)
embedding_model= OpenAIenbedding()
embeddings = create_embeddings(chunks, embedding_model) # some embedding models, 
# step 1.4 store chunks, embedding in a vector store (knowledge base or index)
vector_store = store_in_vector_store(chunks, embeddings) # using FAISS etc method

# step 2 : retrieval at query time, happens every time use ask a question
