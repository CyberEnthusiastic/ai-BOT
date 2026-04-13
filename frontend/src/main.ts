/**
 * Nova v2 — Frontend entry point.
 *
 * Wires together:
 *   NovaOrb       (Three.js particle sphere)
 *   NovaWebSocket (backend connection)
 *   AudioPlayer   (plays TTS audio, feeds amplitude to orb)
 *   VoiceCapture  (mic recording + Web Speech API)
 *
 * UI elements:
 *   #text-input   + #send-btn  → text commands
 *   #mic-btn                   → push-to-talk
 *   #transcript-inner          → conversation display
 *   #approval-panel            → yes/no approval prompts
 *   #status-text               → current Nova state label
 *   #connection-badge          → WS connection indicator
 */

import { NovaOrb, OrbState } from './orb'
import { NovaWebSocket, NovaMessage } from './websocket'
import { AudioPlayer } from './audio'
import { VoiceCapture } from './voice'

// ── DOM elements ──────────────────────────────────────────────────────────────
const canvas          = document.getElementById('orb-canvas') as HTMLCanvasElement
const statusText      = document.getElementById('status-text')!
const transcriptInner = document.getElementById('transcript-inner')!
const transcriptBox   = document.getElementById('transcript-box')!
const textInput       = document.getElementById('text-input') as HTMLInputElement
const sendBtn         = document.getElementById('send-btn') as HTMLButtonElement
const micBtn          = document.getElementById('mic-btn') as HTMLButtonElement
const approvalPanel   = document.getElementById('approval-panel')!
const approvalText    = document.getElementById('approval-text')!
const approveYes      = document.getElementById('approve-yes') as HTMLButtonElement
const approveNo       = document.getElementById('approve-no') as HTMLButtonElement
const connBadge       = document.getElementById('connection-badge')!

// ── Core modules ──────────────────────────────────────────────────────────────
const orb    = new NovaOrb(canvas)
const ws     = new NovaWebSocket()
const player = new AudioPlayer()
const voice  = new VoiceCapture()

// ── State ─────────────────────────────────────────────────────────────────────
let currentState: OrbState = 'idle'
let interimMsgEl: HTMLElement | null = null

// ── Orb animation loop ────────────────────────────────────────────────────────
orb.animate()

// Frame loop: feed audio amplitude to orb
function amplitudeLoop() {
  orb.setAmplitude(player.getAmplitude())
  requestAnimationFrame(amplitudeLoop)
}
amplitudeLoop()

// ── WebSocket event handlers ──────────────────────────────────────────────────

ws.onStateChange(wsState => {
  if (wsState === 'connected') {
    connBadge.className = 'online'
    connBadge.title     = 'Connected to Nova'
  } else {
    connBadge.className = 'offline'
    connBadge.title     = wsState === 'connecting' ? 'Connecting…' : 'Disconnected'
  }
})

ws.onMessage((msg: NovaMessage) => {
  switch (msg.type) {

    case 'connected':
      setStatus('idle')
      break

    case 'state': {
      const s = msg.state as OrbState
      setStatus(s)
      break
    }

    case 'thinking':
      setStatus('thinking')
      break

    case 'response': {
      const text  = msg.text  as string
      const audio = msg.audio as string
      setStatus('speaking')
      appendMessage('nova', text)
      if (audio) player.playBase64(audio)
      // After audio, drift back to idle (2s grace period)
      setTimeout(() => { if (currentState === 'speaking') setStatus('idle') }, 2200)
      if (msg.stop) {
        setTimeout(() => setStatus('idle'), 800)
      }
      break
    }

    case 'transcribed': {
      const t = msg.text as string
      if (t) {
        // Replace interim with final user message
        if (interimMsgEl) { interimMsgEl.remove(); interimMsgEl = null }
        appendMessage('user', t)
      }
      break
    }

    case 'approval_required': {
      const desc  = msg.description as string
      const level = msg.risk_level  as string
      const prompt = msg.prompt     as string | undefined
      showApprovalPanel(prompt ?? desc, level)
      setStatus('thinking')
      break
    }

    case 'blocked':
      appendMessage('nova', `⛔ ${msg.detail ?? 'Request blocked by guardrails.'}`)
      setStatus('error')
      setTimeout(() => setStatus('idle'), 2500)
      break

    case 'error':
      console.error('[WS] Server error:', msg.detail)
      setStatus('error')
      appendMessage('nova', `⚠ ${msg.detail ?? 'An error occurred.'}`)
      setTimeout(() => setStatus('idle'), 2500)
      break

    case 'pong':
      break

    default:
      console.debug('[WS] Unhandled message:', msg)
  }
})

