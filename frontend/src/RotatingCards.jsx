import { useEffect, useRef, useState, useCallback } from 'react'
import { thumbUrl, PLAYLIST_TYPE_COLOR, PLAYLIST_TYPE_LABEL } from './api'
import { getPlaylistImage } from './playlistImages'
import { IconMusic, IconPlay, IconPlaylist, IconStar } from './Icons'

const mod = (value, length) => ((value % length) + length) % length

function getPlaylistArtwork(playlist) {
  const customImage = getPlaylistImage(playlist)
  if (customImage) return customImage
  const track = (playlist.tracks ?? []).find(item => item.track?.video_id || item.video_id)
  const videoId = track?.track?.video_id || track?.video_id
  return videoId ? thumbUrl(videoId, 'hqdefault') : null
}

export function PlaylistArtwork({ playlist, className = '' }) {
  const image = getPlaylistArtwork(playlist)
  const fallbackColor = PLAYLIST_TYPE_COLOR[playlist.window_type] || '#16382a'
  return (
    <button type="button" onClick={() => onSelect(activePlaylist.id)}>
    <div className={`playlist-artwork ${className}`} style={{ '--artwork-color': fallbackColor }}>
      {image ? (
        <img src={image} alt="" onError={e => { e.currentTarget.style.display = 'none' }} loading="lazy" />
      ) : (
        <div className="playlist-artwork-fallback">
          {playlist.window_type === 'recommendation' ? <IconStar size={52} />
            : playlist.window_type === 'all_time' ? <IconMusic size={52} />
              : <IconPlaylist size={52} />}
        </div>
      )}
      <div className="playlist-artwork-shade" />
    </div>
    </button>
  )
}

function PlaylistCardFace({ playlist }) {
  const trackCount = (playlist.tracks ?? []).length
  return (
    <div className="rotating-playlist-card">
      <PlaylistArtwork playlist={playlist} />
      <div className="rotating-playlist-card-info">
        <strong>{playlist.name}</strong>
        <span>{trackCount} {trackCount === 1 ? 'song' : 'songs'}</span>
      </div>
    </div>
  )
}

/* ── Half-Circle Arc Carousel ─────────────────────────────────── */
export default function RotatingCards({
  cards = [],
  radius = 280,
  cardWidth = 168,
  cardHeight = 222,
  visibleArc = 150,
  autoPlay = true,
  autoPlaySpeed = 0.35,
  pauseOnHover = true,
  draggable = true,
  onCardClick,
  onActiveChange,
  className = '',
}) {
  const [rotation, setRotation] = useState(0)
  const [dragging, setDragging] = useState(false)
  const [hovered, setHovered] = useState(false)
  const dragRef = useRef(null)
  const suppressClickRef = useRef(false)
  const rotationRef = useRef(0)
  const rafRef = useRef(null)

  const count = cards.length
  const step = count > 0 ? 360 / count : 0
  const activeIndex = count > 0 ? mod(Math.round(rotation / step), count) : 0
  const isAutoPlaying = autoPlay && count > 1 && !dragging && !(pauseOnHover && hovered)

  useEffect(() => { rotationRef.current = rotation }, [rotation])
  useEffect(() => { onActiveChange?.(activeIndex) }, [activeIndex, onActiveChange])

  useEffect(() => {
    if (!isAutoPlaying) {
      if (rafRef.current) cancelAnimationFrame(rafRef.current)
      return
    }
    let lastTime = performance.now()
    const tick = (now) => {
      const elapsed = Math.min(now - lastTime, 50)
      lastTime = now
      setRotation(v => v + autoPlaySpeed * elapsed * 0.06)
      rafRef.current = requestAnimationFrame(tick)
    }
    rafRef.current = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(rafRef.current)
  }, [isAutoPlaying, autoPlaySpeed])

  const snapToNearest = useCallback(() => {
    if (!count) return
    setRotation(v => Math.round(v / step) * step)
  }, [count, step])

  const rotateBy = useCallback((deltaIndex) => {
    if (!count) return
    setRotation(v => v + deltaIndex * step)
  }, [count, step])

  const bringToCenter = useCallback((index) => {
    if (!count) return
    const current = activeIndex
    let delta = index - current
    if (delta > count / 2) delta -= count
    if (delta < -count / 2) delta += count
    rotateBy(delta)
  }, [count, activeIndex, rotateBy])

  const handlePointerDown = (e) => {
    if (!draggable || count < 2 || e.target.closest('button')) return
    e.currentTarget.setPointerCapture?.(e.pointerId)
    dragRef.current = { pointerId: e.pointerId, startX: e.clientX, startRotation: rotationRef.current, moved: false }
    setDragging(true)
  }

  const handlePointerMove = (e) => {
    const drag = dragRef.current
    if (!drag || drag.pointerId !== e.pointerId) return
    const dist = e.clientX - drag.startX
    if (Math.abs(dist) > 5) drag.moved = true
    if (drag.moved) e.preventDefault()
    setRotation(drag.startRotation + dist * 0.35)
  }

  const handlePointerUp = (e) => {
    const drag = dragRef.current
    if (!drag || drag.pointerId !== e.pointerId) return
    suppressClickRef.current = drag.moved
    dragRef.current = null
    setDragging(false)
    snapToNearest()
    if (suppressClickRef.current) setTimeout(() => { suppressClickRef.current = false }, 0)
  }

  const handleWheel = (e) => {
    if (count < 2) return
    e.preventDefault()
    rotateBy(e.deltaY > 0 ? 1 : -1)
  }

  const halfArc = visibleArc / 2

  const cardElements = cards.map((card, index) => {
    let relAngle = (index * step) - (rotation % 360)
    while (relAngle > 180) relAngle -= 360
    while (relAngle < -180) relAngle += 360

    if (relAngle < -halfArc - 25 || relAngle > halfArc + 25) return null

    const radians = (relAngle * Math.PI) / 180
    const x = Math.sin(radians) * radius
    const y = - Math.cos(radians) * (radius * 0.88)

    const depth = Math.cos(radians)
    const scale = 0.68 + Math.max(0, depth) * 0.32
    const opacity = depth > -0.15 ? 0.45 + Math.max(0, depth) * 0.55 : 0
    const cardRotate = relAngle * 0.2
    const isActive = index === activeIndex

    return (
      <div
        key={card.id ?? index}
        className={`rotating-card ${isActive ? 'is-active' : ''}`}
        style={{
          position: 'absolute',
          left: '50%',
          top: '90%',
          width: cardWidth,
          height: cardHeight,
          transform: `translate(-50%, -50%) translate3d(${x}px, ${y}px, 0) rotate(${cardRotate}deg) scale(${scale})`,
          zIndex: Math.round(40 + depth * 35),
          opacity,
          transition: dragging ? 'none' : 'transform 0.55s cubic-bezier(0.23, 1, 0.32, 1), opacity 0.55s ease',
          cursor: 'pointer',
          willChange: 'transform',
        }}
        onClick={() => {
          if (suppressClickRef.current) return
          if (index !== activeIndex) bringToCenter(index)
          else onCardClick?.(card, index)
        }}
      >
        {card.content}
      </div>
    )
  }).filter(Boolean)

  if (!count) return null

  return (
    <div
      className={`rotating-cards arc-carousel ${dragging ? 'is-dragging' : ''} ${className}`}
      onPointerDown={handlePointerDown}
      onPointerMove={handlePointerMove}
      onPointerUp={handlePointerUp}
      onPointerCancel={handlePointerUp}
      onWheel={handleWheel}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      style={{ position: 'relative', width: '100%', height: '100%', overflow: 'hidden' }}
    >
      <div className="rotating-cards-stage" style={{ position: 'absolute', inset: 0 }}>
        {cardElements}
      </div>
    </div>
  )
}

