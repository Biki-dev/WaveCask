import { thumbUrl } from './api'
import { usePlayer } from './PlayerContext'
import { PlaylistCarouselSection } from './RotatingCards'

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
                src={thumbUrl(vid, 'mqdefault')}
                alt={track.raw_title}
                onError={event => { event.currentTarget.style.display = 'none' }}
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


/* ── Home page ─────────────────────────────────────────────────── */
export default function HomePage({ playlists, onSelect }) {
  const { play } = usePlayer()

  const playPlaylist = playlist => {
    if ((playlist.tracks ?? []).length > 0) play(0, playlist.tracks)
  }
  const playFromPlaylist = (playlist, index) => {
    if ((playlist.tracks ?? []).length > 0) play(index, playlist.tracks)
  }

  const mixes = playlists.filter(p => ['today', 'day_of_week', 'month'].includes(p.window_type))
  const discover = playlists.filter(p => p.window_type === 'recommendation')
  const context = playlists.filter(p => ['context', 'all_time'].includes(p.window_type))
  const moods = playlists.filter(p => p.window_type === 'mood')

  const greetingHour = new Date().getHours()
  const greeting = greetingHour < 12 ? 'Good morning' : greetingHour < 17 ? 'Good afternoon' : 'Good evening'

  const sections = [
    { title: 'Discover', playlists: discover },
    { title: 'Your Mixes', playlists: mixes },
    { title: 'Mood Mixes', playlists: moods },
    { title: 'Made for you', playlists: context },
  ]

  return (
    <div>
      <div className="content-header home-header">
        <h1 className="content-header-title small" style={{ fontSize: 36, letterSpacing: -1 }}>
          {greeting} 👋
        </h1>
        <div className="content-header-meta" style={{ marginTop: 4 }}>
          Your AI-powered music hub, built from your listening history
        </div>
      </div>

      <div className="content-body">
        {playlists.length > 0 && (
          <>
            <h2 className="home-section-title">Jump back in</h2>
            <QuickPicksRow playlists={playlists} onPlayFromPlaylist={playFromPlaylist} />
          </>
        )}

        {sections.map(section => section.playlists.length > 0 ? (
          <PlaylistCarouselSection
            key={section.title}
            title={section.title}
            playlists={section.playlists}
            onSelect={onSelect}
            onPlay={playPlaylist}
          />
        ) : null)}
      </div>
    </div>
  )
}

