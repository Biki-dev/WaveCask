import { fmtDuration } from './api'
import { usePlayer } from './PlayerContext'
import {
  IconPlay, IconPause, IconSkipNext, IconSkipPrev,
  IconShuffle, IconRepeat, IconRepeatOne,
  IconVolume, IconVolumeMute, IconMusic
} from './Icons'

function fmtTime(secs) {
  if (!secs || isNaN(secs)) return '0:00'
  const m = Math.floor(secs / 60)
  const s = Math.floor(secs % 60)
  return `${m}:${s.toString().padStart(2, '0')}`
}

export default function PlayerBar() {
  const {
    currentTrack, playing, loading, currentTime, duration,
    volume, muted, shuffle, repeat,
    togglePlay, nextTrack, prevTrack, seek, setVolume,
    dispatch,
  } = usePlayer()

  const track = currentTrack?.track ?? currentTrack
  const videoId = track?.video_id

  const thumbUrl = videoId
    ? `https://img.youtube.com/vi/${videoId}/mqdefault.jpg`
    : null

  const progress = duration > 0 ? (currentTime / duration) * 100 : 0

  const handleSeek = (e) => {
    const rect = e.currentTarget.getBoundingClientRect()
    const ratio = (e.clientX - rect.left) / rect.width
    seek(ratio * (duration || 0))
  }

  return (
    <div className="player-bar">
      {/* Left: current track */}
      <div className="player-track">
        <div className="player-thumb">
          {thumbUrl
            ? <img src={thumbUrl} alt={track?.song || track?.raw_title} onError={e => e.target.style.display='none'} />
            : <IconMusic size={28} />
          }
        </div>
        {track ? (
          <div className="player-track-text">
            <div className="player-track-name">{track.song !== 'Unknown' ? track.song : track.raw_title}</div>
            <div className="player-track-artist">{track.artist !== 'Unknown' ? track.artist : track.channel || '—'}</div>
          </div>
        ) : (
          <div className="player-track-text" style={{ color: 'var(--text-muted)', fontSize: 13 }}>
            Nothing playing
          </div>
        )}
      </div>

      {/* Center: controls + progress */}
      <div className="player-center">
        <div className="player-controls">
          <button
            className={`ctrl-btn ${shuffle ? 'active' : ''}`}
            onClick={() => dispatch({ type: 'TOGGLE_SHUFFLE' })}
            title="Shuffle"
          >
            <IconShuffle size={18} />
          </button>

          <button className="ctrl-btn" onClick={prevTrack} title="Previous">
            <IconSkipPrev size={22} />
          </button>

          <button className="ctrl-play" onClick={togglePlay} title={playing ? 'Pause' : 'Play'}>
            {loading
              ? <span style={{ width: 14, height: 14, border: '2px solid #000', borderTopColor: 'transparent', borderRadius: '50%', display: 'inline-block', animation: 'spin 0.6s linear infinite' }} />
              : playing ? <IconPause size={18} /> : <IconPlay size={18} />
            }
          </button>

          <button className="ctrl-btn" onClick={nextTrack} title="Next">
            <IconSkipNext size={22} />
          </button>

          <button
            className={`ctrl-btn ${repeat !== 'none' ? 'active' : ''}`}
            onClick={() => dispatch({ type: 'CYCLE_REPEAT' })}
            title={`Repeat: ${repeat}`}
          >
            {repeat === 'one' ? <IconRepeatOne size={18} /> : <IconRepeat size={18} />}
          </button>
        </div>

        {/* Progress bar */}
        <div className="player-progress">
          <span className="progress-time">{fmtTime(currentTime)}</span>
          <div className="progress-track" onClick={handleSeek} title="Seek">
            <div className="progress-fill" style={{ width: `${progress}%` }} />
            <div className="progress-thumb" style={{ left: `${progress}%` }} />
          </div>
          <span className="progress-time">{fmtTime(duration)}</span>
        </div>
      </div>

      {/* Right: volume */}
      <div className="player-right">
        <button
          className="ctrl-btn"
          onClick={() => dispatch({ type: 'TOGGLE_MUTE' })}
          title={muted ? 'Unmute' : 'Mute'}
        >
          {muted || volume === 0 ? <IconVolumeMute size={20} /> : <IconVolume size={20} />}
        </button>
        <div className="volume-control">
          <input
            type="range"
            min="0" max="1" step="0.01"
            value={muted ? 0 : volume}
            onChange={e => setVolume(parseFloat(e.target.value))}
            style={{ width: 80, accentColor: 'var(--accent)' }}
            title="Volume"
          />
        </div>
      </div>

      <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
    </div>
  )
}
