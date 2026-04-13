/**
 * Audio module.
 *
 * - Plays base64-encoded MP3 audio received from the Nova backend.
 * - Exposes getAmplitude() via a Web Audio AnalyserNode so the orb can
 *   react to Nova's speech in real-time.
 */

const FFT_SIZE = 256

export class AudioPlayer {
  private ctx:      AudioContext | null = null
  private analyser: AnalyserNode  | null = null
  private dataArr:  Uint8Array    | null = null
  private playing   = false

  private _ensureCtx(): AudioContext {
    if (!this.ctx) {
      this.ctx     = new AudioContext()
      this.analyser = this.ctx.createAnalyser()
      this.analyser.fftSize = FFT_SIZE
      this.dataArr  = new Uint8Array(this.analyser.frequencyBinCount)
      this.analyser.connect(this.ctx.destination)
    }
    return this.ctx
  }

  /**
   * Decode and play a base64-encoded MP3/audio blob.
   * Returns immediately; playback is async.
   */
  async playBase64(b64: string): Promise<void> {
    if (!b64) return

    const ctx = this._ensureCtx()
    if (ctx.state === 'suspended') {
      await ctx.resume()
    }

    try {
      const binary  = atob(b64)
      const bytes   = new Uint8Array(binary.length)
      for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i)

      const audioBuffer = await ctx.decodeAudioData(bytes.buffer)
      const source      = ctx.createBufferSource()
      source.buffer     = audioBuffer
      source.connect(this.analyser!)
      source.start(0)
      this.playing = true
      source.onended = () => { this.playing = false }
    } catch (err) {
      console.warn('[Audio] Playback failed:', err)
    }
  }

  /**
   * Return normalised amplitude 0..1 from the analyser.
   * Safe to call every frame even if nothing is playing.
   */
  getAmplitude(): number {
    if (!this.analyser || !this.dataArr || !this.playing) return 0

    this.analyser.getByteFrequencyData(this.dataArr)

    // Average the low-frequency bins (voice range is 80–3000 Hz)
    const binCount = this.dataArr.length
    const voiceBins = Math.floor(binCount * 0.35)
    let sum = 0
    for (let i = 0; i < voiceBins; i++) sum += this.dataArr[i]!
    return Math.min(1, (sum / voiceBins) / 200)
  }

  isPlaying(): boolean {
    return this.playing
  }
}
