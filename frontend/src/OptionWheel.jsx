import { useCallback, useEffect, useRef, useState } from 'react'
import './OptionWheel.css'

const DEFAULT_ITEMS = ['Ambient', 'House', 'Techno', 'Jazz', 'Lo-Fi', 'Synthwave']

export default function OptionWheel({
  items = DEFAULT_ITEMS,
  defaultSelected = 0,
  onChange,
  textColor = '#8e8e8e',
  activeColor = '#ffffff',
  side = 'left',
  fontSize = 1.1,
  spacing = 1.75,
  curve = 1,
  tilt = 7,
  blur = 1.5,
  fade = 0.22,
  minOpacity = 0.08,
  smoothing = 180,
  inset = 32,
  loop = false,
  draggable = true,
  className = '',
}) {
  const rootRef = useRef(null)
  const itemRefs = useRef([])
  const positionRef = useRef(defaultSelected)
  const targetRef = useRef(defaultSelected)
  const selectedRef = useRef(defaultSelected)
  const frameRef = useRef(null)
  const lastFrameRef = useRef(0)
  const configRef = useRef({})
  const dragRef = useRef(null)
  const dragMovedRef = useRef(false)
  const wheelTimerRef = useRef(null)
  const onChangeRef = useRef(onChange)
  const [selectedIndex, setSelectedIndex] = useState(defaultSelected)
  const [isDragging, setIsDragging] = useState(false)

  onChangeRef.current = onChange
  configRef.current = {
    count: items.length,
    items,
    rowHeight: Math.max(fontSize * spacing * 16, 1),
    curve,
    tilt,
    blur,
    fade,
    minOpacity,
    side,
    loop,
    smoothing,
    draggable,
  }

  const runFrame = useCallback((now) => {
    const dt = Math.min((now - lastFrameRef.current) / 1000, 0.05)
    lastFrameRef.current = now
    const config = configRef.current
    const easing = 1 - Math.exp(-dt / Math.max(config.smoothing, 1) * 1000)
    const nextTarget = targetRef.current
    let nextPosition = positionRef.current + (nextTarget - positionRef.current) * easing
    if (Math.abs(nextTarget - nextPosition) < 0.001) nextPosition = nextTarget
    positionRef.current = nextPosition

    const radius = config.tilt > 0 ? config.rowHeight / ((config.tilt * Math.PI) / 180) : 0
    const mirror = config.side === 'right' ? -1 : 1
    itemRefs.current.forEach((element, index) => {
      if (!element) return
      let distance = index - nextPosition
      if (config.loop && config.count > 1) {
        distance = ((distance % config.count) + config.count) % config.count
        if (distance > config.count / 2) distance -= config.count
      }

      const angle = Math.max(-Math.PI / 2, Math.min(Math.PI / 2, distance * ((config.tilt * Math.PI) / 180)))
      const y = radius ? radius * Math.sin(angle) : distance * config.rowHeight
      const x = radius ? -mirror * radius * (1 - Math.cos(angle)) * config.curve : 0
      const rotation = radius ? (mirror * angle * 180) / Math.PI : 0
      const absoluteDistance = Math.abs(distance)
      element.style.transform = `translate(${x.toFixed(2)}px, calc(${y.toFixed(2)}px - 50%)) rotate(${rotation.toFixed(3)}deg)`
      element.style.opacity = String(Math.max(config.minOpacity, 1 - absoluteDistance * config.fade))
      element.style.filter = config.blur > 0 ? `blur(${(absoluteDistance * config.blur).toFixed(2)}px)` : 'none'
      element.style.setProperty('--option-wheel-progress', Math.max(0, 1 - Math.min(absoluteDistance, 1)).toFixed(4))
    })

    frameRef.current = Math.abs(nextTarget - nextPosition) < 0.001 ? null : requestAnimationFrame(runFrame)
  }, [])

  const startAnimation = useCallback(() => {
    if (frameRef.current !== null) cancelAnimationFrame(frameRef.current)
    lastFrameRef.current = performance.now()
    frameRef.current = requestAnimationFrame(runFrame)
  }, [runFrame])

  const applyTarget = useCallback((value, snap = true) => {
    const config = configRef.current
    if (!config.count) return
    let nextTarget = config.loop ? value : Math.min(Math.max(value, 0), config.count - 1)
    if (snap) nextTarget = Math.round(nextTarget)
    targetRef.current = nextTarget
    const index = ((Math.round(nextTarget) % config.count) + config.count) % config.count
    if (index !== selectedRef.current) {
      selectedRef.current = index
      setSelectedIndex(index)
      onChangeRef.current?.(index, config.items[index])
    }
    startAnimation()
  }, [startAnimation])

  useEffect(() => {
    if (!items.length) return undefined
    const element = rootRef.current
    const handleWheel = (event) => {
      event.preventDefault()
      const step = Math.max(-1, Math.min(1, event.deltaY / configRef.current.rowHeight))
      applyTarget(targetRef.current + step, false)
      clearTimeout(wheelTimerRef.current)
      wheelTimerRef.current = setTimeout(() => applyTarget(targetRef.current, true), 140)
    }
    element.addEventListener('wheel', handleWheel, { passive: false })
    return () => {
      element.removeEventListener('wheel', handleWheel)
      clearTimeout(wheelTimerRef.current)
    }
  }, [applyTarget, items.length])

  useEffect(() => {
    selectedRef.current = Math.min(Math.max(defaultSelected, 0), Math.max(items.length - 1, 0))
    targetRef.current = selectedRef.current
    positionRef.current = selectedRef.current
    setSelectedIndex(selectedRef.current)
    startAnimation()
  }, [defaultSelected, items, startAnimation])

  useEffect(() => () => {
    if (frameRef.current !== null) cancelAnimationFrame(frameRef.current)
    clearTimeout(wheelTimerRef.current)
  }, [])

  const handlePointerDown = (event) => {
    if (!configRef.current.draggable) return
    dragRef.current = { y: event.clientY, start: targetRef.current, pointerId: event.pointerId }
    dragMovedRef.current = false
    setIsDragging(true)
  }

  const handlePointerMove = (event) => {
    const drag = dragRef.current
    if (!drag) return
    const delta = event.clientY - drag.y
    if (!dragMovedRef.current && Math.abs(delta) > 4) {
      dragMovedRef.current = true
      rootRef.current?.setPointerCapture(drag.pointerId)
    }
    if (dragMovedRef.current) applyTarget(drag.start - delta / configRef.current.rowHeight, false)
  }

  const handlePointerEnd = () => {
    if (!dragRef.current) return
    dragRef.current = null
    setIsDragging(false)
    if (dragMovedRef.current) applyTarget(targetRef.current, true)
  }

  const handleItemClick = (index) => {
    if (dragMovedRef.current) return
    applyTarget(index, true)
  }

  const handleKeyDown = (event) => {
    if (event.key !== 'ArrowUp' && event.key !== 'ArrowDown' && event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return
    event.preventDefault()
    applyTarget(Math.round(targetRef.current) + (event.key === 'ArrowUp' || event.key === 'ArrowLeft' ? -1 : 1), true)
  }

  return (
    <div
      ref={rootRef}
      role="listbox"
      tabIndex={0}
      aria-label="Library playlists"
      className={`option-wheel${side === 'right' ? ' option-wheel--right' : ''}${isDragging ? ' option-wheel--dragging' : ''}${className ? ` ${className}` : ''}`}
      style={{
        '--option-wheel-text': textColor,
        '--option-wheel-active': activeColor,
        '--option-wheel-font-size': `${fontSize}rem`,
        '--option-wheel-inset': `${inset}px`,
      }}
      onPointerDown={handlePointerDown}
      onPointerMove={handlePointerMove}
      onPointerUp={handlePointerEnd}
      onPointerCancel={handlePointerEnd}
      onKeyDown={handleKeyDown}
    >
      {items.map((item, index) => (
        <div
          key={`${item}-${index}`}
          ref={(element) => { itemRefs.current[index] = element }}
          role="option"
          aria-selected={selectedIndex === index}
          className={`option-wheel__item${selectedIndex === index ? ' option-wheel__item--selected' : ''}`}
          onClick={() => handleItemClick(index)}
        >
          {item}
        </div>
      ))}
    </div>
  )
}
