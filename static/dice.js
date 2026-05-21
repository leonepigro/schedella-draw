/* SchedellaDice — heptagonal prism die, axis=X, multi-axis tumble */
class SchedellaDice {
  constructor(canvas, labels) {
    this.canvas = canvas;
    this.labels = labels;
    this.N = labels.length;

    const W = canvas.clientWidth  || 300;
    const H = canvas.clientHeight || 300;

    this.renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
    this.renderer.setPixelRatio(window.devicePixelRatio);
    this.renderer.setSize(W, H);

    this.scene = new THREE.Scene();
    this.camera = new THREE.PerspectiveCamera(38, W / H, 0.1, 100);
    this.camera.position.set(0, 2.2, 5.8);
    this.camera.lookAt(0, 0, 0);

    this.scene.add(new THREE.AmbientLight(0xffffff, 0.35));
    const key = new THREE.PointLight(0xfde68a, 5.5, 22);
    key.position.set(3, 7, 5);
    this.scene.add(key);
    const rim = new THREE.PointLight(0xf59e0b, 2.0, 16);
    rim.position.set(-5, -2, -3);
    this.scene.add(rim);
    const fill = new THREE.PointLight(0xffffff, 0.8, 14);
    fill.position.set(0, 5, -5);
    this.scene.add(fill);

    this._buildDie();

    this.rolling   = false;
    this.settling  = false;
    this.idle      = true;
    this.targetX   = null;
    this.onSettled = null;
    this.rollTime  = 0;

    this._animate();
  }

  _makeTexture(label, active) {
    const S = 256;
    const cv = document.createElement('canvas');
    cv.width = cv.height = S;
    const ctx = cv.getContext('2d');

    ctx.fillStyle = active ? '#1e1508' : '#0a0804';
    ctx.fillRect(0, 0, S, S);

    // Outer border
    const bw = active ? 12 : 5;
    ctx.strokeStyle = active ? '#f59e0b' : '#2a1d00';
    ctx.lineWidth = bw;
    ctx.strokeRect(bw / 2, bw / 2, S - bw, S - bw);

    // Inner glow when active
    if (active) {
      const grad = ctx.createRadialGradient(S / 2, S / 2, 0, S / 2, S / 2, S * 0.5);
      grad.addColorStop(0, 'rgba(253,230,138,0.18)');
      grad.addColorStop(1, 'rgba(245,158,11,0)');
      ctx.fillStyle = grad;
      ctx.fillRect(0, 0, S, S);
    }

    ctx.fillStyle = active ? '#fde68a' : '#4a3820';
    const fs = label.length > 4 ? 46 : (label.length > 2 ? 60 : 82);
    ctx.font = `900 ${fs}px monospace`;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText(label.toUpperCase(), S / 2, S / 2);

    return new THREE.CanvasTexture(cv);
  }

  _buildDie() {
    const N  = this.N;
    const R  = 1.0;   // compact radius — more square faces
    const HL = 0.70;  // half-length

    const pos = [], nor = [], uvs = [], idx = [];

    for (let i = 0; i < N; i++) {
      const a0   = (i       / N) * Math.PI * 2;
      const a1   = ((i + 1) / N) * Math.PI * 2;
      const aMid = (a0 + a1) / 2;

      const y0 = Math.sin(a0) * R,  z0 = Math.cos(a0) * R;
      const y1 = Math.sin(a1) * R,  z1 = Math.cos(a1) * R;
      const ny  = Math.sin(aMid),    nz = Math.cos(aMid);

      const b = pos.length / 3;
      pos.push(-HL, y0, z0,   HL, y0, z0,   HL, y1, z1,  -HL, y1, z1);
      nor.push(0, ny, nz,     0, ny, nz,     0, ny, nz,    0, ny, nz);
      uvs.push(0, 0,   1, 0,  1, 1,  0, 1);
      idx.push(b, b+1, b+2,   b, b+2, b+3);
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

    // Heptagonal end caps
    const capGeo = new THREE.CylinderGeometry(R * 0.97, R * 0.97, 0.04, N);
    const capMat = new THREE.MeshLambertMaterial({ color: 0x0d0a05 });
    const capL = new THREE.Mesh(capGeo, capMat);
    const capR = new THREE.Mesh(capGeo, capMat);
    capL.rotation.z = capR.rotation.z = Math.PI / 2;
    capL.position.x = -HL;
    capR.position.x =  HL;

    // Visible edges — die-like appearance
    const edgeGeo = new THREE.EdgesGeometry(geo, 1);
    const edgeMat = new THREE.LineBasicMaterial({ color: 0x5a3d00 });
    const edges = new THREE.LineSegments(edgeGeo, edgeMat);

    this.group = new THREE.Group();
    this.group.add(drum, capL, capR, edges);
    this.scene.add(this.group);

    this.group.rotation.x = (0.5 / N) * Math.PI * 2;
  }

  startRoll() {
    this.rolling   = true;
    this.settling  = false;
    this.idle      = false;
    this.rollTime  = 0;
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

    const aMid   = (fi + 0.5) / this.N * Math.PI * 2;
    let   target = aMid;
    const cur    = this.group.rotation.x;

    while (target <= cur)               target += Math.PI * 2;
    while (target - cur > Math.PI * 2) target -= Math.PI * 2;
    if (target - cur < Math.PI / 3)    target += Math.PI * 2;

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

  _animate() {
    requestAnimationFrame(() => this._animate());

    if (this.rolling) {
      this.rollTime += 0.055;
      this.group.rotation.x += 0.14;
      // Multi-axis wobble for realistic tumble
      this.group.rotation.y = Math.sin(this.rollTime * 1.8) * 0.28;
      this.group.rotation.z = Math.sin(this.rollTime * 1.3) * 0.16;
    } else if (this.settling) {
      const diff = this.targetX - this.group.rotation.x;
      // Damp Y/Z wobble
      this.group.rotation.y *= 0.86;
      this.group.rotation.z *= 0.86;
      if (Math.abs(diff) < 0.004) {
        this.group.rotation.x = this.targetX;
        this.group.rotation.y = 0;
        this.group.rotation.z = 0;
        this.settling = false;
        this.idle     = true;
        const cb = this.onSettled;
        this.onSettled = null;
        cb && cb();
      } else {
        this.group.rotation.x += diff * 0.08;
      }
    } else if (this.idle) {
      this.group.rotation.x += 0.004;
      this.group.rotation.y = Math.sin(Date.now() * 0.0005) * 0.06;
    }

    this.renderer.render(this.scene, this.camera);
  }
}
