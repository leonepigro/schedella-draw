class SchedellaDice {
  constructor(canvas, faceLabels) { this.canvas = canvas; this.labels = faceLabels; }
  startRoll() {}
  settleOn(pronostico, onComplete) { if (onComplete) onComplete(); }
}
