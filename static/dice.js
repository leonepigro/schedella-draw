/*
 * SchedellaDice — pentagonal prism, Y-axis vertical (die standing upright)
 *
 * faces 0–4 : 5 rectangular side faces  → labels[0..4]
 * face  5   : top pentagon (+Y)          → labels[5]
 * face  6   : bottom pentagon (–Y)       → labels[6]
 *
 * IDLE  : completely still
 * ROLL  : starts only on startRoll()
 * SETTLE: eases to the exact face, highlights it, then fires onComplete
 */
class SchedellaDice {
  constructor(canvas, labels, options = {}) {
    this.canvas = canvas;
    this.labels = labels;
    this.colors = {
      bg:          options.bg          || '#0a0804',
      bgActive:    options.bgActive    || '#1e1508',
      accent:      options.accent      || '#f59e0b',
      accentDim:   options.accentDim   || '#2d1e00',
      text:        options.text        || '#fde68a',
      textDim:     options.textDim     || '#4d3d1c',
      edge:        options.edge        || '#7a5500',
      specular:    options.specular    || '#3a2800',
      keyLight:    options.keyLight    || 0xfde68a,
      rimLight:    options.rimLight    || 0xf59e0b,
    };

    const W = canvas.clientWidth  || 300;
    const H = canvas.clientHeight || 300;

    this.R  = 1.0;   // prism radius
    this.HL = 0.88;  // half-height

    this.renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
    this.renderer.setPixelRatio(window.devicePixelRatio);
    this.renderer.setSize(W, H);

    this.scene = new THREE.Scene();
    this.camera = new THREE.PerspectiveCamera(36, W / H, 0.1, 100);
    this.camera.position.set(0, 2.0, 5.5);
    this.camera.lookAt(0, 0, 0);

    this.scene.add(new THREE.AmbientLight(0xffffff, 0.32));

    const key = new THREE.PointLight(this.colors.keyLight, 7.0, 26);
    key.position.set(4, 9, 6);
    this.scene.add(key);

    const rim = new THREE.PointLight(this.colors.rimLight, 2.5, 18);
    rim.position.set(-5, -3, -3);
    this.scene.add(rim);

    const top = new THREE.PointLight(0xffffff, 1.8, 14);
    top.position.set(0, 9, 1);
    this.scene.add(top);

    this._buildDie();

    // Start face 0 facing camera — rotation.y = –aMid(0)
    const startY = -(0.5 / 5) * Math.PI * 2;
    this.group.rotation.y = startY;

    this.rolling   = false;
    this.settling  = false;
    this.idle      = true;
    this.targetX   = 0;
    this.targetY   = startY;
    this.targetZ   = 0;
    this.onSettled = null;
    this.rollTime  = 0;

    this._animate();
  }

  // ── Texture ───────────────────────────────────────────────────────────────
  _makeTexture(label, active, isPentagon) {
    const S = 256;
    const cv = document.createElement('canvas');
    cv.width = cv.height = S;
    const ctx = cv.getContext('2d');

    const C = this.colors;
    ctx.fillStyle = C.bg;
    ctx.fillRect(0, 0, S, S);

    if (isPentagon) {
      ctx.beginPath();
      ctx.arc(S / 2, S / 2, S / 2 - 5, 0, Math.PI * 2);
      ctx.fillStyle = active ? C.bgActive : C.bg;
      ctx.fill();
      ctx.strokeStyle = active ? C.accent : C.accentDim;
      ctx.lineWidth = active ? 9 : 4;
      ctx.stroke();
    } else {
      const bw = active ? 11 : 5;
      ctx.strokeStyle = active ? C.accent : C.accentDim;
      ctx.lineWidth = bw;
      ctx.strokeRect(bw / 2, bw / 2, S - bw, S - bw);
    }

    if (active) {
      const g = ctx.createRadialGradient(S / 2, S / 2, 0, S / 2, S / 2, S * 0.48);
      g.addColorStop(0, C.text + '38');
      g.addColorStop(1, C.accent + '00');
      ctx.fillStyle = g;
      ctx.fillRect(0, 0, S, S);
    }

    ctx.fillStyle = active ? C.text : C.textDim;
    const fs = label.length > 4 ? 44 : label.length > 2 ? 58 : 82;
    ctx.font = `900 ${fs}px monospace`;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText(label.toUpperCase(), S / 2, S / 2);

    return new THREE.CanvasTexture(cv);
  }

  // ── Pentagon geometry (cap perpendicular to Y) ────────────────────────────
  _makePentagonGeo(y, normalDir) {
    const N = 5, R = this.R;
    const verts = [], norms = [], uvs = [], idx = [];

    verts.push(0, y, 0);
    norms.push(0, normalDir, 0);
    uvs.push(0.5, 0.5);

    for (let i = 0; i < N; i++) {
      const a = (i / N) * Math.PI * 2;
      verts.push(Math.sin(a) * R, y, Math.cos(a) * R);
      norms.push(0, normalDir, 0);
      uvs.push(0.5 + 0.44 * Math.sin(a), 0.5 - 0.44 * Math.cos(a));
    }
    for (let i = 0; i < N; i++) {
      const a = i + 1, b = (i + 1) % N + 1;
      // CCW from outside: normalDir>0 → (0,a,b), normalDir<0 → (0,b,a)
      normalDir > 0 ? idx.push(0, a, b) : idx.push(0, b, a);
    }

    const geo = new THREE.BufferGeometry();
    geo.setIndex(idx);
    geo.setAttribute('position', new THREE.Float32BufferAttribute(verts, 3));
    geo.setAttribute('normal',   new THREE.Float32BufferAttribute(norms, 3));
    geo.setAttribute('uv',       new THREE.Float32BufferAttribute(uvs,   2));
    return geo;
  }

