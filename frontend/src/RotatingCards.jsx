import { useEffect, useRef, useState } from 'react'
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
    <div
      className={`playlist-artwork ${className}`}
      style={{ '--artwork-color': fallbackColor }}
    >
      {image ? (
        <img
          src={image}
          alt=""
          onError={event => { event.currentTarget.style.display = 'none' }}
          loading="lazy"
        />
      ) : (
        <div className="playlist-artwork-fallback">
          {playlist.window_type === 'recommendation' ? <IconStar size={52} />
            : playlist.window_type === 'all_time' ? <IconMusic size={52} />
              : <IconPlaylist size={52} />}
        </div>
      )}
      <div className="playlist-artwork-shade" />
    </div>
  )
}

function PlaylistCardFace({ playlist }) {
  const typeLabel = PLAYLIST_TYPE_LABEL[playlist.window_type] || playlist.window_type
  const trackCount = (playlist.tracks ?? []).length

  return (
    <div className="rotating-playlist-card">
      <PlaylistArtwork playlist={playlist} />
      <div className="rotating-playlist-card-info">
        <span className="playlist-card-type-badge">{typeLabel}</span>
        <strong>{playlist.name}</strong>
        <span>{trackCount} {trackCount === 1 ? 'song' : 'songs'}</span>
      </div>
    </div>
  )
}

/**
 * A small, dependency-free version of the React Bits Rotating Cards API.
 * It keeps the same core props while adding keyboard, wheel, and pointer controls.
 */
export default function RotatingCards({
  cards = [],
  radius = 290,
  duration = 24,
  cardWidth = 188,
  cardHeight = 252,
  pauseOnHover = true,
  reverse = false,
  draggable = true,
  autoPlay = true,
  onCardClick,
  onActiveChange,
  mouseWheel = true,
  className = '',
  cardClassName = '',
  initialRotation = 0,
}) {
  const [rotation, setRotation] = useState(initialRotation)
  const [dragging, setDragging] = useState(false)
  const [hovered, setHovered] = useState(false)
  const dragRef = useRef(null)
  const suppressClickRef = useRef(false)
  const rotationRef = useRef(initialRotation)

  const count = cards.length
  const step = count > 0 ? 360 / count : 0
  const activeIndex = count > 0 ? mod(Math.round(rotation / step), count) : 0
  const isAutoPlaying = autoPlay && count > 1 && !dragging && !(pauseOnHover && hovered)

  useEffect(() => {
    rotationRef.current = rotation
  }, [rotation])

  useEffect(() => {
    onActiveChange?.(activeIndex)
  }, [activeIndex, onActiveChange])

  useEffect(() => {
    if (!isAutoPlaying) return undefined

    let frameId
    let lastTime = performance.now()
    const direction = reverse ? -1 : 1
    const tick = now => {
      const elapsed = Math.min(now - lastTime, 80)
      lastTime = now
      setRotation(value => value + direction * elapsed * (360 / (duration * 1000)))
      frameId = requestAnimationFrame(tick)
    }

    frameId = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(frameId)
  }, [duration, isAutoPlaying, reverse])

  const rotateBy = (amount, animate = true) => {
    if (!count) return
    setRotation(value => {
      const next = value + amount * step
      return animate ? next : Math.round(next / step) * step
    })
  }

  const bringToCenter = index => {
    if (!count) return
    const current = activeIndex
    let delta = index - current
    if (delta > count / 2) delta -= count
    if (delta < -count / 2) delta += count
    rotateBy(delta)
  }

  const snapToNearest = () => {
    if (!count) return
    setRotation(value => Math.round(value / step) * step)
  }

  const handlePointerDown = event => {
    if (!draggable || count < 2) return
    event.currentTarget.setPointerCapture?.(event.pointerId)
    dragRef.current = {
      pointerId: event.pointerId,
      startX: event.clientX,
      startRotation: rotationRef.current,
      moved: false,
    }
    setDragging(true)
  }

  const handlePointerMove = event => {
    const drag = dragRef.current
    if (!drag || drag.pointerId !== event.pointerId) return
    const distance = event.clientX - drag.startX
    if (Math.abs(distance) > 8) drag.moved = true
    if (drag.moved) event.preventDefault()
    setRotation(drag.startRotation + distance * 0.52)
  }

  const handlePointerUp = event => {
    const drag = dragRef.current
    if (!drag || drag.pointerId !== event.pointerId) return
    suppressClickRef.current = drag.moved
    dragRef.current = null
    setDragging(false)
    snapToNearest()
    if (suppressClickRef.current) {
      window.setTimeout(() => { suppressClickRef.current = false }, 0)
    }
  }

  const handleWheel = event => {
    if (!mouseWheel || count < 2) return
    event.preventDefault()
    rotateBy(event.deltaY > 0 ? 1 : -1)
  }

  const handleCardKeyDown = (event, index) => {
    if (event.key === 'ArrowRight' || event.key === 'ArrowDown') {
      event.preventDefault()
      rotateBy(1)
    } else if (event.key === 'ArrowLeft' || event.key === 'ArrowUp') {
      event.preventDefault()
      rotateBy(-1)
    } else if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault()
      if (index !== activeIndex) bringToCenter(index)
      else onCardClick?.(cards[index], index)
    }
  }

  const cardElements = cards.map((card, index) => {
    const angle = index * step - rotation
    const shortestAngle = Math.abs((((angle + 180) % 360) + 360) % 360 - 180)
    const isActive = index === activeIndex
    const style = {
      width: cardWidth,
      height: cardHeight,
      transform: `translate(-50%, -50%) rotateY(${angle}deg) translateZ(${radius}px)`,
      zIndex: isActive ? 40 : Math.max(1, Math.round(30 - shortestAngle / 8)),
      opacity: shortestAngle > 150 ? 0.28 : 1,
    }

    return (
      <div
        key={card.id ?? index}
        className={`rotating-card ${isActive ? 'is-active' : ''} ${cardClassName}`}
        style={style}
        role="button"
        tabIndex={isActive ? 0 : -1}
        aria-label={card.ariaLabel || `Select ${card.id ?? `card ${index + 1}`}`}
        onClick={() => {
          if (suppressClickRef.current) return
          if (index !== activeIndex) bringToCenter(index)
          else onCardClick?.(card, index)
        }}
        onKeyDown={event => handleCardKeyDown(event, index)}
      >
        {card.content}
      </div>
    )
  })

  if (!count) return null

  return (
    <div
      className={`rotating-cards ${dragging ? 'is-dragging' : ''} ${isAutoPlaying ? 'is-auto-playing' : ''} ${className}`}
      style={{ '--rotating-card-width': `${cardWidth}px`, '--rotating-card-height': `${cardHeight}px` }}
      onPointerDown={handlePointerDown}
      onPointerMove={handlePointerMove}
      onPointerUp={handlePointerUp}
      onPointerCancel={handlePointerUp}
      onWheel={handleWheel}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      aria-label="Rotating playlist cards"
    >
      <div className="rotating-cards-stage">
        <div className="rotating-cards-orbit">
          {cardElements}
        </div>
      </div>
      <div className="rotating-cards-controls" aria-label="Carousel controls">
        <button type="button" className="carousel-arrow" onClick={() => rotateBy(-1)} aria-label="Previous playlist">‹</button>
        <div className="carousel-dots" aria-hidden="true">
          {cards.map((card, index) => (
            <span key={card.id ?? index} className={index === activeIndex ? 'is-active' : ''} />
          ))}
        </div>
        <button type="button" className="carousel-arrow" onClick={() => rotateBy(1)} aria-label="Next playlist">›</button>
      </div>
      <span className="rotating-cards-hint">Drag to rotate · scroll or use arrows</span>
    </div>
  )
}

