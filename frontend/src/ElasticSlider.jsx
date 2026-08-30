import { animate, motion, useMotionValue, useMotionValueEvent, useTransform } from 'motion/react'
import { useEffect, useRef, useState } from 'react'
import './ElasticSlider.css'

const MAX_OVERFLOW = 50

export default function ElasticSlider({
  defaultValue = 50,
  startingValue = 0,
  maxValue = 100,
  className = '',
  isStepped = false,
  stepSize = 1,
  leftIcon = <span aria-hidden="true">−</span>,
  rightIcon = <span aria-hidden="true">+</span>,
  onChange,
}) {
  return (
    <div className={`elastic-slider-container ${className}`}>
      <Slider
        defaultValue={defaultValue}
        startingValue={startingValue}
        maxValue={maxValue}
        isStepped={isStepped}
        stepSize={stepSize}
        leftIcon={leftIcon}
        rightIcon={rightIcon}
        onChange={onChange}
      />
    </div>
  )
}

function Slider({ defaultValue, startingValue, maxValue, isStepped, stepSize, leftIcon, rightIcon, onChange }) {
  const [value, setValue] = useState(defaultValue)
  const sliderRef = useRef(null)
  const [region, setRegion] = useState('middle')
  const clientX = useMotionValue(0)
  const overflow = useMotionValue(0)
  const scale = useMotionValue(1)

  useEffect(() => {
    setValue(defaultValue)
  }, [defaultValue])

  useEffect(() => {
    onChange?.(defaultValue)
  }, [defaultValue, onChange])

  useMotionValueEvent(clientX, 'change', latest => {
    if (!sliderRef.current) return
    const { left, right } = sliderRef.current.getBoundingClientRect()
    const distance = latest < left ? left - latest : latest > right ? latest - right : 0
    setRegion(latest < left ? 'left' : latest > right ? 'right' : 'middle')
    overflow.jump(decay(distance, MAX_OVERFLOW))
  })

  const handlePointerMove = event => {
    if (event.buttons <= 0 || !sliderRef.current) return
    const { left, width } = sliderRef.current.getBoundingClientRect()
    let nextValue = startingValue + ((event.clientX - left) / width) * (maxValue - startingValue)
    if (isStepped) nextValue = Math.round(nextValue / stepSize) * stepSize
    nextValue = Math.min(Math.max(nextValue, startingValue), maxValue)
    setValue(nextValue)
    onChange?.(nextValue)
    clientX.jump(event.clientX)
  }

  const handlePointerDown = event => {
    handlePointerMove(event)
    event.currentTarget.setPointerCapture(event.pointerId)
  }

  const handlePointerUp = () => {
    animate(overflow, 0, { type: 'spring', bounce: 0.5 })
  }

  const rangePercentage = maxValue === startingValue
    ? 0
    : ((value - startingValue) / (maxValue - startingValue)) * 100

  return (
    <>
      <motion.div
        className="elastic-slider-wrapper"
        onHoverStart={() => animate(scale, 1.12)}
        onHoverEnd={() => animate(scale, 1)}
        onTouchStart={() => animate(scale, 1.12)}
        onTouchEnd={() => animate(scale, 1)}
        style={{ scale, opacity: useTransform(scale, [1, 1.12], [0.75, 1]) }}
      >
        <motion.div
          className="elastic-slider-icon"
          animate={{ scale: region === 'left' ? [1, 1.3, 1] : 1, transition: { duration: 0.25 } }}
          style={{ x: useTransform(() => (region === 'left' ? -overflow.get() / scale.get() : 0)) }}
        >
          {leftIcon}
        </motion.div>

        <div
          ref={sliderRef}
          className="elastic-slider-root"
          onPointerMove={handlePointerMove}
          onPointerDown={handlePointerDown}
          onPointerUp={handlePointerUp}
          onPointerCancel={handlePointerUp}
          onLostPointerCapture={handlePointerUp}
          role="slider"
          aria-valuemin={startingValue}
          aria-valuemax={maxValue}
          aria-valuenow={Math.round(value)}
          aria-label="Volume"
          tabIndex={0}
          onKeyDown={event => {
            if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return
            event.preventDefault()
            const delta = event.key === 'ArrowLeft' ? -stepSize : stepSize
            const nextValue = Math.min(maxValue, Math.max(startingValue, value + delta))
            setValue(nextValue)
            onChange?.(nextValue)
          }}
        >
          <motion.div
            className="elastic-slider-track-wrapper"
            style={{
              scaleX: useTransform(() => {
                if (!sliderRef.current) return 1
                return 1 + overflow.get() / sliderRef.current.getBoundingClientRect().width
              }),
              scaleY: useTransform(overflow, [0, MAX_OVERFLOW], [1, 0.8]),
              transformOrigin: useTransform(() => {
                if (!sliderRef.current) return 'left'
                const { left, width } = sliderRef.current.getBoundingClientRect()
                return clientX.get() < left + width / 2 ? 'right' : 'left'
              }),
              height: useTransform(scale, [1, 1.12], [6, 9]),
              marginTop: useTransform(scale, [1, 1.12], [0, -1.5]),
              marginBottom: useTransform(scale, [1, 1.12], [0, -1.5]),
            }}
          >
            <div className="elastic-slider-track">
              <div className="elastic-slider-range" style={{ width: `${rangePercentage}%` }} />
            </div>
          </motion.div>
        </div>

        <motion.div
          className="elastic-slider-icon"
          animate={{ scale: region === 'right' ? [1, 1.3, 1] : 1, transition: { duration: 0.25 } }}
          style={{ x: useTransform(() => (region === 'right' ? overflow.get() / scale.get() : 0)) }}
        >
          {rightIcon}
        </motion.div>
      </motion.div>
      <span className="elastic-slider-value">{Math.round(value)}%</span>
    </>
  )
}

function decay(value, max) {
  if (max === 0) return 0
  const entry = value / max
  return 2 * (1 / (1 + Math.exp(-entry)) - 0.5) * max
}