/* ── Unified Playlist Section ─────────────────────────────────── */
export function PlaylistCarouselSection({ playlists, onSelect, onPlay }) {
  const [activeIndex, setActiveIndex] = useState(0)
  const safeActiveIndex = Math.min(activeIndex, Math.max(playlists.length - 1, 0))
  const activePlaylist = playlists[safeActiveIndex]

  if (!activePlaylist) return null

  const typeLabel = PLAYLIST_TYPE_LABEL[activePlaylist?.window_type] || activePlaylist?.window_type || ''
  const accentColor = PLAYLIST_TYPE_COLOR[activePlaylist?.window_type] || '#1db954'
  const trackCount = activePlaylist ? (activePlaylist.tracks ?? []).length : 0

  const cards = playlists.map(playlist => ({
    id: playlist.id,
    content: <PlaylistCardFace playlist={playlist} />,
  }))

  return (
    <section className="playlist-carousel-section">
      <div
        className="playlist-carousel-viewport"
        style={{
          '--focus-color': accentColor,
          display: 'flex',
          flexDirection: 'column',
          position: 'relative',
          height: '100%'
        }}
      >
        {/* Type label — upper area */}
        <div style={{ textAlign: 'center', padding: '22px 0 6px', zIndex: 60, position: 'relative' }}>
          <span
            className="playlist-focus-eyebrow"
            style={{ color: accentColor, fontSize: 12, letterSpacing: '0.14em' }}
          >
            {typeLabel}
          </span>
        </div>

        {/* Arc carousel */}
        <div style={{ position: 'relative', minHeight: 280 }}>
          <RotatingCards
            cards={cards}
            radius={360}
            cardWidth={168}
            cardHeight={222}
            visibleArc={150}
            draggable
            autoPlay
            pauseOnHover
            onActiveChange={setActiveIndex}
            onCardClick={card => onSelect(card.id)}
          />
        </div>

        {/* Black space — active playlist details */}
        <div
          style={{
            position: 'absolute',
            zIndex: 50,
            alignItems: 'center',
            textAlign: 'center',
          }}
        >
          <div
            className="playlist-focus-details"
            style={{
              position: 'relative',
              transform: 'none',
              left: '450px',
              top: '450px',
              margin: '0 auto',
              width: 'min(360px, 92%)',
              minWidth: 'auto',
              padding: '0px 22px',
              backdropFilter: 'blur(10px)',
            }}
          >
            <h3 style={{ fontSize: 'clamp(20px, 2.2vw, 28px)', margin: '0 0 6px' }}>
              {activePlaylist.name}
            </h3>
            <p style={{ margin: '0 0 14px', fontSize: 13, lineHeight: 1.5 }}>
              {trackCount} {trackCount === 1 ? 'song' : 'songs'}{' '}
              <span style={{ color: 'var(--text-muted)', padding: '0 5px' }}>·</span>
              Curated from your listening history
            </p>
          </div>
        </div>
      </div>
    </section>
  )
}