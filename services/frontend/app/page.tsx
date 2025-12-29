'use client';

import { useState, useRef, useEffect } from 'react';
import { Search, Play, Pause, Music2, Loader2 } from 'lucide-react';

interface SongResult {
  id: string;
  distance: number;
  cosine_similarity: number;
  metadata: {
    song_name: string;
    artist_name: string;
    album_name: string;
    genres: string;
  };
  audio_url: string;
}

interface QueryResponse {
  results: SongResult[];
  query_type: string;
}

export default function Home() {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<SongResult[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [playingId, setPlayingId] = useState<string | null>(null);
  const [audioCache, setAudioCache] = useState<Map<string, HTMLAudioElement>>(new Map());
  const currentAudioRef = useRef<HTMLAudioElement | null>(null);

  // Pre-fetch audio previews when results change
  useEffect(() => {
    if (results.length > 0) {
      const newCache = new Map<string, HTMLAudioElement>();
      
      results.forEach((song) => {
        // Create audio element for each result
        const audio = new Audio();
        audio.src = song.audio_url;
        audio.preload = 'auto';
        
        // Add event listeners
        audio.addEventListener('ended', () => {
          setPlayingId(null);
        });
        
        audio.addEventListener('error', (e) => {
          console.error(`Failed to load audio for ${song.id}:`, e);
        });
        
        newCache.set(song.id, audio);
      });
      
      setAudioCache(newCache);
    }
    
    // Cleanup function
    return () => {
      audioCache.forEach((audio) => {
        audio.pause();
        audio.src = '';
      });
    };
  }, [results]);

  const handleSearch = async (e: React.FormEvent) => {
    e.preventDefault();
    
    if (!query.trim()) {
      setError('Please enter a search query');
      return;
    }

    setLoading(true);
    setError(null);
    setResults([]);
    
    // Stop any currently playing audio
    if (currentAudioRef.current) {
      currentAudioRef.current.pause();
      currentAudioRef.current = null;
      setPlayingId(null);
    }

    try {
      const apiUrl = process.env.NEXT_PUBLIC_API_URL;
      console.log('API URL:', apiUrl);
      const response = await fetch(`${apiUrl}/query/text`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          query: query,
          top_k: 10,
        }),
      });

      if (!response.ok) {
        throw new Error(`Search failed: ${response.statusText}`);
      }

      const data: QueryResponse = await response.json();
      setResults(data.results);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'An error occurred');
      console.error('Search error:', err);
    } finally {
      setLoading(false);
    }
  };

  const togglePlay = (songId: string) => {
    const audio = audioCache.get(songId);
    
    if (!audio) {
      console.error(`Audio not found for ${songId}`);
      return;
    }

    // If this song is already playing, pause it
    if (playingId === songId) {
      audio.pause();
      setPlayingId(null);
      currentAudioRef.current = null;
    } else {
      // Pause any currently playing audio
      if (currentAudioRef.current) {
        currentAudioRef.current.pause();
      }
      
      // Play the new audio
      audio.currentTime = 0;
      audio.play().catch((err) => {
        console.error('Failed to play audio:', err);
        setError('Failed to play audio preview');
      });
      
      setPlayingId(songId);
      currentAudioRef.current = audio;
    }
  };

  return (
    <div className="min-h-screen bg-gradient-to-br from-purple-50 via-white to-blue-50 dark:from-gray-900 dark:via-gray-800 dark:to-gray-900">
      <div className="container mx-auto px-4 py-12 max-w-4xl">
        {/* Header */}
        <div className="text-center mb-12">
          <div className="flex items-center justify-center mb-4">
            <Music2 className="w-12 h-12 text-purple-600 dark:text-purple-400" />
          </div>
          <h1 className="text-5xl font-bold text-gray-900 dark:text-white mb-3">
            MusicLip
          </h1>
          <p className="text-lg text-gray-600 dark:text-gray-300">
            Search for music using natural language
          </p>
        </div>

        {/* Search Form */}
        <form onSubmit={handleSearch} className="mb-8">
          <div className="relative">
            <input
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Try: 'upbeat electronic dance music' or 'sad acoustic guitar'"
              className="w-full px-6 py-4 pr-14 text-lg rounded-2xl border-2 border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-white placeholder-gray-400 focus:outline-none focus:border-purple-500 dark:focus:border-purple-400 transition-colors shadow-lg"
              disabled={loading}
            />
            <button
              type="submit"
              disabled={loading}
              className="absolute right-2 top-1/2 -translate-y-1/2 p-3 bg-purple-600 hover:bg-purple-700 disabled:bg-gray-400 text-white rounded-xl transition-colors shadow-md"
            >
              {loading ? (
                <Loader2 className="w-5 h-5 animate-spin" />
              ) : (
                <Search className="w-5 h-5" />
              )}
            </button>
          </div>
        </form>

        {/* Error Message */}
        {error && (
          <div className="mb-6 p-4 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-xl text-red-700 dark:text-red-300">
            {error}
          </div>
        )}

        {/* Results */}
        {results.length > 0 && (
          <div className="space-y-3">
            <h2 className="text-2xl font-semibold text-gray-900 dark:text-white mb-4">
              Top Results
            </h2>
            {results.map((song, index) => (
              <div
                key={song.id}
                className="bg-white dark:bg-gray-800 rounded-xl p-5 shadow-md hover:shadow-lg transition-shadow border border-gray-100 dark:border-gray-700"
              >
                <div className="flex items-start gap-4">
                  {/* Play Button */}
                  <button
                    onClick={() => togglePlay(song.id)}
                    className="flex-shrink-0 w-12 h-12 flex items-center justify-center bg-purple-600 hover:bg-purple-700 text-white rounded-full transition-colors shadow-md"
                    aria-label={playingId === song.id ? 'Pause' : 'Play'}
                  >
                    {playingId === song.id ? (
                      <Pause className="w-5 h-5" />
                    ) : (
                      <Play className="w-5 h-5 ml-0.5" />
                    )}
                  </button>

                  {/* Song Info */}
                  <div className="flex-grow min-w-0">
                    <div className="flex items-start justify-between gap-2 mb-1">
                      <h3 className="text-lg font-semibold text-gray-900 dark:text-white truncate">
                        {song.metadata.song_name}
                      </h3>
                      <span className="flex-shrink-0 text-sm font-medium text-purple-600 dark:text-purple-400">
                        #{index + 1}
                      </span>
                    </div>
                    <p className="text-gray-600 dark:text-gray-300 mb-2 truncate">
                      {song.metadata.artist_name}
                    </p>
                    <div className="flex flex-wrap gap-2 text-sm">
                      <span className="px-2 py-1 bg-gray-100 dark:bg-gray-700 text-gray-700 dark:text-gray-300 rounded-md">
                        {song.metadata.genres}
                      </span>
                      <span className="px-2 py-1 bg-purple-50 dark:bg-purple-900/20 text-purple-700 dark:text-purple-300 rounded-md">
                        {(song.cosine_similarity * 100).toFixed(1)}% match
                      </span>
                    </div>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}

        {/* Empty State */}
        {!loading && results.length === 0 && !error && (
          <div className="text-center py-16">
            <Music2 className="w-16 h-16 text-gray-300 dark:text-gray-600 mx-auto mb-4" />
            <p className="text-gray-500 dark:text-gray-400 text-lg">
              Search for music to get started
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
