/* SchedellaDice — barrel die (cylindrical, axis=X, rolls toward camera) */
class SchedellaDice {
  constructor(canvas, labels) {
    this.canvas = canvas;
    this.labels = labels;
    this.N = labels.length; // 7

    const W = canvas.clientWidth  || 300;
    const H = canvas.clientHeight || 300;

    this.renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
    this.renderer.setPixelRatio(window.devicePixelRatio);
    this.renderer.setSize(W, H);

    this.scene = new THREE.Scene();
    this.camera = new THREE.PerspectiveCamera(36, W / H, 0.1, 100);
    this.camera.position.set(0, 1.8, 6);
    this.camera.lookAt(0, 0, 0);

    this.scene.add(new THREE.AmbientLight(0xffffff, 0.45));
    const key = new THREE.PointLight(0xfde68a, 3.5, 22);
    key.position.set(2, 7, 5);
    this.scene.add(key);
    const rim = new THREE.PointLight(0xf59e0b, 1.2, 14);
    rim.position.set(-4, -3, -3);
    this.scene.add(rim);

    this._buildBarrel();

    this.rolling  = false;
    this.settling = false;
    this.idle     = true;
    this.targetX  = null;
    this.onSettled = null;

    this._animate();
  }

  // ── Face texture ──────────────────────────────────────────────────────────
  _makeTexture(label, active) {
    const S = 256;
    const cv = document.createElement('canvas');
    cv.width = cv.height = S;
    const ctx = cv.getContext('2d');

    ctx.fillStyle = active ? '#2d2410' : '#0f0d08';
    ctx.fillRect(0, 0, S, S);

    const bw = active ? 10 : 4;
    ctx.strokeStyle = active ? '#f59e0b' : '#3d3010';
    ctx.lineWidth = bw;
    ctx.strokeRect(bw / 2, bw / 2, S - bw, S - bw);

    ctx.fillStyle = active ? '#fde68a' : '#78716c';
    const fs = label.length > 4 ? 48 : (label.length > 2 ? 62 : 82);
    ctx.font = `900 ${fs}px monospace`;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText(label.toUpperCase(), S / 2, S / 2);

    return new THREE.CanvasTexture(cv);
  }

  // ── Barrel geometry: axis=X, N rectangular side faces ─────────────────────
  // Vertex at angle a: (±H, R·sin(a), R·cos(a))
  // Face i normal: (0, sin(aMid), cos(aMid))
  // Face faces +Z (camera) when group.rotation.x = aMid = (i+0.5)/N·2π
  _buildBarrel() {
    const N = this.N;
    const R = 1.15;   // radius (height visible from front)
    const HL = 1.05;  // half-length (width left/right)

    const pos = [], nor = [], uvs = [], idx = [];

    for (let i = 0; i < N; i++) {
      const a0   = (i       / N) * Math.PI * 2;
      const a1   = ((i + 1) / N) * Math.PI * 2;
      const aMid = (a0 + a1) / 2;

      const y0 = Math.sin(a0) * R,  z0 = Math.cos(a0) * R;
      const y1 = Math.sin(a1) * R,  z1 = Math.cos(a1) * R;
      const ny  = Math.sin(aMid),    nz = Math.cos(aMid);

      const b = pos.length / 3;
      pos.push(-HL, y0, z0,  HL, y0, z0,  HL, y1, z1,  -HL, y1, z1);
      nor.push(0, ny, nz,    0, ny, nz,    0, ny, nz,    0, ny, nz);
      uvs.push(0, 0,  1, 0,  1, 1,  0, 1);
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

    const drum = new THREE.Mesh(geo, this.mats);

    // End caps (dark N-gon discs)
    const capGeo = new THREE.CylinderGeometry(R * 0.97, R * 0.97, 0.05, N);
    const capMat = new THREE.MeshLambertMaterial({ color: 0x1a160d });
    const capL = new THREE.Mesh(capGeo, capMat);
    const capR = new THREE.Mesh(capGeo, capMat);
    capL.rotation.z = capR.rotation.z = Math.PI / 2;
    capL.position.x = -HL;
    capR.position.x =  HL;

    // Group so caps rotate with the drum
    this.group = new THREE.Group();
    this.group.add(drum, capL, capR);
    this.scene.add(this.group);

    // Start with face 0 facing camera
    this.group.rotation.x = (0.5 / N) * Math.PI * 2;
  }

  // ── Public API ────────────────────────────────────────────────────────────
  startRoll() {
    this.rolling   = true;
    this.settling  = false;
    this.idle      = false;
    this.onSettled = null;
    this.labels.forEach((lbl, i) => {
      this.mats[i].map.dispose();
      this.mats[i].map = this._makeTexture(lbl, false);
      this.mats[i].needsUpdate = true;
    });
  }

  settleOn(pronostico, onComplete) {
    const fi = this.labels.findIndex(l => l.toLowerCase() === pronostico.toLowerCase());
    if (fi === -1) { onComplete && onComplete(); return; }

    // Face fi faces +Z when group.rotation.x = (fi+0.5)/N·2π
    const aMid   = (fi + 0.5) / this.N * Math.PI * 2;
    let   target = aMid;
    const cur    = this.group.rotation.x;

    // Keep rolling forward past current position
    while (target <= cur)                target += Math.PI * 2;
    while (target - cur > Math.PI * 2)  target -= Math.PI * 2;
    // Guarantee a visible settling arc (≥ 60°)
    if (target - cur < Math.PI / 3)     target += Math.PI * 2;

    this.rolling   = false;
    this.settling  = true;
    this.targetX   = target;
    this.onSettled = () => {
      this.mats[fi].map.dispose();
      this.mats[fi].map = this._makeTexture(this.labels[fi], true);
      this.mats[fi].needsUpdate = true;
      onComplete && onComplete();
    };
  }

  // ── Render loop ──────────────────────────────────────────────────────────
  _animate() {
    requestAnimationFrame(() => this._animate());

    if (this.rolling) {
      this.group.rotation.x += 0.13;
    } else if (this.settling) {
      const diff = this.targetX - this.group.rotation.x;
      if (Math.abs(diff) < 0.004) {
        this.group.rotation.x = this.targetX;
        this.settling = false;
        this.idle     = true;
        const cb = this.onSettled;
        this.onSettled = null;
        cb && cb();
      } else {
        // Ease-out: brakes quadratically
        this.group.rotation.x += diff * 0.08;
      }
    } else if (this.idle) {
      this.group.rotation.x += 0.005;
    }

    this.renderer.render(this.scene, this.camera);
  }
}
