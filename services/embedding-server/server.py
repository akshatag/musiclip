"""
Embedding Server - FastAPI service for generating audio and text embeddings using MuLan.

Deploy with: modal deploy server.py
Serve locally with: modal serve server.py
"""
import io
import logging
from typing import List
import modal

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Configuration
MODEL_NAME = "OpenMuQ/MuQ-MuLan-large"
MODEL_CACHE_DIR = "/models"

# Define Modal container image with all dependencies
container_image = (
    modal.Image.debian_slim(python_version="3.10")
    .apt_install(
        "libsndfile1",
        "ffmpeg",
        "git",
    )
    .pip_install(
        "fastapi[standard]==0.109.0",
        "pydantic==2.5.3",
        "torch>=2.2.0",
        "torchaudio>=2.2.0",
        "librosa==0.10.1",
        "numpy==1.24.3",
        "python-multipart==0.0.6",
    )
    .pip_install("git+https://github.com/tencent-ailab/MuQ.git")
)

# Create Modal app and volume for model caching
app = modal.App("musicclip-embedding-server", image=container_image)
model_cache_vol = modal.Volume.from_name("muq-model-cache", create_if_missing=True)

@app.cls(
    volumes={MODEL_CACHE_DIR: model_cache_vol},
    gpu="T4",
    scaledown_window=300,
)
@modal.concurrent(max_inputs=10)
class EmbeddingService:
    """
    Modal class that wraps the FastAPI app.
    Uses @modal.enter() to load the model once per container lifecycle.
    """
    
    @modal.enter()
    def load_model(self):
        """Load the MuLan model once when the container starts."""
        import torch
        from muq import MuQMuLan
        
        # Configure logging inside container
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )
        self.logger = logging.getLogger(__name__)
        
        self.logger.info(f"Loading MuLAN model: {MODEL_NAME}")
        
        # Determine device
        if torch.cuda.is_available():
            self.device = "cuda"
        else:
            self.device = "cpu"
        
        # Load model - this only happens once per container
        self.model = MuQMuLan.from_pretrained(MODEL_NAME, cache_dir=MODEL_CACHE_DIR)
        self.model = self.model.to(self.device).eval()
        
        # Commit the volume to persist cached model weights
        model_cache_vol.commit()
        
        self.logger.info(f"✓ Model loaded successfully on {self.device}")
    
    @modal.asgi_app()
    def serve(self):
        """Return the FastAPI app with model injected."""
        import torch
        import librosa
        from fastapi import FastAPI, File, UploadFile, HTTPException
        from pydantic import BaseModel
        
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
        
        # Create FastAPI app
        web_app = FastAPI(
            title="MusicCLIP Embedding Server",
            description="Generate audio and text embeddings using MuQ-MuLan model",
            version="1.0.0",
        )
        
        # Capture self for use in routes
        service = self
        
        @web_app.get("/health", response_model=HealthResponse)
        async def health_check():
            """Health check endpoint"""
            return HealthResponse(
                status="healthy",
                model_loaded=True,
                device=service.device
            )
        
        @web_app.get("/info", response_model=InfoResponse)
        async def get_info():
            """Get model information"""
            with torch.no_grad():
                test_embed = service.model(texts=["test"])
                embed_dim = test_embed.shape[-1]
            
            return InfoResponse(
                model_name=MODEL_NAME,
                device=service.device,
                embedding_dimension=embed_dim
            )
        
        @web_app.post("/embed/text", response_model=EmbeddingResponse)
        async def embed_text(request: TextEmbedRequest):
            """Generate embedding from text query"""
            try:
                service.logger.info(f"Generating text embedding for: {request.text[:50]}...")
                
                with torch.no_grad():
                    text_embeds = service.model(texts=[request.text])
                
                embedding_list = text_embeds.cpu().numpy().flatten().tolist()
                
                return EmbeddingResponse(
                    embedding=embedding_list,
                    dimension=len(embedding_list)
                )
            
            except Exception as e:
                service.logger.error(f"Error generating text embedding: {e}")
                raise HTTPException(status_code=500, detail=str(e))
        
        @web_app.post("/embed/text/batch", response_model=BatchEmbeddingResponse)
        async def embed_text_batch(request: TextBatchEmbedRequest):
            """Generate embeddings from multiple text queries"""
            try:
                service.logger.info(f"Generating {len(request.texts)} text embeddings")
                
                with torch.no_grad():
                    text_embeds = service.model(texts=request.texts)
                
                embeddings_array = text_embeds.cpu().numpy()
                embeddings_list = [emb.tolist() for emb in embeddings_array]
                
                return BatchEmbeddingResponse(
                    embeddings=embeddings_list,
                    dimension=embeddings_array.shape[-1],
                    count=len(embeddings_list)
                )
            
            except Exception as e:
                service.logger.error(f"Error generating text embeddings: {e}")
                raise HTTPException(status_code=500, detail=str(e))
        
        @web_app.post("/embed/audio", response_model=EmbeddingResponse)
        async def embed_audio(
            file: UploadFile = File(..., description="Audio file (WAV, MP3, etc.)")
        ):
            """Generate embedding from uploaded audio file"""
            try:
                service.logger.info(f"Generating audio embedding for: {file.filename}")
                
                audio_bytes = await file.read()
                audio_buffer = io.BytesIO(audio_bytes)
                wav, sr = librosa.load(audio_buffer, sr=24000)
                
                wavs = torch.tensor(wav).unsqueeze(0).to(service.device)
                
                with torch.no_grad():
                    audio_embeds = service.model(wavs=wavs)
                
                embedding_list = audio_embeds.cpu().numpy().flatten().tolist()
                
                return EmbeddingResponse(
                    embedding=embedding_list,
                    dimension=len(embedding_list)
                )
            
            except Exception as e:
                service.logger.error(f"Error generating audio embedding: {e}")
                raise HTTPException(status_code=500, detail=str(e))
        
        @web_app.get("/")
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
        
        return web_app
