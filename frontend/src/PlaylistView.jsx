import { fmtDuration, fmtScore, PLAYLIST_TYPE_LABEL, thumbUrl } from './api'
import { usePlayer } from './PlayerContext'
import { IconPlay, IconPause, IconShuffle, IconMusic } from './Icons'

/* Tiny wave animation shown for the active row */
function PlayingWave() {
  return (
    <div className="playing-wave">
      <span /><span /><span /><span />
    </div>
  )
}

/* Score bar */
function ScoreBar({ value }) {
  const pct = Math.max(0, Math.min(1, value ?? 0)) * 100
  return (
    <div className="track-score">
      <div className="track-score-bar">
        <div className="track-score-fill" style={{ width: `${pct}%` }} />
      </div>
      <span>{Math.round(pct)}</span>
    </div>
  )
}

export default function PlaylistView({ playlist }) {
  const { play, currentTrack, playing } = usePlayer()

  if (!playlist) return null

  const tracks = playlist.tracks ?? []
  const playlistThumbs = tracks
    .slice(0, 4)
    .map(pt => thumbUrl(pt.track?.video_id || pt.video_id))

  const headerClass = `content-header ${playlist.window_type}-header`
  const typeLabel = PLAYLIST_TYPE_LABEL[playlist.window_type] || playlist.window_type

  const playAll = (startIndex = 0) => {
    play(startIndex, tracks)
  }

  const shuffleAll = () => {
    const shuffled = [...tracks].sort(() => Math.random() - 0.5)
    play(0, shuffled)
  }

  const isActiveTrack = (pt) => {
    const vid = pt.track?.video_id || pt.video_id
    const cur = currentTrack?.track?.video_id || currentTrack?.video_id
    return vid === cur
  }

  return (
    <div style={{ height: '100%' }}>
      {/* Header */}
      <div className={headerClass}>
        <div className="content-header-badge">{typeLabel}</div>
        <h1 className={`content-header-title ${playlist.name.length > 20 ? 'small' : ''}`}>
          {playlist.name}
        </h1>
        <div className="content-header-meta">
          <span style={{ color: 'var(--accent)', fontWeight: 700 }}>WaveCask</span>
          <span>·</span>
          <span>{tracks.length} songs</span>
        </div>
      </div>

      {/* Body */}
      <div className="content-body">
        {/* Action buttons */}
        <div className="playlist-actions">
          <button
            className="btn-play-large"
            onClick={() => {
              if (playing && isActiveTrack(tracks[0])) {
                // If first track is playing, just toggle
              }
              playAll(0)
            }}
            title="Play"
          >
            <IconPlay size={22} />
          </button>
          <button
            className="playlist-actions-shuffle ctrl-btn"
            onClick={shuffleAll}
            title="Shuffle play"
          >
            <IconShuffle size={24} />
          </button>
        </div>

        {/* Track list */}
        {tracks.length === 0 ? (
          <div className="empty-state">
            <IconMusic size={48} />
            <p>No tracks in this playlist yet.</p>
          </div>
        ) : (
          <>
            {/* Column headers */}
            <div className="track-list-header">
              <span>#</span>
              <span>Title</span>
              <span>Genre</span>
              <span>Score</span>
              <span>⏱</span>
            </div>

            {/* Track rows */}
            <div className="track-list">
              {tracks.map((pt, idx) => {
                const track = pt.track || pt
                const vid   = track.video_id
                const active = isActiveTrack(pt)

                return (
                  <div
                    key={vid + idx}
                    className={`track-row ${active ? 'active' : ''}`}
                    onClick={() => playAll(idx)}
                  >
                    {/* Number / play indicator */}
                    <div className="track-num">
                      {active && playing
                        ? <PlayingWave />
                        : (
                          <>
                            <span className="track-num-text">{idx + 1}</span>
                            <span className="track-num-play">
                              <IconPlay size={14} />
                            </span>
                          </>
                        )
                      }
                    </div>

                    {/* Thumbnail + title + artist */}
                    <div className="track-info">
                      <div className="track-thumb">
                        <img
                          src={`https://img.youtube.com/vi/${vid}/mqdefault.jpg`}
                          alt={track.raw_title}
                          onError={e => { e.target.style.display = 'none' }}
                          loading="lazy"
                        />
                      </div>
                      <div className="track-text">
                        <div className="track-title">
                          {track.song !== 'Unknown' ? track.song : track.raw_title}
                        </div>
                        <div className="track-artist">
                          {track.artist !== 'Unknown' ? track.artist : track.channel || '—'}
                        </div>
                      </div>
                    </div>

                    {/* Genre */}
                    <div className="track-album">
                      {track.genre && track.genre !== 'Unknown'
                        ? <span className="genre-badge">{track.genre}</span>
                        : <span style={{ color: 'var(--text-muted)' }}>—</span>
                      }
                    </div>

                    {/* Engagement score */}
                    <div>
                      <ScoreBar value={pt.mix_score} />
                    </div>

                    {/* Duration */}
                    <div className="track-duration">
                      {fmtDuration(track.duration_seconds)}
                    </div>
                  </div>
                )
              })}
            </div>
          </>
        )}
      </div>
    </div>
  )
}
