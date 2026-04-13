/**
 * Nova Orb — Three.js audio-reactive particle sphere.
 *
 * 5 000 particles arranged on a sphere using the Fibonacci lattice.
 * Each state drives colour, size, and motion differently:
 *
 *   idle      — dim blue, slow breath pulse, gentle drift
 *   listening — bright green, sphere expands, faster rotation
 *   thinking  — orange, particles spiral/swirl rapidly
 *   speaking  — cyan, particles pulse with audio amplitude
 *   error     — red, particles scatter outward then snap back
 */

import * as THREE from 'three'

export type OrbState = 'idle' | 'listening' | 'thinking' | 'speaking' | 'error'

// ── State colour palette ──────────────────────────────────────────────────────
const STATE_COLORS: Record<OrbState, THREE.Color> = {
  idle:      new THREE.Color(0x1a4fff),
  listening: new THREE.Color(0x00ff88),
  thinking:  new THREE.Color(0xff8800),
  speaking:  new THREE.Color(0x00e5ff),
  error:     new THREE.Color(0xff2244),
}

// ── Radius & scale per state ─────────────────────────────────────────────────
const STATE_RADIUS: Record<OrbState, number> = {
  idle:      1.0,
  listening: 1.18,
  thinking:  0.95,
  speaking:  1.05,
  error:     1.35,
}

const STATE_PARTICLE_SIZE: Record<OrbState, number> = {
  idle:      0.012,
  listening: 0.014,
  thinking:  0.011,
  speaking:  0.016,
  error:     0.018,
}

const PARTICLE_COUNT = 5000

export class NovaOrb {
  private scene:    THREE.Scene
  private camera:   THREE.PerspectiveCamera
  private renderer: THREE.WebGLRenderer

  private positions:    Float32Array   // base sphere positions
  private live:         Float32Array   // animated positions sent to GPU
  private geometry:     THREE.BufferGeometry
  private material:     THREE.PointsMaterial
  private points:       THREE.Points

  private state:        OrbState = 'idle'
  private targetColor:  THREE.Color = STATE_COLORS.idle.clone()
  private currentColor: THREE.Color = STATE_COLORS.idle.clone()

  private targetRadius:  number = STATE_RADIUS.idle
  private currentRadius: number = STATE_RADIUS.idle

  private clock = new THREE.Clock()
  private t = 0

  // Audio reactivity
  private amplitude = 0          // 0..1 from AudioAnalyser
  private errorTimer = 0         // countdown for error scatter

