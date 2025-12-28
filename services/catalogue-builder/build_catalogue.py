"""
Catalogue Builder - Fetches music from Apple Music and builds the catalogue

This script will:
1. Fetch playlists from Apple Music API
2. Download preview audio files
3. Upload to MinIO
4. Call embedding-server to generate embeddings
5. Store embeddings and metadata in ChromaDB
"""
import os
import sys
import jwt
import time
import requests
import subprocess
import tempfile
import argparse
from datetime import datetime, timedelta
from pathlib import Path
from minio import Minio
from minio.error import S3Error
import chromadb


# ============================================================================
# Configuration from environment variables
# ============================================================================
APPLE_KEY_ID = os.getenv('APPLE_KEY_ID')
APPLE_TEAM_ID = os.getenv('APPLE_TEAM_ID')
APPLE_KEY_PATH = os.getenv('APPLE_KEY_PATH', '/secrets/apple_music_key.p8')

MINIO_ENDPOINT = os.getenv('MINIO_ENDPOINT', 'localhost:9000')
MINIO_ACCESS_KEY = os.getenv('MINIO_ACCESS_KEY', 'minioadmin')
MINIO_SECRET_KEY = os.getenv('MINIO_SECRET_KEY', 'minioadmin')
MINIO_BUCKET = os.getenv('MINIO_BUCKET', 'music-clips')
MINIO_SECURE = os.getenv('MINIO_SECURE', 'false').lower() == 'true'

CHROMA_HOST = os.getenv('CHROMA_HOST', 'localhost')
CHROMA_PORT = int(os.getenv('CHROMA_PORT', '8000'))

EMBEDDING_SERVER_URL = os.getenv('EMBEDDING_SERVER_URL', 'http://localhost:8080')

SAMPLE_RATE = int(os.getenv('SAMPLE_RATE', '24000'))
STOREFRONT = os.getenv('STOREFRONT', 'us')


# ============================================================================
# Apple Music API Functions
# ============================================================================
def generate_apple_developer_token(
    private_key_path: str,
    key_id: str,
    team_id: str,
    expiration_days: int = 180
) -> str:
    """Generate an Apple Music API Developer Token (JWT)."""
    with open(private_key_path, 'r') as key_file:
        private_key = key_file.read()
    
    expiration_time = datetime.utcnow() + timedelta(days=min(expiration_days, 180))
    
    headers = {
        "alg": "ES256",
        "kid": key_id
    }
    
    payload = {
        "iss": team_id,
        "iat": int(time.time()),
        "exp": int(expiration_time.timestamp())
    }
    
    token = jwt.encode(
        payload,
        private_key,
        algorithm="ES256",
        headers=headers
    )
    
    return token


def get_catalog_playlist(
    token: str,
    playlist_id: str,
    storefront: str = "us",
    include_tracks: bool = True
) -> dict:
    """Get a catalog playlist from Apple Music API."""
    url = f"https://api.music.apple.com/v1/catalog/{storefront}/playlists/{playlist_id}"
    headers = {"Authorization": f"Bearer {token}"}
    
    params = {}
    if include_tracks:
        params["include"] = "tracks"
    
    try:
        response = requests.get(url, headers=headers, params=params)
        response_data = response.json() if response.text else {}
        
        if response.status_code == 200:
            return {"success": True, "status_code": response.status_code, "data": response_data}
        else:
            return {"success": False, "status_code": response.status_code, "data": response_data}
    except requests.exceptions.RequestException as e:
        return {"success": False, "status_code": None, "data": {"error": str(e)}}


def get_catalog_song(
    token: str,
    song_id: str,
    storefront: str = "us"
) -> dict:
    """Get a catalog song from Apple Music API."""
    url = f"https://api.music.apple.com/v1/catalog/{storefront}/songs/{song_id}"
    headers = {"Authorization": f"Bearer {token}"}
    
    try:
        response = requests.get(url, headers=headers)
        response_data = response.json() if response.text else {}
        
        if response.status_code == 200:
            return {"success": True, "status_code": response.status_code, "data": response_data}
        else:
            return {"success": False, "status_code": response.status_code, "data": response_data}
    except requests.exceptions.RequestException as e:
        return {"success": False, "status_code": None, "data": {"error": str(e)}}


