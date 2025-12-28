# MusicCLIP - Music Similarity Search with Docker

A production-ready music similarity search system using MuLAN embeddings, built with a microservices architecture.

## Architecture

This project is organized into 6 separate services that can be deployed independently:

### 1. **MinIO** - Object Storage
- **Local**: MinIO container
- **Production**: AWS S3
- **Purpose**: Store WAV audio files
- **Access**: 
  - API: `http://localhost:9000`
  - Console UI: `http://localhost:9001`

### 2. **ChromaDB** - Vector Database
- **Local**: ChromaDB container
- **Production**: Chroma Cloud
- **Purpose**: Store embeddings and metadata
- **Access**: `http://localhost:8000`

### 3. **Embedding Server** - ML Service
- **Local**: Python FastAPI container
- **Production**: Modal/RunPod serverless GPU
- **Purpose**: Generate embeddings from audio/text
- **Access**: `http://localhost:8080`
- **Endpoints**:
  - `POST /embed/audio` - Generate audio embedding
  - `POST /embed/text` - Generate text embedding
  - `GET /health` - Health check
  - `GET /info` - Model information

### 4. **Catalogue Builder** - Data Pipeline
- **Local**: Python script (on-demand)
- **Production**: Cron job / scheduled task
- **Purpose**: Fetch music from Apple Music → process → store
- **Workflow**:
  1. Fetch playlist from Apple Music API
  2. Download preview audio
  3. Upload to MinIO
  4. Generate embedding via embedding-server
  5. Store in ChromaDB

### 5. **Query Client** - Query API
- **Local**: Python FastAPI container
- **Production**: Cloud Run / ECS / Lambda
- **Purpose**: REST API for querying music by text or similarity
- **Access**: `http://localhost:8081`
- **Endpoints**:
  - `POST /query/text` - Search by text description
  - `POST /query/similar` - Find similar songs by ID
  - `GET /health` - Health check

### 6. **Frontend** - Web UI
- **Local**: Next.js container
- **Production**: Vercel / CloudFront
- **Purpose**: User-facing web interface for music search
- **Access**: `http://localhost:3000`
- **Features**:
  - Text-based music search
  - Audio preview playback
  - Modern, responsive UI

## Directory Structure

```
musiclip/
├── docker-compose.yml              # Orchestrates all services
├── .env.example                    # Environment variables template
├── .dockerignore                   # Docker ignore patterns
├── services/
│   ├── embedding-server/           # ML service for embeddings
│   │   ├── Dockerfile
│   │   ├── requirements.txt
│   │   └── server.py
│   ├── catalogue-builder/          # Data pipeline script
│   │   ├── Dockerfile
│   │   ├── requirements.txt
│   │   └── build_catalogue.py
│   ├── query-client/               # Query API server
│   │   ├── Dockerfile
│   │   ├── requirements.txt
│   │   └── query.py
│   └── frontend/                   # Web UI
│       ├── Dockerfile
│       ├── package.json
│       ├── app/
│       │   ├── layout.tsx
│       │   ├── page.tsx
│       │   └── globals.css
│       └── README.md
├── data/                           # Mounted volumes
├── chroma_db/                      # Existing ChromaDB data (to migrate)
├── clips_wav/                      # Existing WAV files (to migrate)
└── README.md
```

## Getting Started

### Prerequisites

- Docker Desktop installed
- Docker Compose v2.0+
- Apple Music API credentials (for catalogue builder)

### Setup

1. **Clone and navigate to the project**:
   ```bash
   cd /Users/akshat/Documents/projects/musiclip
   ```

2. **Create environment file**:
   ```bash
   cp .env.example .env
   # Edit .env with your Apple Music API credentials
   ```

3. **Start core services** (MinIO, ChromaDB, Embedding Server):
   ```bash
   docker-compose up -d
   ```

4. **Check service health**:
   ```bash
   docker-compose ps
   ```

   All services should show "healthy" status.

5. **Access service UIs**:
   - Frontend Web UI: http://localhost:3000
   - MinIO Console: http://localhost:9001 (login: minioadmin/minioadmin)
   - ChromaDB API: http://localhost:8000
   - Query API: http://localhost:8081/health
   - Embedding Server: http://localhost:8080/health

## Usage

### Building the Music Catalogue

The catalogue builder is an on-demand service that fetches music from Apple Music playlists and indexes them.

#### Interactive Shell Mode (Recommended)

Run the interactive shell to index multiple playlists:

```bash
docker-compose --profile tools run --rm catalogue-builder
```

Then enter playlist IDs when prompted:
```
Playlist ID: pl.606afcbb70264d2eb2b51d8dbcfa6a12
Playlist ID: pl.d66feecbd40d423d81e8e643e368291a
Playlist ID: quit
```

#### Single Playlist Mode

Process a specific Apple Music playlist:

```bash
docker-compose --profile tools run --rm catalogue-builder \
  --playlist-id pl.d66feecbd40d423d81e8e643e368291a
```

