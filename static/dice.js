class SchedellaDice {
  constructor(canvas, faceLabels) {
    this.canvas = canvas;
    this.labels = faceLabels.slice(0, 6); // max 6 faces (cube)
    this.targetFace = 0;
    this.isRolling = false;
    this._onSettled = null;
    this.rollTarget = null;
    this.rollVelocity = null;
    this._init();
  }

  _init() {
    const w = this.canvas.clientWidth || 300;
    const h = this.canvas.clientHeight || 300;

    this.renderer = new THREE.WebGLRenderer({ canvas: this.canvas, antialias: true, alpha: true });
    this.renderer.setSize(w, h);
    this.renderer.setPixelRatio(window.devicePixelRatio);

    this.scene = new THREE.Scene();
    this.camera = new THREE.PerspectiveCamera(45, w / h, 0.1, 100);
    this.camera.position.set(0, 0, 3.5);

    // Lighting
    this.scene.add(new THREE.AmbientLight(0xffffff, 0.6));
    const point = new THREE.PointLight(0xf59e0b, 1.5, 10);
    point.position.set(2, 3, 4);
    this.scene.add(point);

    // Build cube with face textures
    const materials = this.labels.map((label, i) =>
      new THREE.MeshStandardMaterial({
        map: this._makeTexture(label, i === 0),
        roughness: 0.3,
        metalness: 0.7,
      })
    );
    while (materials.length < 6) {
      materials.push(new THREE.MeshStandardMaterial({ color: 0x2d2410 }));
    }

    this.cube = new THREE.Mesh(new THREE.BoxGeometry(1.5, 1.5, 1.5), materials);
    this.scene.add(this.cube);

    // Face normal vectors for each BoxGeometry face (+x,-x,+y,-y,+z,-z)
    this.faceNormals = [
      new THREE.Vector3(1, 0, 0),
      new THREE.Vector3(-1, 0, 0),
      new THREE.Vector3(0, 1, 0),
      new THREE.Vector3(0, -1, 0),
      new THREE.Vector3(0, 0, 1),
      new THREE.Vector3(0, 0, -1),
    ];

    this.rollVelocity = new THREE.Vector3();
    this.rollTarget = null;
    this._animate();
  }

  _makeTexture(label, active) {
    const size = 256;
    const c = document.createElement('canvas');
    c.width = c.height = size;
    const ctx = c.getContext('2d');

    ctx.fillStyle = active ? '#1a160d' : '#12100a';
    ctx.fillRect(0, 0, size, size);

    ctx.strokeStyle = active ? '#f59e0b' : '#2d2410';
    ctx.lineWidth = 8;
    ctx.strokeRect(4, 4, size - 8, size - 8);

    ctx.fillStyle = active ? '#fde68a' : '#92400e';
    ctx.font = `bold ${label.length > 4 ? 48 : 64}px system-ui, sans-serif`;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText(label.toUpperCase(), size / 2, size / 2);

    return new THREE.CanvasTexture(c);
  }

  _updateFaceTextures(activePron) {
    this.labels.forEach((label, i) => {
      const mat = this.cube.material[i];
      if (mat.map) mat.map.dispose();
      mat.map = this._makeTexture(label, label.toLowerCase() === activePron);
      mat.needsUpdate = true;
    });
  }

  _animate() {
    requestAnimationFrame(() => this._animate());
    if (this.isRolling) {
      this.cube.rotation.x += this.rollVelocity.x;
      this.cube.rotation.y += this.rollVelocity.y;
      this.cube.rotation.z += this.rollVelocity.z;
      this.rollVelocity.multiplyScalar(0.97);
    } else if (this.rollTarget) {
      this.cube.quaternion.slerp(this.rollTarget, 0.08);
      if (this.cube.quaternion.angleTo(this.rollTarget) < 0.01) {
        this.cube.quaternion.copy(this.rollTarget);
        this.rollTarget = null;
        if (this._onSettled) { this._onSettled(); this._onSettled = null; }
      }
    } else {
      this.cube.rotation.y += 0.005;
    }
    this.renderer.render(this.scene, this.camera);
  }

  startRoll() {
    this.isRolling = true;
    this.rollTarget = null;
    this.rollVelocity.set(
      (Math.random() - 0.5) * 0.4,
      (Math.random() - 0.5) * 0.4,
      (Math.random() - 0.5) * 0.2
    );
    setTimeout(() => { this.isRolling = false; }, 1800);
  }

  settleOn(pronostico, onComplete) {
    const faceIdx = this.labels.findIndex(l => l.toLowerCase() === pronostico.toLowerCase());
    if (faceIdx === -1) {
      if (onComplete) onComplete();
      return;
    }
    this._updateFaceTextures(pronostico);
    const target = new THREE.Vector3(0, 0, -1);
    const faceDir = this.faceNormals[faceIdx].clone();
    const q = new THREE.Quaternion().setFromUnitVectors(faceDir, target);
    this.rollTarget = q;
    this._onSettled = onComplete;
    setTimeout(() => { this.isRolling = false; }, 100);
  }
}
