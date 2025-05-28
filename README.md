# RAG

# step 1 data ingestion and indexing (building you knowledge base) 
## step1.1 load document
``` python
docs = [] # a list of potential relevant documents
raw_docs = load_documents(docs)
```

## step 1.2 split the docs into chunks
```python
chunks = split_documents(raw_docs, chunk_size, chunk_overlap)
```
## step 1.3 create embedding for your chunks ( capture semitic meanings)
```python
embedding_model= OpenAIenbedding()
embeddings = create_embeddings(chunks, embedding_model) # some embedding models,
```
## step 1.4 store chunks, embedding in a vector store (knowledge base or index)
```python
vector_store = store_in_vector_store(chunks, embeddings) # using FAISS etc method
```
# step 2 : retrieval at query time, happens every time use ask a question

## get user query
user_query = “ tell me…?”
## get user query_embedding
```python
query_embedding = embed_query(user_query, embedding_model)
```
## find the top-k most similar chunks to the query_embedding
```python
revelent_chunks = retrieve_relevent_chunks (query_embedding, vector_store, k)
```


