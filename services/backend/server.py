"""
Musiclip Server - FastAPI server for querying the Musiclip database
"""
import os
import logging
import requests
import chromadb
from chromadb.config import Settings
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Dict, Any
import uvicorn

# Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Configuration
CHROMA_HOST = os.environ['CHROMA_HOST']  # e.g. api.trychroma.com
CHROMA_API_KEY = os.environ['CHROMA_API_KEY']
CHROMA_TENANT = os.getenv('CHROMA_TENANT', 'default_tenant')
CHROMA_DATABASE = os.getenv('CHROMA_DATABASE', 'default_database')
EMBEDDING_SERVER_URL = os.environ['EMBEDDING_SERVER_URL']
S3_BUCKET_URL = os.environ['S3_BUCKET_URL']  # e.g. https://my-bucket.s3.us-east-1.amazonaws.com
PORT = int(os.getenv('PORT', '8081'))

# Global variables for ChromaDB client and collection
client = None
collection = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Connect to Chroma Cloud on startup"""
    global client, collection
    
    logger.info(f"Connecting to Chroma Cloud at {CHROMA_HOST}...")
    client = chromadb.HttpClient(
        host=CHROMA_HOST,
        ssl=True,
        headers={"x-chroma-token": CHROMA_API_KEY},
        settings=Settings(
            chroma_client_auth_provider="chromadb.auth.token_authn.TokenAuthClientProvider",
            chroma_client_auth_credentials=CHROMA_API_KEY,
            chroma_auth_token_transport_header="x-chroma-token",
        ),
        tenant=CHROMA_TENANT,
        database=CHROMA_DATABASE,
    )
    
    collection = client.get_collection(name="music_embeddings")
    logger.info(f"Connected! Collection has {collection.count()} embeddings")
    
    yield

# Initialize FastAPI app with lifespan
app = FastAPI(
    title="Musiclip Server",
    description="API for querying music embeddings by text or similarity",
    version="1.0.0",
    lifespan=lifespan
)

# Add CORS middleware to allow frontend requests
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, set to your frontend domain (e.g., ["https://yourdomain.com"])
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Request/Response models
class TextQueryRequest(BaseModel):
    query: str
    top_k: int = 10

class SongIdQueryRequest(BaseModel):
    song_id: str
    top_k: int = 10

class QueryResult(BaseModel):
    id: str
    distance: float
    cosine_similarity: float
    metadata: Dict[str, Any]
    audio_url: str

class QueryResponse(BaseModel):
    results: List[QueryResult]
    query_type: str

def get_text_embedding(query_text):
    """Get text embedding from the embedding server."""
    try:
        response = requests.post(
            f"{EMBEDDING_SERVER_URL}/embed/text",
            json={"text": query_text},
            timeout=30
        )
        response.raise_for_status()
        return response.json()['embedding']
    except requests.exceptions.RequestException as e:
        raise Exception(f"Failed to get embedding from server: {e}")

def query_music(query_text, top_k=5):
    """Query the music database with a text string."""
    # Get text embedding from embedding server
    query_embedding = get_text_embedding(query_text)
    
    # Query ChromaDB for nearest neighbors
    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=top_k
    )
    
    return results

def query_music_by_id(song_id, top_k=5):
    """Query the music database using another song's ID."""
    # Get the embedding for the specified song ID
    result = collection.get(
        ids=[song_id],
        include=['embeddings']
    )
    
    if not result['ids'] or len(result['embeddings']) == 0:
        raise ValueError(f"Song ID '{song_id}' not found in database.")
    
    # Use the song's embedding to find nearest neighbors
    query_embedding = result['embeddings'][0]
    
    # Query ChromaDB for nearest neighbors
    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=top_k + 1  # +1 because the song itself will be in results
    )
    
    # Filter out the query song itself from results
    filtered_results = {
        'ids': [[]],
        'distances': [[]],
        'metadatas': [[]]
    }
    
    for i, result_id in enumerate(results['ids'][0]):
        if result_id != song_id:
            filtered_results['ids'][0].append(result_id)
            filtered_results['distances'][0].append(results['distances'][0][i])
            filtered_results['metadatas'][0].append(results['metadatas'][0][i])
    
    # Trim to requested top_k
    filtered_results['ids'][0] = filtered_results['ids'][0][:top_k]
    filtered_results['distances'][0] = filtered_results['distances'][0][:top_k]
    filtered_results['metadatas'][0] = filtered_results['metadatas'][0][:top_k]
    
    return filtered_results

def get_audio_url(song_id: str) -> str:
    """Generate S3 URL for a song's audio file."""
    return f"{S3_BUCKET_URL}/{song_id}.wav"

def format_results(raw_results) -> List[QueryResult]:
    """Format ChromaDB results into QueryResult objects."""
    formatted = []
    
    if not raw_results['ids'] or not raw_results['ids'][0]:
        return formatted
    
    for file_id, distance, metadata in zip(
        raw_results['ids'][0],
        raw_results['distances'][0],
        raw_results['metadatas'][0]
    ):
        formatted.append(QueryResult(
            id=file_id,
            distance=distance,
            cosine_similarity=1 - distance,
            metadata=metadata,
            audio_url=get_audio_url(file_id)
        ))
    
    return formatted

# API Endpoints
@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "chromadb_connected": collection is not None,
        "collection_size": collection.count() if collection else 0
    }

@app.post("/query/text", response_model=QueryResponse)
async def query_by_text(request: TextQueryRequest):
    """Query music by text description."""
    try:
        results = query_music(request.query, top_k=request.top_k)
        formatted_results = format_results(results)
        
        return QueryResponse(
            results=formatted_results,
            query_type="text"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/query/similar", response_model=QueryResponse)
async def query_by_song_id(request: SongIdQueryRequest):
    """Query music similar to a given song ID."""
    try:
        results = query_music_by_id(request.song_id, top_k=request.top_k)
        formatted_results = format_results(results)
        
        return QueryResponse(
            results=formatted_results,
            query_type="similarity"
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/collection/info")
async def collection_info():
    """Get information about the music collection."""
    try:
        return {
            "name": "music_embeddings",
            "count": collection.count(),
            "metadata": collection.metadata
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    logger.info(f"Starting server on port {PORT}")
    uvicorn.run(app, host="0.0.0.0", port=PORT)
