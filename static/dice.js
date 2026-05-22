/*
 * SchedellaDice — pentagonal prism, Y-axis vertical
 *
 * faces 0–4 : 5 rectangular side faces  → labels[0..4]
 * face  5   : top pentagon (+Y)          → labels[5]
 * face  6   : bottom pentagon (–Y)       → labels[6]
 *
 * Rolling uses quaternion + random axis that changes every ~25 frames
 * → every roll looks different (true 3D tumble, not barrel spin).
 * Settling uses quaternion SLERP toward the exact target face orientation.
 * Idle = completely still.
 */
class SchedellaDice {
  constructor(canvas, labels, options = {}) {
    this.canvas = canvas;
    this.labels = labels;
    this.colors = {
      bg:       options.bg       || '#0a0804',
      bgActive: options.bgActive || '#1e1508',
      accent:   options.accent   || '#f59e0b',
      accentDim:options.accentDim|| '#2d1e00',
      text:     options.text     || '#fde68a',
      textDim:  options.textDim  || '#4d3d1c',
      edge:     options.edge     || '#7a5500',
      specular: options.specular || '#3a2800',
      keyLight: options.keyLight || 0xfde68a,
      rimLight: options.rimLight || 0xf59e0b,
    };

    const W = canvas.clientWidth  || 300;
    const H = canvas.clientHeight || 300;

    this.R  = 1.0;
    this.HL = 0.88;

    this.renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
    this.renderer.setPixelRatio(window.devicePixelRatio);
    this.renderer.setSize(W, H);

    this.scene  = new THREE.Scene();
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

    this.rolling     = false;
    this.settling    = false;
    this.idle        = true;
    this.targetQuat  = new THREE.Quaternion();
    this.onSettled   = null;
    this._rollAxis   = new THREE.Vector3(0, 1, 0);
    this._rollSpeed  = 0.12;
    this._axisTimer  = 0;

    // Face 0 toward camera: rotation.y = –aMid(0)
    const startEuler = new THREE.Euler(0, -(0.5 / 5) * Math.PI * 2, 0, 'XYZ');
    this.group.quaternion.setFromEuler(startEuler);

    this._animate();
  }

  // ── Texture ───────────────────────────────────────────────────────────────
  _makeTexture(label, active, isPentagon) {
    const S = 256;
    const cv = document.createElement('canvas');
    cv.width = cv.height = S;
    const ctx = cv.getContext('2d');
    const C   = this.colors;

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
      normalDir > 0 ? idx.push(0, a, b) : idx.push(0, b, a);
    }
    const geo = new THREE.BufferGeometry();
    geo.setIndex(idx);
    geo.setAttribute('position', new THREE.Float32BufferAttribute(verts, 3));
    geo.setAttribute('normal',   new THREE.Float32BufferAttribute(norms, 3));
    geo.setAttribute('uv',       new THREE.Float32BufferAttribute(uvs,   2));
    return geo;
  }

  // ── Build the die ─────────────────────────────────────────────────────────
  _buildDie() {
    const N = 5, R = this.R, HL = this.HL;
    const pos = [], nor = [], uvs = [], idx = [];

    for (let i = 0; i < N; i++) {
      const a0   = (i       / N) * Math.PI * 2;
      const a1   = ((i + 1) / N) * Math.PI * 2;
      const aMid = (a0 + a1) / 2;
      const x0 = Math.sin(a0) * R, z0 = Math.cos(a0) * R;
      const x1 = Math.sin(a1) * R, z1 = Math.cos(a1) * R;
      const nx = Math.sin(aMid), nz = Math.cos(aMid);
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
        map:       this._makeTexture(lbl, false, i >= 5),
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

  // ── Random roll axis ──────────────────────────────────────────────────────
  _pickAxis() {
    this._rollAxis = new THREE.Vector3(
      Math.random() * 2 - 1,
      Math.random() * 2 - 1,
      Math.random() * 2 - 1
    ).normalize();
    this._rollSpeed  = 0.09 + Math.random() * 0.07;
    this._axisTimer  = 0;
    this._axisLife   = 18 + Math.floor(Math.random() * 22); // 18–40 frames
  }

  // ── Theme change (live) ───────────────────────────────────────────────────
  setColors(options) {
    Object.assign(this.colors, options);
    this.group.children.forEach(c => {
      if (c.isLineSegments) c.material.color.set(this.colors.edge);
    });
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
    this.onSettled = null;
    this._pickAxis();
    this.labels.forEach((lbl, i) => {
      this.mats[i].map.dispose();
      this.mats[i].map = this._makeTexture(lbl, false, i >= 5);
      this.mats[i].needsUpdate = true;
    });
  }

  settleOn(pronostico, onComplete) {
    const fi = this.labels.findIndex(l => l.toLowerCase() === pronostico.toLowerCase());
    if (fi === -1) { onComplete && onComplete(); return; }

    // Compute target quaternion for face fi facing +Z (camera)
    let euler;
    if (fi < 5) {
      // Side face fi: rotation.y = –aMid so face normal aligns with +Z
      euler = new THREE.Euler(0, -(fi + 0.5) / 5 * Math.PI * 2, 0, 'XYZ');
    } else if (fi === 5) {
      // Top pentagon: tilt X = +π/2 so +Y normal faces +Z
      euler = new THREE.Euler(Math.PI / 2, 0, 0, 'XYZ');
    } else {
      // Bottom pentagon: tilt X = –π/2 so –Y normal faces +Z
      euler = new THREE.Euler(-Math.PI / 2, 0, 0, 'XYZ');
    }
    this.targetQuat = new THREE.Quaternion().setFromEuler(euler);

    this.rolling   = false;
    this.settling  = true;
    this.onSettled = () => {
      this.mats[fi].map.dispose();
      this.mats[fi].map = this._makeTexture(this.labels[fi], true, fi >= 5);
      this.mats[fi].needsUpdate = true;
      onComplete && onComplete();
    };
  }

  // ── Render loop ───────────────────────────────────────────────────────────
  _animate() {
    requestAnimationFrame(() => this._animate());

    if (this.rolling) {
      // Change tumble axis every _axisLife frames → visually different each roll
      this._axisTimer++;
      if (this._axisTimer >= this._axisLife) this._pickAxis();

      const qDelta = new THREE.Quaternion()
        .setFromAxisAngle(this._rollAxis, this._rollSpeed);
      this.group.quaternion.multiply(qDelta);

    } else if (this.settling) {
      const angle = this.group.quaternion.angleTo(this.targetQuat);
      if (angle < 0.008) {
        this.group.quaternion.copy(this.targetQuat);
        this.settling = false;
        this.idle     = true;
        const cb = this.onSettled;
        this.onSettled = null;
        cb && cb();
      } else {
        // Ease-out: factor proportional to angle so it decelerates naturally
        const t = Math.min(0.12, angle * 0.055);
        this.group.quaternion.slerp(this.targetQuat, t);
      }
    }
    // idle: completely still

    this.renderer.render(this.scene, this.camera);
  }
}
