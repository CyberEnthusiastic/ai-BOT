/**
 * Nova WebSocket client.
 *
 * Connects to ws://localhost:8000/ws (proxied by Vite in dev).
 * Provides typed send helpers and an event callback interface.
 */

export type WsState = 'connecting' | 'connected' | 'disconnected'

export interface NovaMessage {
  type: string
  [key: string]: unknown
}

export type MessageHandler = (msg: NovaMessage) => void

const WS_URL = `${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws`
const RECONNECT_DELAY_MS = 2500
const MAX_RECONNECT_DELAY_MS = 30_000

export class NovaWebSocket {
  private ws:      WebSocket | null = null
  private delay:   number = RECONNECT_DELAY_MS
  private stopped  = false

  private _onMessage: MessageHandler = () => {}
  private _onStateChange: (s: WsState) => void = () => {}

  constructor() {
    this._connect()
  }

  onMessage(fn: MessageHandler): void        { this._onMessage      = fn }
  onStateChange(fn: (s: WsState) => void): void { this._onStateChange = fn }

  // ── Send helpers ───────────────────────────────────────────────────────────

  send(msg: NovaMessage): void {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(msg))
    }
  }

  sendText(text: string): void {
    this.send({ type: 'text_input', text })
  }

  sendVoice(audiob64: string): void {
    this.send({ type: 'voice_input', audio: audiob64 })
  }

  sendApproval(approved: boolean): void {
    this.send({ type: 'approval', approved })
  }

  ping(): void {
    this.send({ type: 'ping' })
  }

  destroy(): void {
    this.stopped = true
    this.ws?.close()
  }

  // ── Connection management ─────────────────────────────────────────────────

  private _connect(): void {
    if (this.stopped) return

    this._onStateChange('connecting')
    const ws = new WebSocket(WS_URL)
    this.ws  = ws

    ws.onopen = () => {
      this.delay = RECONNECT_DELAY_MS
      this._onStateChange('connected')
    }

    ws.onmessage = (ev: MessageEvent) => {
      try {
        const msg: NovaMessage = JSON.parse(ev.data as string)
        this._onMessage(msg)
      } catch {
        console.warn('[WS] Received non-JSON message', ev.data)
      }
    }

    ws.onclose = () => {
      if (!this.stopped) {
        this._onStateChange('disconnected')
        this._scheduleReconnect()
      }
    }

    ws.onerror = () => {
      ws.close()
    }
  }

  private _scheduleReconnect(): void {
    if (this.stopped) return
    setTimeout(() => this._connect(), this.delay)
    this.delay = Math.min(this.delay * 1.5, MAX_RECONNECT_DELAY_MS)
  }
}
