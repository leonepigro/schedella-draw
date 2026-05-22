/*
 * SchedellaDice — pentagonal prism (true 7-face heptahedron)
 *   faces 0-4  : 5 rectangular side faces (labels[0..4])
 *   faces 5-6  : 2 pentagonal end caps    (labels[5..6])
 *
 * Rolls ONLY on startRoll(). Idle = completely still.
 * settleOn(pronostico) eases to the correct face, then calls onComplete.
 */
class SchedellaDice {
  constructor(canvas, labels) {
    this.canvas = canvas;
    this.labels = labels; // must be length 7

    const W = canvas.clientWidth  || 300;
    const H = canvas.clientHeight || 300;

    this.R  = 1.05;  // prism radius
    this.HL = 0.80;  // half-length

    this.renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
    this.renderer.setPixelRatio(window.devicePixelRatio);
    this.renderer.setSize(W, H);

    this.scene = new THREE.Scene();
    this.camera = new THREE.PerspectiveCamera(36, W / H, 0.1, 100);
    this.camera.position.set(0, 2.2, 5.8);
    this.camera.lookAt(0, 0, 0);

    this.scene.add(new THREE.AmbientLight(0xffffff, 0.4));
    const key = new THREE.PointLight(0xfde68a, 6.0, 24);
    key.position.set(3, 7, 5);
    this.scene.add(key);
    const rim = new THREE.PointLight(0xf59e0b, 2.2, 18);
    rim.position.set(-5, -2, -3);
    this.scene.add(rim);
    const fill = new THREE.PointLight(0xffffff, 0.9, 14);
    fill.position.set(0, 5, -5);
    this.scene.add(fill);

    this._buildDie();

    this.rolling   = false;
    this.settling  = false;
    this.idle      = true;
    this.targetX   = (0.5 / 5) * Math.PI * 2;
    this.targetY   = 0;
    this.targetZ   = 0;
    this.onSettled = null;
    this.rollTime  = 0;

    this._animate();
  }

  // ── Textures ──────────────────────────────────────────────────────────────
  _makeTexture(label, active, round) {
    const S = 256;
    const cv = document.createElement('canvas');
    cv.width = cv.height = S;
    const ctx = cv.getContext('2d');

    if (round) {
      // Circular background for pentagon faces
      ctx.fillStyle = active ? '#1e1508' : '#0a0804';
      ctx.fillRect(0, 0, S, S);
      ctx.beginPath();
      ctx.arc(S / 2, S / 2, S / 2 - 4, 0, Math.PI * 2);
      ctx.fillStyle = active ? '#1e1508' : '#0d0a05';
      ctx.fill();
      ctx.strokeStyle = active ? '#f59e0b' : '#2a1d00';
      ctx.lineWidth = active ? 10 : 4;
      ctx.stroke();
    } else {
      ctx.fillStyle = active ? '#1e1508' : '#0a0804';
      ctx.fillRect(0, 0, S, S);
      const bw = active ? 12 : 5;
      ctx.strokeStyle = active ? '#f59e0b' : '#2a1d00';
      ctx.lineWidth = bw;
      ctx.strokeRect(bw / 2, bw / 2, S - bw, S - bw);
    }

    if (active) {
      const grad = ctx.createRadialGradient(S / 2, S / 2, 0, S / 2, S / 2, S * 0.5);
      grad.addColorStop(0, 'rgba(253,230,138,0.20)');
      grad.addColorStop(1, 'rgba(245,158,11,0)');
      ctx.fillStyle = grad;
      ctx.fillRect(0, 0, S, S);
    }

    ctx.fillStyle = active ? '#fde68a' : '#4a3820';
    const fs = label.length > 4 ? 44 : (label.length > 2 ? 58 : 80);
    ctx.font = `900 ${fs}px monospace`;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText(label.toUpperCase(), S / 2, S / 2);

    return new THREE.CanvasTexture(cv);
  }

  // ── Pentagon end-cap geometry ─────────────────────────────────────────────
  // x = position on X axis; normalDir = ±1 (outward normal)
  _makePentagonGeo(x, normalDir) {
    const N = 5;
    const R = this.R;
    const verts = [], norms = [], uvArr = [], idx = [];

    // Centre
    verts.push(x, 0, 0);
    norms.push(normalDir, 0, 0);
    uvArr.push(0.5, 0.5);

    for (let i = 0; i < N; i++) {
      const a = (i / N) * Math.PI * 2;
      verts.push(x, Math.sin(a) * R, Math.cos(a) * R);
      norms.push(normalDir, 0, 0);
      uvArr.push(0.5 + 0.45 * Math.sin(a), 0.5 - 0.45 * Math.cos(a));
    }
    for (let i = 0; i < N; i++) {
      const a = i + 1, b = (i + 1) % N + 1;
      normalDir > 0 ? idx.push(0, b, a) : idx.push(0, a, b);
    }

    const geo = new THREE.BufferGeometry();
    geo.setIndex(idx);
    geo.setAttribute('position', new THREE.Float32BufferAttribute(verts, 3));
    geo.setAttribute('normal',   new THREE.Float32BufferAttribute(norms, 3));
    geo.setAttribute('uv',       new THREE.Float32BufferAttribute(uvArr,  2));
    return geo;
  }