export function PlaylistCarouselSection({ title, playlists, onSelect, onPlay }) {
  const [activeIndex, setActiveIndex] = useState(0)
  const safeActiveIndex = Math.min(activeIndex, Math.max(playlists.length - 1, 0))
  const activePlaylist = playlists[safeActiveIndex]
  const typeLabel = PLAYLIST_TYPE_LABEL[activePlaylist?.window_type] || activePlaylist?.window_type || ''
  const accentColor = PLAYLIST_TYPE_COLOR[activePlaylist?.window_type] || '#1db954'
  const trackCount = activePlaylist ? (activePlaylist.tracks ?? []).length : 0


  if (!activePlaylist) return null

  const cards = playlists.map(playlist => ({
    id: playlist.id,
    ariaLabel: `${playlist.name}, ${PLAYLIST_TYPE_LABEL[playlist.window_type] || playlist.window_type}`,
    content: <PlaylistCardFace playlist={playlist} />,
  }))

  return (
    <section className="playlist-carousel-section" aria-labelledby={`playlist-section-${title.replace(/\s+/g, '-').toLowerCase()}`}>
      <div className="playlist-section-heading">
        <div>
          <h2 id={`playlist-section-${title.replace(/\s+/g, '-').toLowerCase()}`} className="home-section-title">{title}</h2>
          <p className="playlist-section-subtitle">A rotating snapshot of your listening world</p>
        </div>
        <div className="playlist-section-status">
          <span className="playlist-section-status-label" style={{ '--status-color': accentColor }}>{typeLabel}</span>
          <span>{safeActiveIndex + 1} / {playlists.length}</span>
        </div>
      </div>

      <div className="playlist-carousel-viewport" style={{ '--focus-color': accentColor }}>
        <RotatingCards
          cards={cards}
          radius={Math.min(292, Math.max(205, playlists.length * 29))}
          duration={28}
          cardWidth={188}
          cardHeight={252}
          draggable
          autoPlay
          pauseOnHover
          mouseWheel
          onActiveChange={setActiveIndex}
          onCardClick={card => onSelect(card.id)}
        />

        <div className="playlist-focus-details" aria-live="polite">
          <span className="playlist-focus-eyebrow" style={{ color: accentColor }}>{typeLabel}</span>
          <h3>{activePlaylist.name}</h3>
          <p>{trackCount} {trackCount === 1 ? 'song' : 'songs'} <span aria-hidden="true">·</span> Curated from your listening history</p>
          <div className="playlist-focus-actions">
            <button type="button" className="playlist-focus-play" onClick={() => onPlay(activePlaylist)}>
              <IconPlay size={16} />
              Play mix
            </button>
            <button type="button" className="playlist-focus-open" onClick={() => onSelect(activePlaylist.id)}>
              View playlist
            </button>
          </div>
        </div>
      </div>
    </section>
  )
}