# ============================================================================
# Audio Processing Functions
# ============================================================================
def download_and_convert_preview(
    preview_url: str,
    song_id: str,
    sample_rate: int = 24000
) -> dict:
    """Download a preview audio file and convert it to WAV format using ffmpeg.
    Returns a temporary file that the caller must delete after use."""
    try:
        # Create temporary files (not using context manager so they persist)
        temp_m4a = tempfile.NamedTemporaryFile(suffix='.m4a', delete=False)
        temp_wav = tempfile.NamedTemporaryFile(suffix='.wav', delete=False)
        
        try:
            # Download the preview file
            response = requests.get(preview_url, stream=True)
            response.raise_for_status()
            
            with open(temp_m4a.name, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            
            # Convert to WAV using ffmpeg
            ffmpeg_cmd = [
                'ffmpeg',
                '-i', temp_m4a.name,
                '-ar', str(sample_rate),
                '-ac', '1',  # mono
                '-y',
                temp_wav.name
            ]
            
            result = subprocess.run(
                ffmpeg_cmd,
                capture_output=True,
                text=True
            )
            
            # Clean up m4a file
            os.unlink(temp_m4a.name)
            
            if result.returncode != 0:
                os.unlink(temp_wav.name)
                return {
                    "success": False,
                    "wav_path": None,
                    "message": f"ffmpeg error: {result.stderr}"
                }
            
            return {
                "success": True,
                "wav_path": temp_wav.name,
                "message": f"Successfully converted to WAV"
            }
        except Exception as e:
            # Clean up temp files on error
            try:
                os.unlink(temp_m4a.name)
            except:
                pass
            try:
                os.unlink(temp_wav.name)
            except:
                pass
            raise
            
    except Exception as e:
        return {
            "success": False,
            "wav_path": None,
            "message": f"Error: {str(e)}"
        }


# ============================================================================
# MinIO Functions
# ============================================================================
def get_minio_client():
    """Create and return a MinIO client."""
    return Minio(
        MINIO_ENDPOINT,
        access_key=MINIO_ACCESS_KEY,
        secret_key=MINIO_SECRET_KEY,
        secure=MINIO_SECURE
    )


def upload_to_minio(file_path: str, song_id: str) -> dict:
    """Upload a WAV file to MinIO."""
    try:
        client = get_minio_client()
        
        # Ensure bucket exists
        if not client.bucket_exists(MINIO_BUCKET):
            client.make_bucket(MINIO_BUCKET)
        
        # Upload file
        object_name = f"{song_id}.wav"
        client.fput_object(
            MINIO_BUCKET,
            object_name,
            file_path,
            content_type="audio/wav"
        )
        
        return {
            "success": True,
            "object_name": object_name,
            "message": f"Uploaded to MinIO: {object_name}"
        }
    except S3Error as e:
        return {
            "success": False,
            "object_name": None,
            "message": f"MinIO error: {str(e)}"
        }
    except Exception as e:
        return {
            "success": False,
            "object_name": None,
            "message": f"Error: {str(e)}"
        }


# ============================================================================
# Embedding Functions
# ============================================================================
def get_audio_embedding(wav_path: str) -> dict:
    """Get audio embedding from the embedding server."""
    try:
        with open(wav_path, 'rb') as f:
            files = {'file': (f'{Path(wav_path).name}', f, 'audio/wav')}
            response = requests.post(
                f"{EMBEDDING_SERVER_URL}/embed/audio",
                files=files,
                timeout=60
            )
            response.raise_for_status()
            return {
                "success": True,
                "embedding": response.json()['embedding']
            }
    except Exception as e:
        return {
            "success": False,
            "embedding": None,
            "message": f"Failed to get embedding: {e}"
        }


# ============================================================================
# ChromaDB Functions
# ============================================================================
def get_chromadb_client():
    """Create and return a ChromaDB client."""
    # Simple connection without tenant/database for compatibility with existing data
    return chromadb.HttpClient(host=CHROMA_HOST, port=CHROMA_PORT)


def song_exists_in_chromadb(song_id: str, collection) -> bool:
    """Check if a song already exists in ChromaDB."""
    try:
        existing = collection.get(ids=[song_id])
        return len(existing['ids']) > 0
    except Exception:
        return False


def add_song_to_chromadb(
    song_id: str,
    song_name: str,
    album_name: str,
    artist_name: str,
    release_date: str,
    genres: list,
    embedding: list,
    collection
) -> dict:
    """Add a song to ChromaDB with metadata and audio embedding."""
    try:
        metadata = {
            "song_id": song_id,
            "song_name": song_name,
            "album_name": album_name,
            "artist_name": artist_name,
            "release_date": release_date,
            "genres": ", ".join(genres) if genres else ""
        }
        
        # Check if ID already exists and delete it
        try:
            existing = collection.get(ids=[song_id])
            if existing['ids']:
                collection.delete(ids=[song_id])
        except Exception:
            pass
        
        # Add to ChromaDB
        collection.add(
            ids=[song_id],
            embeddings=[embedding],
            metadatas=[metadata]
        )
        
        return {
            "success": True,
            "message": f"Added to ChromaDB: {song_name}"
        }
        
    except Exception as e:
        return {
            "success": False,
            "message": f"Error adding to ChromaDB: {str(e)}"
        }


# ============================================================================
# Main Processing Functions
# ============================================================================
def process_song(
    token: str,
    track_id: str,
    track_name: str,
    artist_name: str,
    collection,
    skip_existing: bool = True
) -> dict:
    """Process a single song: download, convert, upload, embed, and index."""
    
    # Check if song already exists
    if skip_existing and song_exists_in_chromadb(track_id, collection):
        return {"status": "skipped", "message": "Already in database"}
    
    try:
        # Fetch detailed song info
        song_result = get_catalog_song(token=token, song_id=track_id, storefront=STOREFRONT)
        
        if not song_result["success"]:
            return {"status": "failed", "message": "Failed to fetch song details"}
        
        # Extract song data
        song_data = song_result["data"]
        if "data" not in song_data or len(song_data["data"]) == 0:
            return {"status": "failed", "message": "No song data available"}
        
        song = song_data["data"][0]
        attributes = song.get("attributes", {})
        preview_url = attributes.get('previews', [{}])[0].get('url') if attributes.get('previews') else None
        
        if not preview_url:
            return {"status": "failed", "message": "No preview URL available"}
        
        # Download and convert preview
        convert_result = download_and_convert_preview(
            preview_url=preview_url,
            song_id=track_id,
            sample_rate=SAMPLE_RATE
        )
        
        if not convert_result["success"]:
            return {"status": "failed", "message": f"Conversion failed: {convert_result['message']}"}
        
        wav_path = convert_result['wav_path']
        
        try:
            # Upload to MinIO
            upload_result = upload_to_minio(wav_path, track_id)
            if not upload_result["success"]:
                return {"status": "failed", "message": f"Upload failed: {upload_result['message']}"}
            
            # Get embedding
            embed_result = get_audio_embedding(wav_path)
            if not embed_result["success"]:
                return {"status": "failed", "message": embed_result.get('message', 'Embedding failed')}
            
            # Add to ChromaDB
            chromadb_result = add_song_to_chromadb(
                song_id=track_id,
                song_name=attributes.get('name', 'Unknown'),
                album_name=attributes.get('albumName', 'Unknown'),
                artist_name=attributes.get('artistName', 'Unknown'),
                release_date=attributes.get('releaseDate', 'Unknown'),
                genres=attributes.get('genreNames', []),
                embedding=embed_result['embedding'],
                collection=collection
            )
            
            if chromadb_result["success"]:
                return {"status": "success", "message": "Successfully indexed"}
            else:
                return {"status": "failed", "message": chromadb_result['message']}
        finally:
            # Clean up temporary WAV file
            try:
                os.unlink(wav_path)
            except:
                pass
            
    except Exception as e:
        return {"status": "failed", "message": f"Error: {str(e)}"}


def process_playlist(
    playlist_id: str,
    skip_existing: bool = True
) -> dict:
    """Process an entire playlist."""
    
    # Validate configuration
    if not APPLE_KEY_ID or not APPLE_TEAM_ID:
        return {
            "success": False,
            "message": "Apple Music credentials not configured. Set APPLE_KEY_ID and APPLE_TEAM_ID environment variables."
        }
    
    if not os.path.exists(APPLE_KEY_PATH):
        return {
            "success": False,
            "message": f"Apple Music key file not found at {APPLE_KEY_PATH}"
        }
    
    try:
        # Generate Apple Music token
        print("Generating Apple Music API token...")
        token = generate_apple_developer_token(
            private_key_path=APPLE_KEY_PATH,
            key_id=APPLE_KEY_ID,
            team_id=APPLE_TEAM_ID
        )
        
        # Connect to ChromaDB
        print(f"Connecting to ChromaDB at {CHROMA_HOST}:{CHROMA_PORT}...")
        try:
            client = get_chromadb_client()
            print("Client created successfully")
            collection = client.get_or_create_collection(name="music_embeddings")
            print(f"Connected! Current collection size: {collection.count()}")
        except Exception as e:
            print(f"ChromaDB connection error: {e}")
            raise
        
        # Fetch playlist
        print(f"\nFetching playlist {playlist_id}...")
        playlist_result = get_catalog_playlist(
            token=token,
            playlist_id=playlist_id,
            storefront=STOREFRONT,
            include_tracks=True
        )
        
        if not playlist_result["success"]:
            return {
                "success": False,
                "message": f"Failed to fetch playlist: {playlist_result.get('data', {}).get('error', 'Unknown error')}"
            }
        
        data = playlist_result["data"]
        
        if "data" not in data or len(data["data"]) == 0:
            return {"success": False, "message": "No playlist data available"}
        
        playlist = data["data"][0]
        attributes = playlist.get("attributes", {})
        
        print(f"\nPlaylist: {attributes.get('name', 'N/A')}")
        print(f"Curator: {attributes.get('curatorName', 'N/A')}")
        
        # Process all tracks
        if "relationships" not in playlist or "tracks" not in playlist["relationships"]:
            return {"success": False, "message": "No tracks found in playlist"}
        
        tracks = playlist["relationships"]["tracks"]
        track_list = tracks.get("data", [])
        track_count = len(track_list)
        
        print(f"Number of tracks: {track_count}\n")
        print("="*60)
        
        # Track statistics
        processed = 0
        skipped = 0
        failed = 0
        
        for i, track in enumerate(track_list, 1):
            track_id = track.get("id")
            track_attrs = track.get("attributes", {})
            track_name = track_attrs.get('name', 'Unknown')
            artist_name = track_attrs.get('artistName', 'Unknown')
            
            print(f"[{i}/{track_count}] {track_name} - {artist_name}")
            
            result = process_song(
                token=token,
                track_id=track_id,
                track_name=track_name,
                artist_name=artist_name,
                collection=collection,
                skip_existing=skip_existing
            )
            
            if result["status"] == "success":
                print(f"  ✓ {result['message']}")
                processed += 1
            elif result["status"] == "skipped":
                print(f"  ⊙ {result['message']}")
                skipped += 1
            else:
                print(f"  ✗ {result['message']}")
                failed += 1
        
        # Print summary
        print("\n" + "="*60)
        print("PROCESSING SUMMARY")
        print("="*60)
        print(f"Total tracks: {track_count}")
        print(f"Successfully processed: {processed}")
        print(f"Skipped (already in DB): {skipped}")
        print(f"Failed: {failed}")
        print("="*60)
        
        return {
            "success": True,
            "total": track_count,
            "processed": processed,
            "skipped": skipped,
            "failed": failed
        }
        
    except Exception as e:
        return {
            "success": False,
            "message": f"Error processing playlist: {str(e)}"
        }


def process_single_song(
    song_id: str,
    skip_existing: bool = True
) -> dict:
    """Process a single song by its ID."""
    
    # Validate configuration
    if not APPLE_KEY_ID or not APPLE_TEAM_ID:
        return {
            "success": False,
            "message": "Apple Music credentials not configured. Set APPLE_KEY_ID and APPLE_TEAM_ID environment variables."
        }
    
    if not os.path.exists(APPLE_KEY_PATH):
        return {
            "success": False,
            "message": f"Apple Music key file not found at {APPLE_KEY_PATH}"
        }
    
    try:
        # Generate Apple Music token
        print("Generating Apple Music API token...")
        token = generate_apple_developer_token(
            private_key_path=APPLE_KEY_PATH,
            key_id=APPLE_KEY_ID,
            team_id=APPLE_TEAM_ID
        )
        
        # Connect to ChromaDB
        print(f"Connecting to ChromaDB at {CHROMA_HOST}:{CHROMA_PORT}...")
        try:
            client = get_chromadb_client()
            collection = client.get_or_create_collection(name="music_embeddings")
            print(f"Connected! Current collection size: {collection.count()}")
        except Exception as e:
            print(f"ChromaDB connection error: {e}")
            raise
        
        # Fetch song details
        print(f"\nFetching song {song_id}...")
        song_result = get_catalog_song(token=token, song_id=song_id, storefront=STOREFRONT)
        
        if not song_result["success"]:
            return {
                "success": False,
                "message": f"Failed to fetch song: {song_result.get('data', {}).get('error', 'Unknown error')}"
            }
        
        data = song_result["data"]
        
        if "data" not in data or len(data["data"]) == 0:
            return {"success": False, "message": "No song data available"}
        
        song = data["data"][0]
        attributes = song.get("attributes", {})
        song_name = attributes.get('name', 'Unknown')
        artist_name = attributes.get('artistName', 'Unknown')
        
        print(f"\nSong: {song_name}")
        print(f"Artist: {artist_name}")
        print("="*60)
        
        # Process the song
        result = process_song(
            token=token,
            track_id=song_id,
            track_name=song_name,
            artist_name=artist_name,
            collection=collection,
            skip_existing=skip_existing
        )
        
        if result["status"] == "success":
            print(f"✓ {result['message']}")
            return {"success": True, "message": "Song indexed successfully"}
        elif result["status"] == "skipped":
            print(f"⊙ {result['message']}")
            return {"success": True, "message": "Song already in database"}
        else:
            print(f"✗ {result['message']}")
            return {"success": False, "message": result['message']}
        
    except Exception as e:
        return {
            "success": False,
            "message": f"Error processing song: {str(e)}"
        }


# ============================================================================
# Interactive Shell
# ============================================================================
def interactive_shell():
    """Launch an interactive shell for indexing playlists and songs."""
    print("=" * 60)
    print("Apple Music Catalogue Indexer - Interactive Shell")
    print("=" * 60)
    print("Index playlists or individual songs from Apple Music.")
    print("Type 'quit' or 'exit' to exit.\n")
    
    # Validate configuration on startup
    if not APPLE_KEY_ID or not APPLE_TEAM_ID:
        print("ERROR: Apple Music credentials not configured.")
        print("Set APPLE_KEY_ID and APPLE_TEAM_ID environment variables.")
        return
    
    if not os.path.exists(APPLE_KEY_PATH):
        print(f"ERROR: Apple Music key file not found at {APPLE_KEY_PATH}")
        return
    
    print(f"✓ Configuration validated")
    print(f"  Apple Key ID: {APPLE_KEY_ID}")
    print(f"  Apple Team ID: {APPLE_TEAM_ID}")
    print(f"  ChromaDB: {CHROMA_HOST}:{CHROMA_PORT}")
    print(f"  MinIO: {MINIO_ENDPOINT}")
    print(f"  Embedding Server: {EMBEDDING_SERVER_URL}\n")
    
    while True:
        try:
            # Ask user to choose between playlist or song
            print("\nWhat would you like to add?")
            print("  1. Playlist")
            print("  2. Song")
            print("  q. Quit")
            
            choice = input("\nChoice (1/2/q): ").strip().lower()
            
            if choice in ['quit', 'exit', 'q']:
                print("Goodbye!")
                break
            
            if choice == '1':
                # Playlist mode
                playlist_id = input("\nPlaylist ID: ").strip()
                
                if not playlist_id:
                    print("Please enter a valid playlist ID.")
                    continue
                
                # Process the playlist
                result = process_playlist(playlist_id, skip_existing=True)
                
                if not result["success"]:
                    print(f"\nError: {result['message']}\n")
                else:
                    print(f"\n✓ Playlist indexed successfully!\n")
            
            elif choice == '2':
                # Song mode
                song_id = input("\nSong ID: ").strip()
                
                if not song_id:
                    print("Please enter a valid song ID.")
                    continue
                
                # Process the song
                result = process_single_song(song_id, skip_existing=True)
                
                if not result["success"]:
                    print(f"\nError: {result['message']}\n")
                else:
                    print(f"\n✓ {result['message']}\n")
            
            else:
                print("Invalid choice. Please enter 1, 2, or q.")
            
        except KeyboardInterrupt:
            print("\n\nGoodbye!")
            break
        except Exception as e:
            print(f"Error: {e}\n")


# ============================================================================
# Main Entry Point
# ============================================================================
def main():
    parser = argparse.ArgumentParser(
        description='Build music catalogue from Apple Music playlists and songs',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Interactive shell mode
  python build_catalogue.py --interactive
  
  # Index a specific playlist
  python build_catalogue.py --playlist-id pl.606afcbb70264d2eb2b51d8dbcfa6a12
  
  # Index a specific song
  python build_catalogue.py --song-id 1234567890
  
  # Index playlist and reprocess existing songs
  python build_catalogue.py --playlist-id pl.606afcbb70264d2eb2b51d8dbcfa6a12 --no-skip-existing
        """
    )
    parser.add_argument('--interactive', action='store_true', help='Launch interactive shell')
    parser.add_argument('--playlist-id', help='Apple Music playlist ID')
    parser.add_argument('--song-id', help='Apple Music song ID')
    parser.add_argument('--no-skip-existing', action='store_true', help='Reprocess songs already in database')
    
    args = parser.parse_args()
    
    if args.interactive:
        interactive_shell()
    elif args.playlist_id:
        result = process_playlist(args.playlist_id, skip_existing=not args.no_skip_existing)
        if not result["success"]:
            print(f"Error: {result['message']}")
            sys.exit(1)
    elif args.song_id:
        result = process_single_song(args.song_id, skip_existing=not args.no_skip_existing)
        if not result["success"]:
            print(f"Error: {result['message']}")
            sys.exit(1)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