  // ── Build the full die ────────────────────────────────────────────────────
  _buildDie() {
    const N  = 5;
    const R  = this.R;
    const HL = this.HL;

    // 5 rectangular side faces
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
      uvs.push(0, 0,   1, 0,   1, 1,   0, 1);
      idx.push(b, b+1, b+2,   b, b+2, b+3);
    }
    const sideGeo = new THREE.BufferGeometry();
    sideGeo.setIndex(idx);
    sideGeo.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
    sideGeo.setAttribute('normal',   new THREE.Float32BufferAttribute(nor, 3));
    sideGeo.setAttribute('uv',       new THREE.Float32BufferAttribute(uvs, 2));
    for (let i = 0; i < N; i++) sideGeo.addGroup(i * 6, 6, i);

    // Materials: 5 side + 2 pentagon
    this.mats = this.labels.map((lbl, i) =>
      new THREE.MeshLambertMaterial({ map: this._makeTexture(lbl, false, i >= 5) })
    );

    const drum  = new THREE.Mesh(sideGeo, this.mats.slice(0, 5));
    const edges = new THREE.LineSegments(
      new THREE.EdgesGeometry(sideGeo, 1),
      new THREE.LineBasicMaterial({ color: 0x5a3d00 })
    );

    // Pentagon faces
    const topGeo  = this._makePentagonGeo(+HL + 0.001, +1);
    const botGeo  = this._makePentagonGeo(-HL - 0.001, -1);
    const topMesh = new THREE.Mesh(topGeo, this.mats[5]);
    const botMesh = new THREE.Mesh(botGeo, this.mats[6]);
    const eCol    = new THREE.LineBasicMaterial({ color: 0x5a3d00 });
    const topEdge = new THREE.LineSegments(new THREE.EdgesGeometry(topGeo), eCol);
    const botEdge = new THREE.LineSegments(new THREE.EdgesGeometry(botGeo), eCol);

    this.group = new THREE.Group();
    this.group.add(drum, edges, topMesh, botMesh, topEdge, botEdge);
    this.scene.add(this.group);

    // Start with side face 0 toward camera, perfectly still
    this.group.rotation.x = (0.5 / N) * Math.PI * 2;
    this.group.rotation.y = 0;
    this.group.rotation.z = 0;
  }

  // ── Public API ────────────────────────────────────────────────────────────
  startRoll() {
    this.rolling   = true;
    this.settling  = false;
    this.idle      = false;
    this.rollTime  = 0;
    this.onSettled = null;
    this.labels.forEach((lbl, i) => {
      this.mats[i].map.dispose();
      this.mats[i].map = this._makeTexture(lbl, false, i >= 5);
      this.mats[i].needsUpdate = true;
    });
  }

  settleOn(pronostico, onComplete) {
    const fi = this.labels.findIndex(l => l.toLowerCase() === pronostico.toLowerCase());
    if (fi === -1) { onComplete && onComplete(); return; }

    this.rolling   = false;
    this.settling  = true;
    this.onSettled = () => {
      this.mats[fi].map.dispose();
      this.mats[fi].map = this._makeTexture(this.labels[fi], true, fi >= 5);
      this.mats[fi].needsUpdate = true;
      onComplete && onComplete();
    };

    if (fi < 5) {
      // Side face: advance X to bring face fi toward camera, Y/Z → 0
      const aMid = (fi + 0.5) / 5 * Math.PI * 2;
      let target = aMid;
      const cur  = this.group.rotation.x;
      while (target <= cur)               target += Math.PI * 2;
      while (target - cur > Math.PI * 2) target -= Math.PI * 2;
      if (target - cur < Math.PI / 3)    target += Math.PI * 2;
      this.targetX = target;
      this.targetY = 0;
      this.targetZ = 0;
    } else if (fi === 5) {
      // Top pentagon (+X face): rotate Y = -π/2 so +X points toward camera
      this.targetX = this.group.rotation.x;
      this.targetY = -Math.PI / 2;
      this.targetZ = 0;
    } else {
      // Bottom pentagon (-X face): rotate Y = +π/2 so -X points toward camera
      this.targetX = this.group.rotation.x;
      this.targetY = Math.PI / 2;
      this.targetZ = 0;
    }
  }

  // ── Render loop ──────────────────────────────────────────────────────────
  _animate() {
    requestAnimationFrame(() => this._animate());

    if (this.rolling) {
      this.rollTime += 0.055;
      this.group.rotation.x += 0.14;
      this.group.rotation.y  = Math.sin(this.rollTime * 1.8) * 0.25;
      this.group.rotation.z  = Math.sin(this.rollTime * 1.3) * 0.15;
    } else if (this.settling) {
      const dX = this.targetX - this.group.rotation.x;
      const dY = this.targetY - this.group.rotation.y;
      const dZ = this.targetZ - this.group.rotation.z;
      if (Math.abs(dX) < 0.004 && Math.abs(dY) < 0.004 && Math.abs(dZ) < 0.004) {
        this.group.rotation.x = this.targetX;
        this.group.rotation.y = this.targetY;
        this.group.rotation.z = this.targetZ;
        this.settling = false;
        this.idle     = true;
        const cb = this.onSettled;
        this.onSettled = null;
        cb && cb();
      } else {
        this.group.rotation.x += dX * 0.08;
        this.group.rotation.y += dY * 0.08;
        this.group.rotation.z += dZ * 0.08;
      }
    }
    // idle: completely still — no rotation

    this.renderer.render(this.scene, this.camera);
  }
}
