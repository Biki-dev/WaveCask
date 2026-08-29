import { createContext, useContext, useReducer, useRef, useCallback, useEffect } from 'react'
import { fetchAudioUrl } from './api'

const PlayerCtx = createContext(null)

const INITIAL = {
  queue:        [],       // array of track objects
  currentIndex: -1,       // index in queue
  playing:      false,
  loading:      false,
  error:        null,
  currentTime:  0,
  duration:     0,
  volume:       0.8,
  muted:        false,
  shuffle:      false,
  repeat:       'none',   // 'none' | 'one' | 'all'
  streamUrl:    null,
  toast:        null,
}

function reducer(state, action) {
  switch (action.type) {
    case 'SET_QUEUE':
      return { ...state, queue: action.queue, currentIndex: action.index ?? 0 }
    case 'SET_INDEX':
      return { ...state, currentIndex: action.index }
    case 'SET_PLAYING':
      return { ...state, playing: action.value }
    case 'SET_LOADING':
      return { ...state, loading: action.value }
    case 'SET_STREAM':
      return { ...state, streamUrl: action.url, loading: false }
    case 'SET_ERROR':
      return { ...state, error: action.msg, loading: false }
    case 'SET_TIME':
      return { ...state, currentTime: action.value }
    case 'SET_DURATION':
      return { ...state, duration: action.value }
    case 'SET_VOLUME':
      return { ...state, volume: action.value }
    case 'TOGGLE_MUTE':
      return { ...state, muted: !state.muted }
    case 'TOGGLE_SHUFFLE':
      return { ...state, shuffle: !state.shuffle }
    case 'CYCLE_REPEAT':
      return { ...state, repeat: state.repeat === 'none' ? 'all' : state.repeat === 'all' ? 'one' : 'none' }
    case 'SET_TOAST':
      return { ...state, toast: action.msg }
    case 'CLEAR_TOAST':
      return { ...state, toast: null }
    default:
      return state
  }
}

export function PlayerProvider({ children }) {
  const [state, dispatch] = useReducer(reducer, INITIAL)
  const audioRef = useRef(new Audio())
  const toastTimer = useRef(null)

  const showToast = useCallback((msg) => {
    dispatch({ type: 'SET_TOAST', msg })
    clearTimeout(toastTimer.current)
    toastTimer.current = setTimeout(() => dispatch({ type: 'CLEAR_TOAST' }), 3000)
  }, [])

  // Load stream URL when currentIndex changes
  const loadTrack = useCallback(async (track) => {
    if (!track) return
    dispatch({ type: 'SET_LOADING', value: true })
    dispatch({ type: 'SET_STREAM', url: null })
    audioRef.current.pause()
    audioRef.current.src = ''
    try {
      const data = await fetchAudioUrl(track.video_id || track.track?.video_id)
      dispatch({ type: 'SET_STREAM', url: data.stream_url })
      audioRef.current.src = data.stream_url
      audioRef.current.volume = state.volume
      audioRef.current.muted = state.muted
      audioRef.current.play().catch(e => console.warn('Autoplay blocked:', e))
      dispatch({ type: 'SET_PLAYING', value: true })
    } catch (e) {
      dispatch({ type: 'SET_ERROR', msg: e.message })
      showToast('⚠ Could not load audio: ' + e.message)
    }
  }, [state.volume, state.muted, showToast])

  // Wire audio events
  useEffect(() => {
    const audio = audioRef.current
    const onTime    = () => dispatch({ type: 'SET_TIME', value: audio.currentTime })
    const onLoaded  = () => dispatch({ type: 'SET_DURATION', value: audio.duration })
    const onEnded   = () => {
      if (state.repeat === 'one') { audio.currentTime = 0; audio.play(); return }
      nextTrack()
    }
    const onPlay    = () => dispatch({ type: 'SET_PLAYING', value: true })
    const onPause   = () => dispatch({ type: 'SET_PLAYING', value: false })

    audio.addEventListener('timeupdate', onTime)
    audio.addEventListener('loadedmetadata', onLoaded)
    audio.addEventListener('ended', onEnded)
    audio.addEventListener('play', onPlay)
    audio.addEventListener('pause', onPause)
    return () => {
      audio.removeEventListener('timeupdate', onTime)
      audio.removeEventListener('loadedmetadata', onLoaded)
      audio.removeEventListener('ended', onEnded)
      audio.removeEventListener('play', onPlay)
      audio.removeEventListener('pause', onPause)
    }
  }) // re-bind when state.repeat changes

  // Sync volume / mute changes to audio element
  useEffect(() => {
    audioRef.current.volume = state.volume
    audioRef.current.muted  = state.muted
  }, [state.volume, state.muted])

  const currentTrack = state.queue[state.currentIndex] ?? null

  const play = useCallback((trackOrIndex, queue) => {
    if (queue) {
      const idx = typeof trackOrIndex === 'number' ? trackOrIndex : queue.indexOf(trackOrIndex)
      dispatch({ type: 'SET_QUEUE', queue, index: idx >= 0 ? idx : 0 })
      loadTrack(queue[idx >= 0 ? idx : 0])
    } else if (typeof trackOrIndex === 'number') {
      dispatch({ type: 'SET_INDEX', index: trackOrIndex })
      loadTrack(state.queue[trackOrIndex])
    } else {
      // same queue, different track
      const idx = state.queue.findIndex(t => (t.video_id || t.track?.video_id) === (trackOrIndex.video_id || trackOrIndex.track?.video_id))
      if (idx !== -1) {
        dispatch({ type: 'SET_INDEX', index: idx })
        loadTrack(trackOrIndex)
      }
    }
  }, [state.queue, loadTrack])

  const togglePlay = useCallback(() => {
    if (state.playing) { audioRef.current.pause() }
    else               { audioRef.current.play().catch(() => {}) }
  }, [state.playing])

  const nextTrack = useCallback(() => {
    const q = state.queue
    if (!q.length) return
    let next
    if (state.shuffle) {
      next = Math.floor(Math.random() * q.length)
    } else {
      next = (state.currentIndex + 1) % q.length
    }
    dispatch({ type: 'SET_INDEX', index: next })
    loadTrack(q[next])
  }, [state.queue, state.currentIndex, state.shuffle, loadTrack])

  const prevTrack = useCallback(() => {
    const audio = audioRef.current
    if (audio.currentTime > 3) { audio.currentTime = 0; return }
    const q = state.queue
    if (!q.length) return
    const prev = (state.currentIndex - 1 + q.length) % q.length
    dispatch({ type: 'SET_INDEX', index: prev })
    loadTrack(q[prev])
  }, [state.queue, state.currentIndex, loadTrack])

  const seek = useCallback((secs) => {
    audioRef.current.currentTime = secs
    dispatch({ type: 'SET_TIME', value: secs })
  }, [])

  const setVolume = useCallback((v) => {
    dispatch({ type: 'SET_VOLUME', value: v })
  }, [])

  const value = {
    ...state,
    currentTrack,
    audioRef,
    play,
    togglePlay,
    nextTrack,
    prevTrack,
    seek,
    setVolume,
    showToast,
    dispatch,
  }

  return <PlayerCtx.Provider value={value}>{children}</PlayerCtx.Provider>
}

export const usePlayer = () => useContext(PlayerCtx)
