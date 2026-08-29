import { useState, useEffect, useCallback } from 'react'
import { fetchPlaylists, fetchPlaylist } from './api'
import { PlayerProvider, usePlayer } from './PlayerContext'
import Sidebar from './Sidebar'
import PlayerBar from './PlayerBar'
import HomePage from './HomePage'
import PlaylistView from './PlaylistView'
import PipelinePage from './PipelinePage'

function Toast() {
  const { toast } = usePlayer()
  if (!toast) return null
  return <div className="toast">{toast}</div>
}

function AppInner() {
  const [view, setView] = useState('home')
  const [playlistSummaries, setPlaylistSummaries] = useState([])
  const [selectedPlaylist, setSelectedPlaylist] = useState(null)
  const [loadingList, setLoadingList] = useState(true)
  const [loadingDetail, setLoadingDetail] = useState(false)
  const [error, setError] = useState(null)

  const loadPlaylists = useCallback((showLoading = true) => {
    if (showLoading) setLoadingList(true)
    fetchPlaylists()
      .then(data => {
        setPlaylistSummaries(data)
        setLoadingList(false)
      })
      .catch(e => {
        setError(e.message)
        setLoadingList(false)
      })
  }, [])

  // Fetch all playlists on mount
  useEffect(() => {
    loadPlaylists(true)
  }, [loadPlaylists])

  // Select a playlist — reuse already-loaded full data if available
  const handleSelectPlaylist = useCallback(async (id) => {
    setView('playlist')

    // playlistSummaries now holds full objects (with tracks) from fetchPlaylists
    const cached = playlistSummaries.find(p => p.id === id)
    if (cached?.tracks) {
      setSelectedPlaylist(cached)
      return
    }

    // Fallback: fetch individually (e.g. direct link / first load)
    setLoadingDetail(true)
    try {
      const data = await fetchPlaylist(id)
      setSelectedPlaylist(data)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoadingDetail(false)
    }
  }, [playlistSummaries])

  const handleViewChange = (v) => {
    setView(v)
    if (v === 'home') setSelectedPlaylist(null)
  }

  // Render main content area
  const renderMain = () => {
    if (error) {
      return (
        <div style={{ padding: 40, color: 'var(--text-secondary)' }}>
          <p style={{ color: 'var(--accent)', marginBottom: 8 }}>⚠ Connection Error</p>
          <p style={{ fontSize: 14 }}>{error}</p>
          <p style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 8 }}>
            Make sure the WaveCask backend is running at http://localhost:8000
          </p>
        </div>
      )
    }

    if (loadingList) {
      return (
        <div style={{ padding: 40 }}>
          <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap' }}>
            {Array.from({ length: 8 }).map((_, i) => (
              <div key={i} style={{ width: 160 }}>
                <div className="loading-shimmer" style={{ width: '100%', aspectRatio: '1', borderRadius: 10, marginBottom: 8 }} />
                <div className="loading-shimmer" style={{ height: 12, width: '80%', marginBottom: 6 }} />
                <div className="loading-shimmer" style={{ height: 10, width: '60%' }} />
              </div>
            ))}
          </div>
        </div>
      )
    }

    if (view === 'playlist') {
      if (loadingDetail) {
        return (
          <div style={{ padding: 40 }}>
            {Array.from({ length: 6 }).map((_, i) => (
              <div key={i} className="loading-shimmer" style={{ height: 56, borderRadius: 6, marginBottom: 8 }} />
            ))}
          </div>
        )
      }
      return <PlaylistView playlist={selectedPlaylist} />
    }

    if (view === 'pipeline') {
      return <PipelinePage onRefreshPlaylists={() => loadPlaylists(false)} />
    }

    return (
      <HomePage
        playlists={playlistSummaries}
        onSelect={handleSelectPlaylist}
      />
    )
  }

  return (
    <div className="app-shell">
      <Sidebar
        playlists={playlistSummaries}
        selectedId={selectedPlaylist?.id}
        onSelect={handleSelectPlaylist}
        view={view}
        onViewChange={handleViewChange}
      />
      <main className="main-content">
        {renderMain()}
      </main>
      <PlayerBar />
      <Toast />
    </div>
  )
}

export default function App() {
  return (
    <PlayerProvider>
      <AppInner />
    </PlayerProvider>
  )
}
