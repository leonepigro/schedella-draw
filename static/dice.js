/* SchedellaDice — 7-sided prism die */
class SchedellaDice {
  constructor(canvas, labels) {
    this.canvas = canvas;
    this.labels = labels;           // e.g. ['1','X','2','under','over','gol','no gol']
    this.N = labels.length;

    const W = canvas.clientWidth  || 300;
    const H = canvas.clientHeight || 300;

    this.renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
    this.renderer.setPixelRatio(window.devicePixelRatio);
    this.renderer.setSize(W, H);

    this.scene = new THREE.Scene();
    this.camera = new THREE.PerspectiveCamera(42, W / H, 0.1, 100);
    this.camera.position.set(0, 1.0, 5.5);
    this.camera.lookAt(0, 0, 0);

    this.scene.add(new THREE.AmbientLight(0xffffff, 0.45));
    const key = new THREE.PointLight(0xfde68a, 2.5, 20);
    key.position.set(3, 5, 4);
    this.scene.add(key);
    const rim = new THREE.PointLight(0xf59e0b, 0.8, 15);
    rim.position.set(-4, -2, -2);
    this.scene.add(rim);

    this._buildPrism();

    // State
    this.rolling   = false;
    this.settling  = false;
    this.idle      = true;
    this.targetY   = null;
    this.onSettled = null;

    this._animate();
  }

  // ── Texture ──────────────────────────────────────────────────────────────
  _makeTexture(label, active) {
    const S = 256;
    const cv = document.createElement('canvas');
    cv.width = cv.height = S;
    const ctx = cv.getContext('2d');

    // Background
    ctx.fillStyle = active ? '#2d2410' : '#12100a';
    ctx.fillRect(0, 0, S, S);

    // Border
    const bw = active ? 10 : 4;
    ctx.strokeStyle = active ? '#f59e0b' : '#2d2410';
    ctx.lineWidth = bw;
    ctx.beginPath();
    const r = 20;
    ctx.moveTo(r, bw / 2);
    ctx.lineTo(S - r, bw / 2);
    ctx.arcTo(S - bw/2, bw/2, S - bw/2, r, r);
    ctx.lineTo(S - bw/2, S - r);
    ctx.arcTo(S - bw/2, S - bw/2, S - r, S - bw/2, r);
    ctx.lineTo(r, S - bw/2);
    ctx.arcTo(bw/2, S - bw/2, bw/2, S - r, r);
    ctx.lineTo(bw/2, r);
    ctx.arcTo(bw/2, bw/2, r, bw/2, r);
    ctx.closePath();
    ctx.stroke();

    // Label
    ctx.fillStyle = active ? '#fde68a' : '#78716c';
    const fs = label.length > 4 ? 52 : (label.length > 2 ? 62 : 80);
    ctx.font = `900 ${fs}px monospace`;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText(label.toUpperCase(), S / 2, S / 2);

    return new THREE.CanvasTexture(cv);
  }

  // ── Geometry: N-sided prism with one material group per side face ────────
  _buildPrism() {
    const N = this.N;
    const R = 1.15;   // radius
    const H = 0.65;   // half-height

    const pos = [], nor = [], uvs = [], idx = [];

    for (let i = 0; i < N; i++) {
      const a0   = (i       / N) * Math.PI * 2;
      const a1   = ((i + 1) / N) * Math.PI * 2;
      const aMid = (a0 + a1) / 2;

      const x0 = Math.sin(a0) * R,  z0 = Math.cos(a0) * R;
      const x1 = Math.sin(a1) * R,  z1 = Math.cos(a1) * R;
      const nx  = Math.sin(aMid),    nz = Math.cos(aMid);

      const b = pos.length / 3;
      // 4 verts: BL, BR, TR, TL
      pos.push(x0, -H, z0,  x1, -H, z1,  x1, H, z1,  x0, H, z0);
      nor.push(nx, 0, nz,   nx, 0, nz,   nx, 0, nz,   nx, 0, nz);
      uvs.push(0,0,          1,0,          1,1,          0,1);
      idx.push(b, b+1, b+2,  b, b+2, b+3);
    }

    const geo = new THREE.BufferGeometry();
    geo.setIndex(idx);
    geo.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
    geo.setAttribute('normal',   new THREE.Float32BufferAttribute(nor, 3));
    geo.setAttribute('uv',       new THREE.Float32BufferAttribute(uvs, 2));
    for (let i = 0; i < N; i++) geo.addGroup(i * 6, 6, i);

    this.mats = this.labels.map(lbl =>
      new THREE.MeshLambertMaterial({ map: this._makeTexture(lbl, false) })
    );

    this.mesh = new THREE.Mesh(geo, this.mats);
    this.mesh.rotation.x = 0.28;   // slight forward tilt
    this.scene.add(this.mesh);
  }

  // ── Public API ────────────────────────────────────────────────────────────
  startRoll() {
    this.rolling  = true;
    this.settling = false;
    this.idle     = false;
    this.onSettled = null;
    // Reset all face textures to inactive
    this.labels.forEach((lbl, i) => {
      this.mats[i].map.dispose();
      this.mats[i].map = this._makeTexture(lbl, false);
      this.mats[i].needsUpdate = true;
    });
  }

  settleOn(pronostico, onComplete) {
    const idx = this.labels.findIndex(l => l.toLowerCase() === pronostico.toLowerCase());
    if (idx === -1) { onComplete && onComplete(); return; }

    // Face i normal is at aMid = (i+0.5)/N*2π from +Z in local space.
    // After rotation.y = θ, the face normal's Z component = cos(aMid + θ).
    // Face points at camera (+Z) when aMid + θ = 0  →  θ = -aMid
    const aMid = (idx + 0.5) / this.N * Math.PI * 2;
    let target = -aMid;

    // Advance target past current rotation so the die keeps spinning forward
    const cur = this.mesh.rotation.y;
    while (target <= cur)            target += Math.PI * 2;
    while (target - cur > Math.PI * 2) target -= Math.PI * 2;
    // Guarantee a visible settling arc (≥ 45°)
    if (target - cur < Math.PI * 0.25) target += Math.PI * 2;

    this.rolling   = false;
    this.settling  = true;
    this.targetY   = target;
    this.onSettled = () => {
      this.mats[idx].map.dispose();
      this.mats[idx].map = this._makeTexture(this.labels[idx], true);
      this.mats[idx].needsUpdate = true;
      onComplete && onComplete();
    };
  }

  // ── Render loop ──────────────────────────────────────────────────────────
  _animate() {
    requestAnimationFrame(() => this._animate());

    if (this.rolling) {
      this.mesh.rotation.y += 0.11;
    } else if (this.settling) {
      const diff = this.targetY - this.mesh.rotation.y;
      if (Math.abs(diff) < 0.005) {
        this.mesh.rotation.y = this.targetY;
        this.settling = false;
        this.idle     = true;
        const cb = this.onSettled;
        this.onSettled = null;
        cb && cb();
      } else {
        // Ease-out: faster when far, slower near target
        this.mesh.rotation.y += diff * 0.09;
      }
    } else if (this.idle) {
      this.mesh.rotation.y += 0.004;
    }

    this.renderer.render(this.scene, this.camera);
  }
}