  constructor(canvas: HTMLCanvasElement) {
    // ── Renderer ───────────────────────────────────────────────────────────
    this.renderer = new THREE.WebGLRenderer({ canvas, antialias: false, alpha: true })
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2))
    this.renderer.setSize(canvas.clientWidth, canvas.clientHeight)
    this.renderer.setClearColor(0x000000, 0)

    // ── Scene & camera ─────────────────────────────────────────────────────
    this.scene  = new THREE.Scene()
    this.camera = new THREE.PerspectiveCamera(60, canvas.clientWidth / canvas.clientHeight, 0.1, 100)
    this.camera.position.set(0, 0, 3.2)

    // ── Geometry — Fibonacci sphere ────────────────────────────────────────
    this.positions = new Float32Array(PARTICLE_COUNT * 3)
    this.live       = new Float32Array(PARTICLE_COUNT * 3)
    _fibonacciSphere(PARTICLE_COUNT, 1.0, this.positions)
    this.live.set(this.positions)

    this.geometry = new THREE.BufferGeometry()
    this.geometry.setAttribute('position', new THREE.BufferAttribute(this.live, 3))

    // ── Material — additive blending for glow ─────────────────────────────
    this.material = new THREE.PointsMaterial({
      color:       STATE_COLORS.idle,
      size:        STATE_PARTICLE_SIZE.idle,
      sizeAttenuation: true,
      blending:    THREE.AdditiveBlending,
      depthWrite:  false,
      transparent: true,
      opacity:     0.85,
    })

    this.points = new THREE.Points(this.geometry, this.material)
    this.scene.add(this.points)

    // ── Resize observer ────────────────────────────────────────────────────
    window.addEventListener('resize', () => this._onResize(canvas))
  }

  // ── Public API ────────────────────────────────────────────────────────────

  setState(state: OrbState): void {
    if (this.state === state) return
    this.state       = state
    this.targetColor  = STATE_COLORS[state].clone()
    this.targetRadius = STATE_RADIUS[state]
    if (state === 'error') this.errorTimer = 1.5
  }

  setAmplitude(amp: number): void {
    this.amplitude = Math.min(1, Math.max(0, amp))
  }

  animate(): void {
    requestAnimationFrame(() => this.animate())
    const dt = this.clock.getDelta()
    this.t  += dt
    if (this.errorTimer > 0) this.errorTimer -= dt

    // ── Colour lerp ──────────────────────────────────────────────────────
    this.currentColor.lerp(this.targetColor, dt * 3.5)
    this.material.color.copy(this.currentColor)

    // ── Radius lerp ──────────────────────────────────────────────────────
    this.currentRadius += (this.targetRadius - this.currentRadius) * dt * 4.0

    // ── Particle size ────────────────────────────────────────────────────
    const targetSize = STATE_PARTICLE_SIZE[this.state] * (1 + this.amplitude * 0.6)
    this.material.size += (targetSize - this.material.size) * dt * 6

    // ── Opacity ──────────────────────────────────────────────────────────
    const targetOpacity = this.state === 'idle' ? 0.55 : 0.9
    this.material.opacity += (targetOpacity - this.material.opacity) * dt * 3

    // ── Per-particle animation ────────────────────────────────────────────
    this._animateParticles(dt)

    // ── Rotation ─────────────────────────────────────────────────────────
    const rotSpeed = {
      idle:      0.06,
      listening: 0.14,
      thinking:  0.35,
      speaking:  0.12,
      error:     0.5,
    }[this.state]

    this.points.rotation.y += dt * rotSpeed
    this.points.rotation.x  = Math.sin(this.t * 0.18) * 0.08

    this.geometry.attributes['position'].needsUpdate = true
    this.renderer.render(this.scene, this.camera)
  }

  // ── Private helpers ───────────────────────────────────────────────────────

  private _animateParticles(dt: number): void {
    const pos  = this.positions
    const live = this.live
    const t    = this.t

    for (let i = 0; i < PARTICLE_COUNT; i++) {
      const i3 = i * 3
      const bx = pos[i3]!,  by = pos[i3 + 1]!,  bz = pos[i3 + 2]!
      let x = bx, y = by, z = bz

      switch (this.state) {

        case 'idle': {
          // Slow breathing — radial scale oscillation
          const breathe = 1 + Math.sin(t * 0.8 + i * 0.001) * 0.04
          const r = this.currentRadius * breathe
          x = bx * r;  y = by * r;  z = bz * r
          break
        }

        case 'listening': {
          // Sphere expands with gentle shimmer per particle
          const shimmer = 1 + Math.sin(t * 2.0 + i * 0.007) * 0.03
          const r = this.currentRadius * shimmer
          x = bx * r;  y = by * r;  z = bz * r
          break
        }

        case 'thinking': {
          // Spiral vortex — particles swirl around Y axis
          const angle = t * 2.5 + i * (Math.PI * 2 / PARTICLE_COUNT) * 4
          const r     = this.currentRadius + Math.sin(t * 3 + i * 0.01) * 0.12
          const phi   = Math.acos(Math.max(-1, Math.min(1, by / Math.sqrt(bx*bx + by*by + bz*bz || 1))))
          const cx    = Math.cos(angle) * Math.sin(phi)
          const cz    = Math.sin(angle) * Math.sin(phi)
          const cy    = Math.cos(phi)
          x = cx * r;  y = cy * r;  z = cz * r
          break
        }

        case 'speaking': {
          // Audio-reactive radial pulse
          const pulse = 1 + this.amplitude * 0.3 * Math.sin(t * 8 + i * 0.05)
          const r = this.currentRadius * pulse
          x = bx * r;  y = by * r;  z = bz * r
          break
        }

        case 'error': {
          // Scatter outward, then snap back
          const scatter = this.errorTimer > 0
            ? Math.max(0, this.errorTimer / 1.5)   // 1 → 0 as timer ticks down
            : 0
          const scatterDir = scatter * (1.2 + (i % 7) * 0.08)
          const flash = Math.sin(t * 18) > 0 ? 1.2 : 0.7
          x = bx * (this.currentRadius + scatterDir) * flash
          y = by * (this.currentRadius + scatterDir) * flash
          z = bz * (this.currentRadius + scatterDir) * flash
          break
        }
      }

      live[i3]     = x
      live[i3 + 1] = y
      live[i3 + 2] = z
    }
  }

  private _onResize(canvas: HTMLCanvasElement): void {
    const w = canvas.clientWidth
    const h = canvas.clientHeight
    this.camera.aspect = w / h
    this.camera.updateProjectionMatrix()
    this.renderer.setSize(w, h)
  }
}

// ── Fibonacci lattice sphere ─────────────────────────────────────────────────
function _fibonacciSphere(n: number, r: number, out: Float32Array): void {
  const golden = Math.PI * (3 - Math.sqrt(5))
  for (let i = 0; i < n; i++) {
    const y     = 1 - (i / (n - 1)) * 2          // -1 .. 1
    const rSlice = Math.sqrt(Math.max(0, 1 - y * y))
    const theta  = golden * i
    const x = Math.cos(theta) * rSlice
    const z = Math.sin(theta) * rSlice
    out[i * 3]     = x * r
    out[i * 3 + 1] = y * r
    out[i * 3 + 2] = z * r
  }
}
