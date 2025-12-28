"""
Embedding Server - FastAPI service for generating audio and text embeddings
"""
import os
import io
import logging
from typing import List, Optional
from contextlib import asynccontextmanager

import torch
import librosa
import numpy as np
from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from muq import MuQMuLan

# Configure logging
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Configuration from environment variables
DEVICE = os.getenv("DEVICE", "cpu")
MODEL_NAME = os.getenv("MODEL_NAME", "OpenMuQ/MuQ-MuLan-large")
MODEL_CACHE_DIR = os.getenv("MODEL_CACHE_DIR", "/models")
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8080"))

# Global model instance
model = None

# Pydantic models for request/response
class TextEmbedRequest(BaseModel):
    text: str

class TextBatchEmbedRequest(BaseModel):
    texts: List[str]

class EmbeddingResponse(BaseModel):
    embedding: List[float]
    dimension: int

class BatchEmbeddingResponse(BaseModel):
    embeddings: List[List[float]]
    dimension: int
    count: int

class HealthResponse(BaseModel):
    status: str
    model_loaded: bool
    device: str

class InfoResponse(BaseModel):
    model_name: str
    device: str
    embedding_dimension: int


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events"""
    global model
    
    # Startup: Load model
    logger.info(f"Loading MuLAN model: {MODEL_NAME}")
    logger.info(f"Using device: {DEVICE}")
    
    try:
        # Determine device
        if DEVICE == "auto":
            if torch.backends.mps.is_available():
                device = "mps"
            elif torch.cuda.is_available():
                device = "cuda"
            else:
                device = "cpu"
        else:
            device = DEVICE
        
        # Load model
        model = MuQMuLan.from_pretrained(MODEL_NAME, cache_dir=MODEL_CACHE_DIR)
        model = model.to(device).eval()
        logger.info(f"✓ Model loaded successfully on {device}")
        
    except Exception as e:
        logger.error(f"Failed to load model: {e}")
        raise
    
    yield
    
    # Shutdown
    logger.info("Shutting down embedding server")


# Initialize FastAPI app
app = FastAPI(
    title="MusicCLIP Embedding Server",
    description="Generate audio and text embeddings using MuQ-MuLan model",
    version="1.0.0",
    lifespan=lifespan
)


@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint"""
    return HealthResponse(
        status="healthy" if model is not None else "unhealthy",
        model_loaded=model is not None,
        device=str(next(model.parameters()).device) if model is not None else "unknown"
    )


@app.get("/info", response_model=InfoResponse)
async def get_info():
    """Get model information"""
    if model is None:
        raise HTTPException(status_code=503, detail="Model not loaded")
    
    # Get embedding dimension by running a test
    with torch.no_grad():
        test_embed = model(texts=["test"])
        embed_dim = test_embed.shape[-1]
    
    return InfoResponse(
        model_name=MODEL_NAME,
        device=str(next(model.parameters()).device),
        embedding_dimension=embed_dim
    )


@app.post("/embed/text", response_model=EmbeddingResponse)
async def embed_text(request: TextEmbedRequest):
    """Generate embedding from text query"""
    if model is None:
        raise HTTPException(status_code=503, detail="Model not loaded")
    
    try:
        logger.info(f"Generating text embedding for: {request.text[:50]}...")
        
        with torch.no_grad():
            text_embeds = model(texts=[request.text])
        
        # Convert to list
        embedding_list = text_embeds.cpu().numpy().flatten().tolist()
        
        return EmbeddingResponse(
            embedding=embedding_list,
            dimension=len(embedding_list)
        )
    
    except Exception as e:
        logger.error(f"Error generating text embedding: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/embed/text/batch", response_model=BatchEmbeddingResponse)
async def embed_text_batch(request: TextBatchEmbedRequest):
    """Generate embeddings from multiple text queries"""
    if model is None:
        raise HTTPException(status_code=503, detail="Model not loaded")
    
    try:
        logger.info(f"Generating {len(request.texts)} text embeddings")
        
        with torch.no_grad():
            text_embeds = model(texts=request.texts)
        
        # Convert to list of lists
        embeddings_array = text_embeds.cpu().numpy()
        embeddings_list = [emb.tolist() for emb in embeddings_array]
        
        return BatchEmbeddingResponse(
            embeddings=embeddings_list,
            dimension=embeddings_array.shape[-1],
            count=len(embeddings_list)
        )
    
    except Exception as e:
        logger.error(f"Error generating text embeddings: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/embed/audio", response_model=EmbeddingResponse)
async def embed_audio(
    file: UploadFile = File(..., description="Audio file (WAV, MP3, etc.)")
):
    """Generate embedding from uploaded audio file"""
    if model is None:
        raise HTTPException(status_code=503, detail="Model not loaded")
    
    try:
        logger.info(f"Generating audio embedding for: {file.filename}")
        
        # Read audio file
        audio_bytes = await file.read()
        audio_buffer = io.BytesIO(audio_bytes)
        
        # Load audio with librosa (supports multiple formats)
        wav, sr = librosa.load(audio_buffer, sr=24000)
        
        # Convert to tensor
        device = next(model.parameters()).device
        wavs = torch.tensor(wav).unsqueeze(0).to(device)
        
        # Generate embedding
        with torch.no_grad():
            audio_embeds = model(wavs=wavs)
        
        # Convert to list
        embedding_list = audio_embeds.cpu().numpy().flatten().tolist()
        
        return EmbeddingResponse(
            embedding=embedding_list,
            dimension=len(embedding_list)
        )
    
    except Exception as e:
        logger.error(f"Error generating audio embedding: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "service": "MusicCLIP Embedding Server",
        "version": "1.0.0",
        "endpoints": {
            "health": "/health",
            "info": "/info",
            "embed_text": "POST /embed/text",
            "embed_text_batch": "POST /embed/text/batch",
            "embed_audio": "POST /embed/audio"
        }
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=HOST, port=PORT)
