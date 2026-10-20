{{ config(post_hook="create index if not exists documents_embedding_idx on {{ this }} using hnsw (embedding vector_cosine_ops)") }}
-- Menu and policy chunks for retrieval; embedding is null when the embedding model was unavailable at load time
select id, source, heading, content, embedding
from {{ source('raw', 'documents') }}
