"""
Query Server - FastAPI server for querying the music database

Uses:
- ChromaDB HTTP client (instead of local persistent client)
- Embedding-server API (instead of loading model locally)

Can also run in interactive shell mode with --interactive flag
"""
import os
import sys
import requests
import chromadb
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
import uvicorn

# Configuration from environment variables
CHROMA_HOST = os.getenv('CHROMA_HOST', 'localhost')
CHROMA_PORT = int(os.getenv('CHROMA_PORT', '8000'))
EMBEDDING_SERVER_URL = os.getenv('EMBEDDING_SERVER_URL', 'http://localhost:8080')
HOST = os.getenv('HOST', '0.0.0.0')
PORT = int(os.getenv('PORT', '8081'))

# MinIO configuration
MINIO_ENDPOINT = os.getenv('MINIO_ENDPOINT', 'localhost:9000')  # Internal endpoint for API calls
MINIO_PUBLIC_ENDPOINT = os.getenv('MINIO_PUBLIC_ENDPOINT', 'localhost:9001')  # Public endpoint for browser UI
MINIO_BUCKET = os.getenv('MINIO_BUCKET', 'music-clips')
MINIO_SECURE = os.getenv('MINIO_SECURE', 'false').lower() == 'true'

# Construct MinIO base URL for direct download (using API endpoint on port 9000)
MINIO_PROTOCOL = 'https' if MINIO_SECURE else 'http'
# Use port 9000 for direct API access, not 9001 (console UI)
MINIO_DOWNLOAD_ENDPOINT = os.getenv('MINIO_DOWNLOAD_ENDPOINT', 'localhost:9000')
MINIO_BASE_URL = f"{MINIO_PROTOCOL}://{MINIO_DOWNLOAD_ENDPOINT}/{MINIO_BUCKET}"

# Global variables for ChromaDB client and collection
client = None
collection = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events"""
    global client, collection
    
    # Startup: Connect to ChromaDB
    print(f"Connecting to ChromaDB at {CHROMA_HOST}:{CHROMA_PORT}...")
    client = chromadb.HttpClient(host=CHROMA_HOST, port=CHROMA_PORT)
    
    try:
        collection = client.get_collection(name="music_embeddings")
        count = collection.count()
        print(f"Connected to ChromaDB!")
        print(f"Collection size: {count} embeddings")
    except Exception as e:
        print(f"Error connecting to ChromaDB: {e}")
        raise
    
    yield
    
    # Shutdown: Cleanup if needed
    print("Shutting down query server...")

# Initialize FastAPI app with lifespan
app = FastAPI(
    title="MusicLip Query API",
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
    audio_url: str  # MinIO URL for the audio file

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

def get_minio_url(song_id: str) -> str:
    """Generate MinIO browser URL for a song's WAV file."""
    return f"{MINIO_BASE_URL}/{song_id}.wav"

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
            audio_url=get_minio_url(file_id)
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

def display_results(results):
    """Display query results in a formatted way."""
    if not results['ids'] or not results['ids'][0]:
        print("No results found.")
        return
    
    print("\n=== Top Results ===")
    for i, (file_id, distance, metadata) in enumerate(zip(
        results['ids'][0],
        results['distances'][0],
        results['metadatas'][0]
    ), 1):
        cosine_similarity = 1 - distance
        
        # Extract metadata
        song_name = metadata.get('song_name', 'Unknown')
        artist_name = metadata.get('artist_name', 'Unknown')
        album_name = metadata.get('album_name', 'Unknown')
        genres = metadata.get('genres', 'N/A')
        
        # Generate MinIO URL
        audio_url = get_minio_url(file_id)
        
        print(f"{i}. {song_name} - {artist_name}")
        print(f"   Album: {album_name}")
        print(f"   Genres: {genres}")
        print(f"   Cosine Similarity: {cosine_similarity:.4f}")
        print(f"   Audio URL: {audio_url}")
        print()

def interactive_shell():
    """Launch an interactive query shell."""
    print("=" * 60)
    print("Music Query Interactive Shell")
    print("=" * 60)
    print("Enter a text query to search for similar music.")
    print("Or use [song_id] to find songs similar to a specific song.")
    print("Type 'quit' or 'exit' to exit.\n")
    
    while True:
        try:
            query = input("Query: ").strip()
            
            if query.lower() in ['quit', 'exit', 'q']:
                print("Goodbye!")
                break
            
            if not query:
                print("Please enter a valid query.\n")
                continue
            
            # Check if query is an ID (surrounded by brackets)
            if query.startswith('[') and query.endswith(']'):
                song_id = query[1:-1].strip()
                print(f"Searching for songs similar to ID: {song_id}")
                results = query_music_by_id(song_id, top_k=10)
            else:
                # Perform text-based query
                results = query_music(query, top_k=10)
            
            display_results(results)
            
        except KeyboardInterrupt:
            print("\n\nGoodbye!")
            break
        except Exception as e:
            print(f"Error: {e}\n")

if __name__ == "__main__":
    # Check if running in interactive mode
    if len(sys.argv) > 1 and sys.argv[1] == "--interactive":
        # Initialize ChromaDB for interactive mode
        print(f"Connecting to ChromaDB at {CHROMA_HOST}:{CHROMA_PORT}...")
        client = chromadb.HttpClient(host=CHROMA_HOST, port=CHROMA_PORT)
        
        try:
            collection = client.get_collection(name="music_embeddings")
            print(f"Connected to ChromaDB!")
            print(f"Collection size: {collection.count()} embeddings\n")
        except Exception as e:
            print(f"Error connecting to ChromaDB: {e}")
            sys.exit(1)
        
        interactive_shell()
    else:
        # Run FastAPI server
        print(f"Starting Query API server on {HOST}:{PORT}")
        uvicorn.run(app, host=HOST, port=PORT)
