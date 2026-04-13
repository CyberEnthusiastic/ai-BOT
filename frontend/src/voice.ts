/**
 * Browser-side voice capture using MediaRecorder + Web Speech API.
 *
 * Usage:
 *   const vc = new VoiceCapture()
 *   vc.onTranscript(text => console.log(text))          // real-time (Web Speech)
 *   vc.onAudio(b64 => novaWs.sendVoice(b64))            // send PCM to backend
 *   vc.startRecording()
 *   vc.stopRecording()
 */

export type TranscriptHandler = (text: string, final: boolean) => void
export type AudioHandler = (base64Audio: string) => void

export class VoiceCapture {
  private recognition: SpeechRecognition | null = null
  private recorder:    MediaRecorder | null = null
  private stream:      MediaStream | null = null
  private chunks:      Blob[] = []

  private _onTranscript: TranscriptHandler = () => {}
  private _onAudio:      AudioHandler      = () => {}

  onTranscript(fn: TranscriptHandler): void { this._onTranscript = fn }
  onAudio(fn: AudioHandler): void           { this._onAudio      = fn }

  async startRecording(): Promise<void> {
    // ── MediaRecorder for sending audio to backend ─────────────────────────
    try {
      this.stream = await navigator.mediaDevices.getUserMedia({ audio: true, video: false })
      this.chunks = []
      const mimeType = MediaRecorder.isTypeSupported('audio/webm;codecs=opus')
        ? 'audio/webm;codecs=opus'
        : 'audio/webm'
      this.recorder = new MediaRecorder(this.stream, { mimeType })
      this.recorder.ondataavailable = (e: BlobEvent) => {
        if (e.data.size > 0) this.chunks.push(e.data)
      }
      this.recorder.onstop = () => this._handleRecordingStop()
      this.recorder.start()
    } catch (err) {
      console.warn('[Voice] MediaRecorder error:', err)
    }

    // ── Web Speech API for real-time transcript display ────────────────────
    const SpeechRec = window.SpeechRecognition ?? window.webkitSpeechRecognition
    if (SpeechRec) {
      this.recognition = new SpeechRec()
      this.recognition.continuous     = false
      this.recognition.interimResults = true
      this.recognition.lang           = 'en-US'

      this.recognition.onresult = (ev: SpeechRecognitionEvent) => {
        let interim = ''
        let final   = ''
        for (let i = ev.resultIndex; i < ev.results.length; i++) {
          const res = ev.results[i]
          if (!res) continue
          if (res.isFinal) final   += (res[0]?.transcript ?? '')
          else             interim += (res[0]?.transcript ?? '')
        }
        if (final)   this._onTranscript(final, true)
        else if (interim) this._onTranscript(interim, false)
      }

      this.recognition.onerror = () => { /* ignore */ }
      this.recognition.start()
    }
  }

  stopRecording(): void {
    this.recognition?.stop()
    this.recognition = null

    if (this.recorder && this.recorder.state !== 'inactive') {
      this.recorder.stop()
    }
    this.stream?.getTracks().forEach(t => t.stop())
  }

  isRecording(): boolean {
    return this.recorder?.state === 'recording'
  }

  private _handleRecordingStop(): void {
    if (this.chunks.length === 0) return
    const blob = new Blob(this.chunks, { type: this.recorder?.mimeType ?? 'audio/webm' })
    const reader = new FileReader()
    reader.onloadend = () => {
      const result = reader.result as string
      // result = "data:audio/webm;base64,AAAA..."
      const b64 = result.split(',')[1] ?? ''
      if (b64) this._onAudio(b64)
    }
    reader.readAsDataURL(blob)
    this.chunks = []
  }
}

// Augment Window type for Safari's prefixed SpeechRecognition
declare global {
  interface Window {
    webkitSpeechRecognition?: typeof SpeechRecognition
  }
}
