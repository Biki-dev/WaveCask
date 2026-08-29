import { thumbUrl, PLAYLIST_TYPE_LABEL } from './api'
import { getPlaylistImage } from './playlistImages'
import { IconPlay, IconPlaylist, IconStar, IconMusic } from './Icons'
import { usePlayer } from './PlayerContext'

/* ── Card background resolver ──────────────────────────────────── */
function CardBackground({ playlist }) {
  const customImg = getPlaylistImage(playlist)

  if (customImg) {
    return <img className="playlist-card-bg" src={customImg} alt="" loading="lazy" />
  }

  // Fallback: YouTube thumbnail collage from first 4 tracks
  const tracks = playlist.tracks ?? []
  const thumbs = tracks.slice(0, 4).map(pt => thumbUrl(pt.track?.video_id || pt.video_id))

  if (thumbs.length >= 4) {
    return (
      <div className="playlist-card-bg-fallback">
        {thumbs.map((t, i) => (
          <img key={i} src={t} alt="" onError={e => e.target.style.display = 'none'} loading="lazy" />
        ))}
      </div>
    )
  }

  if (thumbs.length >= 1) {
    return <img className="playlist-card-bg" src={thumbs[0]} alt="" loading="lazy" />
  }

  // Icon fallback
  return (
    <div className="playlist-card-bg-fallback-icon">
      {playlist.window_type === 'recommendation'
        ? <IconStar size={52} />
        : playlist.window_type === 'all_time'
          ? <IconMusic size={52} />
          : <IconPlaylist size={52} />
      }
    </div>
  )
}

/* ── Individual card ───────────────────────────────────────────── */
function PlaylistCard({ playlist, onSelect, onPlay }) {
  const typeLabel  = PLAYLIST_TYPE_LABEL[playlist.window_type] || playlist.window_type
  const tracks     = playlist.tracks ?? []
  const trackCount = tracks.length

  return (
    <div
      className="playlist-card"
      onClick={() => onSelect(playlist.id)}
      id={`home-card-${playlist.id}`}
    >
      {/* Full-bleed background */}
      <CardBackground playlist={playlist} />

      {/* Gradient vignette overlay */}
      <div className="playlist-card-overlay" />

      {/* Play button (appears on hover, above overlay) */}
      <button
        className="playlist-card-play"
        onClick={e => { e.stopPropagation(); onPlay(playlist) }}
        title={`Play ${playlist.name}`}
      >
        <svg width="20" height="20" viewBox="0 0 24 24" fill="black">
          <path d="M8 5v14l11-7z" />
        </svg>
      </button>

      {/* Info overlay – bottom of card */}
      <div className="playlist-card-info">
        <div className="playlist-card-type-badge">{typeLabel}</div>
        <div className="playlist-card-name">{playlist.name}</div>
        <div className="playlist-card-desc">
          {trackCount} {trackCount === 1 ? 'song' : 'songs'}
        </div>
      </div>
    </div>
  )
}

/* ── Quick picks row ───────────────────────────────────────────── */
function QuickPicksRow({ playlists, onPlayFromPlaylist }) {
  const allTracks = playlists.flatMap(p =>
    (p.tracks ?? []).slice(0, 3).map(pt => ({ ...pt, playlist: p }))
  ).filter(pt => pt.track?.video_id || pt.video_id)

  const picks = allTracks.slice(0, 8)

  return (
    <div className="quick-picks-grid">
      {picks.map((pt, i) => {
        const track = pt.track || pt
        const vid = track.video_id
        return (
          <div
            key={vid + i}
            className="quick-pick-item"
            onClick={() => onPlayFromPlaylist(pt.playlist, i)}
            title={track.song !== 'Unknown' ? track.song : track.raw_title}
          >
            <div className="quick-pick-thumb">
              <img
                src={`https://img.youtube.com/vi/${vid}/mqdefault.jpg`}
                alt={track.raw_title}
                onError={e => e.target.style.display = 'none'}
                loading="lazy"
              />
            </div>
            <span className="quick-pick-title">
              {track.song !== 'Unknown' ? track.song : track.raw_title}
            </span>
          </div>
        )
      })}
    </div>
  )
}

/* ── Section wrapper ───────────────────────────────────────────── */
function PlaylistSection({ title, playlists, onSelect, onPlay }) {
  return (
    <div style={{ marginBottom: 48 }}>
      <h2 className="home-section-title">{title}</h2>
      <div className="playlist-grid">
        {playlists.map(pl => (
          <PlaylistCard
            key={pl.id}
            playlist={pl}
            onSelect={onSelect}
            onPlay={onPlay}
          />
        ))}
      </div>
    </div>
  )
}

/* ── Home page ─────────────────────────────────────────────────── */
export default function HomePage({ playlists, onSelect }) {
  const { play } = usePlayer()

  const playPlaylist    = (pl) => { if ((pl.tracks ?? []).length > 0) play(0, pl.tracks) }
  const playFromPlaylist = (pl, idx) => { if ((pl.tracks ?? []).length > 0) play(idx, pl.tracks) }

  const mixes    = playlists.filter(p => ['today', 'day_of_week', 'month'].includes(p.window_type))
  const discover = playlists.filter(p => p.window_type === 'recommendation')
  const context  = playlists.filter(p => ['context', 'all_time'].includes(p.window_type))
  const moods    = playlists.filter(p => p.window_type === 'mood')

  const greetingHour = new Date().getHours()
  const greeting = greetingHour < 12 ? 'Good morning' : greetingHour < 17 ? 'Good afternoon' : 'Good evening'

  return (
    <div>
      {/* Header */}
      <div className="content-header home-header">
        <h1 className="content-header-title small" style={{ fontSize: 36, letterSpacing: -1 }}>
          {greeting} 👋
        </h1>
        <div className="content-header-meta" style={{ marginTop: 4 }}>
          Your AI-powered music hub, built from your listening history
        </div>
      </div>

      <div className="content-body">
        {/* Jump back in */}
        {playlists.length > 0 && (
          <>
            <h2 className="home-section-title">Jump back in</h2>
            <QuickPicksRow playlists={playlists} onPlayFromPlaylist={playFromPlaylist} />
          </>
        )}

        {discover.length > 0 && (
          <PlaylistSection title="Discover" playlists={discover} onSelect={onSelect} onPlay={playPlaylist} />
        )}
        {mixes.length > 0 && (
          <PlaylistSection title="Your Mixes" playlists={mixes} onSelect={onSelect} onPlay={playPlaylist} />
        )}
        {moods.length > 0 && (
          <PlaylistSection title="Mood Mixes" playlists={moods} onSelect={onSelect} onPlay={playPlaylist} />
        )}
        {context.length > 0 && (
          <PlaylistSection title="Made for you" playlists={context} onSelect={onSelect} onPlay={playPlaylist} />
        )}
      </div>
    </div>
  )
}