#### Reprocess Existing Songs

By default, songs already in the database are skipped. To reprocess:

```bash
docker-compose --profile tools run --rm catalogue-builder \
  --playlist-id pl.606afcbb70264d2eb2b51d8dbcfa6a12 \
  --no-skip-existing
```

See [services/catalogue-builder/README.md](services/catalogue-builder/README.md) for more details.

### Searching for Music

#### Web UI (Recommended)

The easiest way to search for music is through the web interface:

1. Start all services:
   ```bash
   docker-compose up -d
   ```

2. Open your browser to [http://localhost:3000](http://localhost:3000)

3. Enter a natural language query like:
   - "upbeat electronic dance music"
   - "sad acoustic guitar ballad"
   - "energetic rock with electric guitar"

4. Click search and play audio previews directly in the browser

#### Command Line Interface

Run the interactive query client:

```bash
docker-compose run --rm query-client
```

Then enter text queries or song IDs:
```
Query: upbeat electronic dance music
Query: [1234567890]  # Query by song ID
Query: quit
```

#### API Access

Query the API directly:

```bash
curl -X POST http://localhost:8081/query/text \
  -H "Content-Type: application/json" \
  -d '{"query": "upbeat electronic dance music", "top_k": 10}'
```

### Migrating Existing Data

If you have existing data in `clips_wav/` and `chroma_db/`, you'll need to migrate it:

```bash
# TODO: Create migration scripts in Phase 5
# These will upload WAV files to MinIO and ChromaDB data to the container
```

## Docker Commands Reference

### Start all services
```bash
docker-compose up -d
```

### Stop all services
```bash
docker-compose down
```

### View logs
```bash
# All services
docker-compose logs -f

# Specific service
docker-compose logs -f embedding-server
```

### Rebuild a service
```bash
docker-compose build embedding-server
docker-compose up -d embedding-server
```

### Run one-off commands
```bash
# Catalogue builder (requires --profile tools)
docker-compose --profile tools run --rm catalogue-builder --help
docker-compose --profile tools run --rm catalogue-builder --interactive

# Query client
docker-compose run --rm query-client
```

### Clean up everything (including volumes)
```bash
docker-compose down -v
```

## Development

### Service Development Workflow

1. **Make changes** to service code in `services/<service-name>/`
2. **Rebuild** the service: `docker-compose build <service-name>`
3. **Restart** the service: `docker-compose up -d <service-name>`
4. **Check logs**: `docker-compose logs -f <service-name>`

### Adding Dependencies

Edit `services/<service-name>/requirements.txt` and rebuild:
```bash
docker-compose build <service-name>
docker-compose up -d <service-name>
```

## Configuration

### Environment Variables

Key environment variables (see `.env.example`):

- `MINIO_ROOT_USER` / `MINIO_ROOT_PASSWORD` - MinIO credentials
- `APPLE_KEY_ID` / `APPLE_TEAM_ID` - Apple Music API credentials
- `DEVICE` - Computing device (cpu, cuda, mps)

### GPU Support

To enable GPU support for the embedding server:

1. Uncomment the GPU section in `docker-compose.yml`
2. Ensure NVIDIA Docker runtime is installed
3. Set `DEVICE=cuda` in `.env`
4. Use GPU-enabled base image in `services/embedding-server/Dockerfile`

## Production Deployment

### Transitioning to Production

1. **MinIO → S3**: Update service configs to use S3 SDK
2. **ChromaDB → Chroma Cloud**: Update connection strings
3. **Embedding Server → Modal/RunPod**: Deploy with GPU support
4. **Catalogue Builder → Cron**: Schedule as periodic job

### Production Checklist

- [ ] Use production-grade secrets management (not .env files)
- [ ] Enable HTTPS/TLS for all services
- [ ] Set `ALLOW_RESET=FALSE` for ChromaDB
- [ ] Configure proper backup strategies
- [ ] Set up monitoring and alerting
- [ ] Use managed services where possible

## Troubleshooting

### Services won't start
```bash
# Check logs
docker-compose logs

# Ensure no port conflicts
lsof -i :8000  # ChromaDB
lsof -i :9000  # MinIO
lsof -i :8080  # Embedding server
```

### Model download issues
The embedding server downloads the MuLAN model on first run. This can take time:
```bash
# Check download progress
docker-compose logs -f embedding-server
```

### Out of memory
Reduce batch size or allocate more memory to Docker:
- Docker Desktop → Settings → Resources → Memory

## Implementation Status

- [x] Phase 1: Project structure setup
- [x] Phase 2: Service design and docker-compose
- [ ] Phase 3: Service implementation
- [ ] Phase 4: Configuration and environment
- [ ] Phase 5: Data migration
- [ ] Phase 6: Testing and validation
- [ ] Phase 7: Production readiness

## License

MIT

## Contributing

Contributions welcome! Please open an issue or PR.