  // ── Build full die ────────────────────────────────────────────────────────
  _buildDie() {
    const N = 5, R = this.R, HL = this.HL;
    const pos = [], nor = [], uvs = [], idx = [];

    for (let i = 0; i < N; i++) {
      const a0   = (i       / N) * Math.PI * 2;
      const a1   = ((i + 1) / N) * Math.PI * 2;
      const aMid = (a0 + a1) / 2;

      const x0 = Math.sin(a0) * R, z0 = Math.cos(a0) * R;
      const x1 = Math.sin(a1) * R, z1 = Math.cos(a1) * R;
      const nx  = Math.sin(aMid),   nz = Math.cos(aMid);

      const b = pos.length / 3;
      pos.push(x0, -HL, z0,   x1, -HL, z1,   x1, HL, z1,   x0, HL, z0);
      nor.push(nx,  0, nz,    nx,  0, nz,    nx,  0, nz,    nx,  0, nz);
      uvs.push(0, 0,   1, 0,   1, 1,   0, 1);
      idx.push(b, b+1, b+2,   b, b+2, b+3);
    }

    const sideGeo = new THREE.BufferGeometry();
    sideGeo.setIndex(idx);
    sideGeo.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
    sideGeo.setAttribute('normal',   new THREE.Float32BufferAttribute(nor, 3));
    sideGeo.setAttribute('uv',       new THREE.Float32BufferAttribute(uvs, 2));
    for (let i = 0; i < N; i++) sideGeo.addGroup(i * 6, 6, i);

    this.mats = this.labels.map((lbl, i) =>
      new THREE.MeshPhongMaterial({
        map:      this._makeTexture(lbl, false, i >= 5),
        shininess: 55,
        specular:  new THREE.Color(this.colors.specular),
      })
    );

    const drum  = new THREE.Mesh(sideGeo, this.mats.slice(0, 5));
    const edges = new THREE.LineSegments(
      new THREE.EdgesGeometry(sideGeo, 1),
      new THREE.LineBasicMaterial({ color: this.colors.edge })
    );

    const topGeo  = this._makePentagonGeo(+HL + 0.002, +1);
    const botGeo  = this._makePentagonGeo(-HL - 0.002, -1);
    const topMesh = new THREE.Mesh(topGeo, this.mats[5]);
    const botMesh = new THREE.Mesh(botGeo, this.mats[6]);

    const eM = new THREE.LineBasicMaterial({ color: this.colors.edge });
    const topEdge = new THREE.LineSegments(new THREE.EdgesGeometry(topGeo), eM);
    const botEdge = new THREE.LineSegments(new THREE.EdgesGeometry(botGeo), eM);

    this.group = new THREE.Group();
    this.group.add(drum, edges, topMesh, botMesh, topEdge, botEdge);
    this.scene.add(this.group);
  }

  // ── Theme change (live, no rebuild) ──────────────────────────────────────
  setColors(options) {
    Object.assign(this.colors, options);
    // Rebuild edges color
    this.group.children.forEach(c => {
      if (c.isLineSegments && c.material) {
        c.material.color.set(this.colors.edge);
      }
    });
    // Rebuild all face textures (keep active state)
    this.labels.forEach((lbl, i) => {
      this.mats[i].map.dispose();
      this.mats[i].map = this._makeTexture(lbl, false, i >= 5);
      this.mats[i].needsUpdate = true;
      this.mats[i].specular.set(this.colors.specular);
    });
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
      // Side face fi: advance Y until face fi faces camera (+Z)
      // Face i faces +Z when rotation.y = –aMid + k*2π
      const aMid   = (fi + 0.5) / 5 * Math.PI * 2;
      let   target = -aMid;
      const cur    = this.group.rotation.y;
      while (target <= cur)               target += Math.PI * 2;
      while (target - cur > Math.PI * 2) target -= Math.PI * 2;
      if   (target - cur < Math.PI / 3)  target += Math.PI * 2;
      this.targetX = 0;
      this.targetY = target;
      this.targetZ = 0;
    } else {
      // Pentagon cap: tilt X = ±π/2, park Y at nearest 2π multiple
      // Top (+Y, fi=5): rotation.x = +π/2  → top faces camera
      // Bot (–Y, fi=6): rotation.x = –π/2  → bottom faces camera
      const nearest2pi = Math.round(this.group.rotation.y / (Math.PI * 2)) * Math.PI * 2;
      this.targetX = fi === 5 ? Math.PI / 2 : -Math.PI / 2;
      this.targetY = nearest2pi;
      this.targetZ = 0;
    }
  }

  // ── Render loop ───────────────────────────────────────────────────────────
  _animate() {
    requestAnimationFrame(() => this._animate());

    if (this.rolling) {
      this.rollTime += 0.055;
      this.group.rotation.y += 0.14;
      // X/Z wobble → looks like a tumbling die, not a lathe
      this.group.rotation.x = Math.sin(this.rollTime * 2.1) * 0.32;
      this.group.rotation.z = Math.sin(this.rollTime * 1.5) * 0.20;

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
        this.group.rotation.x += dX * 0.085;
        this.group.rotation.y += dY * 0.085;
        this.group.rotation.z += dZ * 0.085;
      }

    }
    // idle: completely still — no rotation at all

    this.renderer.render(this.scene, this.camera);
  }
}
