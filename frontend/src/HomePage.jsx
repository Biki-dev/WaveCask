import { thumbUrl } from './api'
import { usePlayer } from './PlayerContext'
import { PlaylistCarouselSection } from './RotatingCards'

/* ── Home page ─────────────────────────────────────────────────── */
export default function HomePage({ playlists, onSelect }) {
  const { play } = usePlayer()

  const playPlaylist = playlist => {
    if ((playlist.tracks ?? []).length > 0) play(0, playlist.tracks)
  }
  const playFromPlaylist = (playlist, index) => {
    if ((playlist.tracks ?? []).length > 0) play(index, playlist.tracks)
  }

  return (
     <div>
        {/* ONE unified carousel for every playlist */}
        {playlists.length > 0 && (
          <PlaylistCarouselSection
            playlists={playlists}
            onSelect={onSelect}
            onPlay={playPlaylist}
          />
        )}
     
    </div>
  )
}