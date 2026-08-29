import { thumbUrl, PLAYLIST_TYPE_LABEL } from './api'
import { IconWave, IconHome, IconSearch, IconLibrary, IconMusic, IconPlaylist } from './Icons'
import { usePlayer } from './PlayerContext'

function PlaylistThumb({ playlist }) {
  const tracks = playlist.tracks ?? []
  const vid = tracks[0]?.track?.video_id || tracks[0]?.video_id
  if (vid) {
    return (
      <div className="sidebar-playlist-thumb">
        <img src={thumbUrl(vid, 'default')} alt="" onError={e => e.target.style.display='none'} loading="lazy" />
      </div>
    )
  }
  return (
    <div className="sidebar-playlist-thumb">
      <IconPlaylist size={18} />
    </div>
  )
}

export default function Sidebar({ playlists, selectedId, onSelect, view, onViewChange }) {
  const { currentTrack, playing } = usePlayer()

  return (
    <aside className="sidebar">
      {/* Logo */}
      <div className="sidebar-logo">
        <IconWave size={28} />
        <span className="sidebar-logo-text">WaveCask</span>
      </div>

      {/* Main nav */}
      <nav className="sidebar-nav">
        <div
          className={`sidebar-nav-item ${view === 'home' ? 'active' : ''}`}
          onClick={() => onViewChange('home')}
          id="nav-home"
        >
          <IconHome size={20} />
          Home
        </div>
        <div
          className={`sidebar-nav-item ${view === 'pipeline' ? 'active' : ''}`}
          onClick={() => onViewChange('pipeline')}
          id="nav-pipeline"
        >
          <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor">
            <path d="M19.14 12.94c.04-.3.06-.61.06-.94 0-.32-.02-.64-.07-.94l2.03-1.58c.18-.14.23-.41.12-.61l-1.92-3.32c-.12-.22-.37-.29-.59-.22l-2.39.96c-.5-.38-1.03-.7-1.62-.94l-.36-2.54c-.04-.24-.24-.41-.48-.41h-3.84c-.24 0-.43.17-.47.41l-.36 2.54c-.59.24-1.13.57-1.62.94l-2.39-.96c-.22-.08-.47 0-.59.22L2.74 8.87c-.12.21-.08.47.12.61l2.03 1.58c-.05.3-.09.63-.09.94s.02.64.07.94l-2.03 1.58c-.18.14-.23.41-.12.61l1.92 3.32c.12.22.37.29.59.22l2.39-.96c.5.38 1.03.7 1.62.94l.36 2.54c.05.24.24.41.48.41h3.84c.24 0 .44-.17.47-.41l.36-2.54c.59-.24 1.13-.56 1.62-.94l2.39.96c.22.08.47 0 .59-.22l1.92-3.32c.12-.22.07-.47-.12-.61l-2.01-1.58zM12 15.6c-1.98 0-3.6-1.62-3.6-3.6s1.62-3.6 3.6-3.6 3.6 1.62 3.6 3.6-1.62 3.6-3.6 3.6z"/>
          </svg>
          Pipeline Control
        </div>
      </nav>

      {/* Library */}
      <div className="sidebar-section-label">Your Library</div>
      <div className="sidebar-playlist-list">
        {playlists.map(pl => (
          <div
            key={pl.id}
            className={`sidebar-playlist-item ${selectedId === pl.id && view === 'playlist' ? 'active' : ''}`}
            onClick={() => { onSelect(pl.id); onViewChange('playlist') }}
            id={`playlist-item-${pl.id}`}
          >
            <PlaylistThumb playlist={pl} />
            <div className="sidebar-playlist-info">
              <div className="sidebar-playlist-name">{pl.name}</div>
              <div className="sidebar-playlist-meta">
                {PLAYLIST_TYPE_LABEL[pl.window_type] || pl.window_type} · {(pl.tracks ?? []).length}
              </div>
            </div>
          </div>
        ))}

        {playlists.length === 0 && (
          <div style={{ padding: '20px 12px', color: 'var(--text-muted)', fontSize: 13, textAlign: 'center' }}>
            No playlists yet.<br />Run the nightly pipeline to generate them.
          </div>
        )}
      </div>
    </aside>
  )
}
