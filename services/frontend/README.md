# MusicLip Frontend

A modern, responsive web interface for searching music using natural language queries.

## Features

- **Text-based search**: Search for music using natural language descriptions
- **Real-time results**: Get top 10 matching songs instantly
- **Audio preview**: Pre-fetched audio previews with play/pause controls
- **Modern UI**: Built with Next.js, React, TypeScript, and TailwindCSS
- **Responsive design**: Works seamlessly on desktop and mobile devices

## Tech Stack

- **Framework**: Next.js 14 (App Router)
- **Language**: TypeScript
- **Styling**: TailwindCSS
- **Icons**: Lucide React
- **Deployment**: Docker, Vercel, or CloudFront

## Development

### Local Development (without Docker)

1. Install dependencies:
   ```bash
   npm install
   ```

2. Set environment variables:
   ```bash
   export NEXT_PUBLIC_API_URL=http://localhost:8081
   ```

3. Run development server:
   ```bash
   npm run dev
   ```

4. Open [http://localhost:3000](http://localhost:3000)

### Docker Development

Run with docker-compose from the project root:

```bash
docker-compose up -d frontend
```

Access at [http://localhost:3000](http://localhost:3000)

## Environment Variables

- `NEXT_PUBLIC_API_URL`: URL of the query-client API (default: `http://localhost:8081`)

## Deployment

### Vercel

1. Connect your GitHub repository to Vercel
2. Set environment variable:
   - `NEXT_PUBLIC_API_URL`: Your production query-client API URL
3. Deploy

### CloudFront + S3

1. Build the static export:
   ```bash
   npm run build
   ```

2. Upload `.next/static` and `public` folders to S3
3. Configure CloudFront distribution
4. Set environment variables in build process

### Docker

Build and run:

```bash
docker build -t musiclip-frontend .
docker run -p 3000:3000 -e NEXT_PUBLIC_API_URL=http://your-api-url musiclip-frontend
```

## API Integration

The frontend communicates with the query-client service via REST API:

- **Endpoint**: `POST /query/text`
- **Request**:
  ```json
  {
    "query": "upbeat electronic dance music",
    "top_k": 10
  }
  ```
- **Response**:
  ```json
  {
    "results": [
      {
        "id": "1234567890",
        "distance": 0.123,
        "cosine_similarity": 0.877,
        "metadata": {
          "song_name": "Song Name",
          "artist_name": "Artist Name",
          "album_name": "Album Name",
          "genres": "Electronic, Dance"
        },
        "audio_url": "http://localhost:9001/music-clips/1234567890.wav"
      }
    ],
    "query_type": "text"
  }
  ```

## Architecture

- **Client-side rendering**: Search and audio playback happen in the browser
- **Audio pre-fetching**: All result previews are pre-loaded for instant playback
- **Responsive design**: Mobile-first approach with TailwindCSS
- **Type safety**: Full TypeScript coverage for reliability