// ── UI helpers ────────────────────────────────────────────────────────────────

function setStatus(state: OrbState): void {
  currentState = state
  orb.setState(state)

  const labels: Record<OrbState, string> = {
    idle:      'Ready',
    listening: 'Listening',
    thinking:  'Thinking',
    speaking:  'Speaking',
    error:     'Error',
  }

  statusText.textContent = labels[state]
  statusText.className   = `state-${state}`
}

function appendMessage(role: 'user' | 'nova', text: string): HTMLElement {
  const el = document.createElement('div')
  el.className = role === 'user' ? 'msg-user' : 'msg-nova'
  el.textContent = text
  transcriptInner.appendChild(el)
  transcriptBox.scrollTop = transcriptBox.scrollHeight
  return el
}

function showApprovalPanel(description: string, riskLevel: string): void {
  const icon = riskLevel === 'CRITICAL' ? '🔴' : '🟠'
  approvalText.textContent = `${icon} ${riskLevel}: ${description}`
  approvalPanel.classList.remove('hidden')
  approvalPanel.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
}

function hideApprovalPanel(): void {
  approvalPanel.classList.add('hidden')
}

// ── Send text command ─────────────────────────────────────────────────────────

function sendText(): void {
  const text = textInput.value.trim()
  if (!text) return
  appendMessage('user', text)
  ws.sendText(text)
  textInput.value = ''
  setStatus('thinking')
}

sendBtn.addEventListener('click', sendText)
textInput.addEventListener('keydown', (e: KeyboardEvent) => {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendText() }
})

// ── Approval buttons ──────────────────────────────────────────────────────────

approveYes.addEventListener('click', () => {
  hideApprovalPanel()
  ws.sendApproval(true)
  setStatus('thinking')
})

approveNo.addEventListener('click', () => {
  hideApprovalPanel()
  ws.sendApproval(false)
})

// ── Mic push-to-talk ──────────────────────────────────────────────────────────

micBtn.addEventListener('mousedown', async () => {
  micBtn.classList.add('recording')
  setStatus('listening')

  voice.onTranscript((text, isFinal) => {
    if (!isFinal) {
      if (!interimMsgEl) {
        interimMsgEl = appendMessage('user', text)
        interimMsgEl.style.opacity = '0.6'
      } else {
        interimMsgEl.textContent = text
      }
    }
  })

  voice.onAudio((b64) => {
    ws.sendVoice(b64)
    setStatus('thinking')
  })

  await voice.startRecording()
})

function stopMic(): void {
  if (voice.isRecording()) {
    voice.stopRecording()
    micBtn.classList.remove('recording')
    if (currentState === 'listening') setStatus('thinking')
  }
}

micBtn.addEventListener('mouseup',    stopMic)
micBtn.addEventListener('mouseleave', stopMic)

// Touch support for mobile
micBtn.addEventListener('touchstart', async (e) => {
  e.preventDefault()
  await voice.startRecording()
  micBtn.classList.add('recording')
  setStatus('listening')
}, { passive: false })

micBtn.addEventListener('touchend', (e) => {
  e.preventDefault()
  stopMic()
}, { passive: false })

// ── Periodic ping to keep WS alive ───────────────────────────────────────────
setInterval(() => ws.ping(), 25_000)

// ── Initial state ─────────────────────────────────────────────────────────────
setStatus('idle')
textInput.focus()
