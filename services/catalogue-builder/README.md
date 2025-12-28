# Catalogue Builder Service

This service fetches music from Apple Music playlists and builds the music catalogue by:
1. Fetching playlists from Apple Music API
2. Downloading preview audio files
3. Converting to WAV format (24kHz, mono)
4. Uploading to MinIO object storage
5. Generating embeddings via the embedding-server
6. Storing embeddings and metadata in ChromaDB

## Prerequisites

- Apple Music API credentials (Key ID and Team ID)
- Apple Music API private key file (`.p8` file)
- All infrastructure services running (MinIO, ChromaDB, embedding-server)

## Usage

### Interactive Shell Mode (Recommended)

Run the service in interactive mode to index multiple playlists:

```bash
docker-compose --profile tools run --rm catalogue-builder
```

This will launch an interactive shell where you can enter playlist IDs:

```
============================================================
Apple Music Playlist Indexer - Interactive Shell
============================================================
Enter Apple Music playlist IDs to index them.
Type 'quit' or 'exit' to exit.

✓ Configuration validated
  Apple Key ID: TQ523NN89M
  Apple Team ID: R4XZQYADC3
  ChromaDB: chromadb:8000
  MinIO: minio:9000
  Embedding Server: http://embedding-server:8080

Playlist ID: pl.606afcbb70264d2eb2b51d8dbcfa6a12
```

### Single Playlist Mode

Index a specific playlist:

```bash
docker-compose --profile tools run --rm catalogue-builder \
  --playlist-id pl.606afcbb70264d2eb2b51d8dbcfa6a12
```

### Reprocess Existing Songs

By default, songs already in the database are skipped. To reprocess them:

```bash
docker-compose --profile tools run --rm catalogue-builder \
  --playlist-id pl.606afcbb70264d2eb2b51d8dbcfa6a12 \
  --no-skip-existing
```

## Finding Apple Music Playlist IDs

1. Open Apple Music in a web browser
2. Navigate to the playlist you want to index
3. The URL will contain the playlist ID:
   ```
   https://music.apple.com/us/playlist/[playlist-name]/pl.XXXXXXXXXXXXXXXXXXXXXXXX
   ```
4. Copy the `pl.XXXXXXXXXXXXXXXXXXXXXXXX` part

### Popular Apple Music Playlists

- **Today's Hits**: `pl.606afcbb70264d2eb2b51d8dbcfa6a12`
- **Top 100: USA**: `pl.606afcbb70264d2eb2b51d8dbcfa6a12`
- **Chill Vibes**: `pl.d66feecbd40d423d81e8e643e368291a`

## Configuration

All configuration is done via environment variables in `docker-compose.yml`:

| Variable | Default | Description |
|----------|---------|-------------|
| `APPLE_KEY_ID` | - | Apple Music API Key ID |
| `APPLE_TEAM_ID` | - | Apple Music API Team ID |
| `APPLE_KEY_PATH` | `/secrets/apple_music_key.p8` | Path to private key file |
| `MINIO_ENDPOINT` | `minio:9000` | MinIO server endpoint |
| `MINIO_ACCESS_KEY` | `minioadmin` | MinIO access key |
| `MINIO_SECRET_KEY` | `minioadmin` | MinIO secret key |
| `MINIO_BUCKET` | `music-clips` | MinIO bucket name |
| `CHROMA_HOST` | `chromadb` | ChromaDB host |
| `CHROMA_PORT` | `8000` | ChromaDB port |
| `EMBEDDING_SERVER_URL` | `http://embedding-server:8080` | Embedding server URL |
| `SAMPLE_RATE` | `24000` | Audio sample rate (Hz) |
| `STOREFRONT` | `us` | Apple Music storefront/region |

## Output

The service will:
- Download and convert audio files to WAV
- Upload WAV files to MinIO (accessible via MinIO console at http://localhost:9001)
- Store embeddings and metadata in ChromaDB
- Print progress for each track:
  - `✓` Successfully indexed
  - `⊙` Skipped (already in database)
  - `✗` Failed (with error message)

## Troubleshooting

### "Apple Music credentials not configured"
- Ensure `APPLE_KEY_ID` and `APPLE_TEAM_ID` are set in your `.env` file
- Copy `.env.example` to `.env` if you haven't already

### "Apple Music key file not found"
- Ensure `AuthKey_TQ523NN89M.p8` exists in the project root
- Check the volume mount in `docker-compose.yml`

### "Failed to fetch playlist"
- Verify the playlist ID is correct
- Check that the playlist is public or accessible
- Ensure your Apple Music API token is valid

### "No preview URL available"
- Some songs don't have preview URLs available
- This is a limitation of the Apple Music API
- The service will skip these tracks automatically

## Development

To run locally without Docker:

```bash
cd services/catalogue-builder

# Install dependencies
pip install -r requirements.txt

# Set environment variables
export APPLE_KEY_ID=your_key_id
export APPLE_TEAM_ID=your_team_id
export APPLE_KEY_PATH=/path/to/AuthKey.p8
export CHROMA_HOST=localhost
export CHROMA_PORT=8000
export MINIO_ENDPOINT=localhost:9000
export EMBEDDING_SERVER_URL=http://localhost:8080

# Run interactive shell
python build_catalogue.py --interactive

# Or index a specific playlist
python build_catalogue.py --playlist-id pl.606afcbb70264d2eb2b51d8dbcfa6a12
```
