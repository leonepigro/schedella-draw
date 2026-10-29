// Popup di avanzamento riusabile. Dati renderizzati solo via textContent.
(function () {
  var timer = null;
  var startedAt = 0;
  var steps = [];
  var indeterminate = false;
  var failCallbacks = [];

  function $(id) { return document.getElementById(id); }

  function pad(n) { return (n < 10 ? "0" : "") + n; }

  function tick() {
    var s = Math.floor((Date.now() - startedAt) / 1000);
    $("progress-elapsed").textContent = pad(Math.floor(s / 60)) + ":" + pad(s % 60);
  }

  function setState(i, state) {
    var li = $("progress-steps").children[i];
    if (!li) return;
    li.className = state === "done" ? "text-[#fde68a]" : state === "active" ? "text-[#f59e0b]" : "muted";
    li.firstChild.textContent = state === "done" ? "✓" : state === "active" ? "•" : "·";
  }

  function refreshBar() {
    var done = 0;
    var kids = $("progress-steps").children;
    for (var i = 0; i < kids.length; i++) if (kids[i].firstChild.textContent === "✓") done++;
    $("progress-bar").style.width = (steps.length ? Math.round(100 * done / steps.length) : 0) + "%";
  }

  function enableButtons() {
    document.querySelectorAll("button[type=submit]").forEach(function (b) { b.disabled = false; });
  }

  var Progress = {
    _busy: false,

    open: function (title, stepList, opts) {
      indeterminate = !!(opts && opts.indeterminate);
      steps = stepList || [];
      $("progress-title").textContent = title;
      var ul = $("progress-steps");
      ul.textContent = "";
      steps.forEach(function (label, i) {
        var li = document.createElement("li");
        var icon = document.createElement("span");
        icon.className = "inline-block w-5 text-center";
        var text = document.createElement("span");
        text.textContent = label;
        li.appendChild(icon);
        li.appendChild(text);
        ul.appendChild(li);
        // indeterminate: elenco senza spunte
        setState(i, !indeterminate && i === 0 ? "active" : "pending");
      });
      $("progress-bar-wrap").classList.toggle("hidden", indeterminate);
      $("progress-spinner").classList.remove("hidden");
      $("progress-error").classList.add("hidden");
      $("progress-bar").style.width = "0%";
      startedAt = Date.now();
      tick();
      clearInterval(timer);
      timer = setInterval(tick, 1000);
      var m = $("progress-modal");
      m.classList.remove("hidden");
      m.classList.add("flex");
    },

    done: function (i) {
      if (indeterminate) return;
      setState(i, "done");
      setState(i + 1, "active");
      refreshBar();
    },

    fail: function (message) {
      clearInterval(timer);
      $("progress-spinner").classList.add("hidden");
      $("progress-error-msg").textContent = message;
      $("progress-error").classList.remove("hidden");
      Progress._busy = false;
      enableButtons();
      failCallbacks.forEach(function (cb) { cb(); });
    },

    close: function () {
      clearInterval(timer);
      var m = $("progress-modal");
      m.classList.add("hidden");
      m.classList.remove("flex");
    },

    onFail: function (cb) { failCallbacks.push(cb); },

    uploadForm: function (form) {
      if (window.event) window.event.preventDefault();
      if (Progress._busy) return false;
      Progress._busy = true;
      document.querySelectorAll("button[type=submit]").forEach(function (b) { b.disabled = true; });
      Progress.open("Preparo la schedella…",
        ["Carico il file", "Leggo le partite dall'Excel", "Apro la configurazione"]);
      fetch(form.action, {
        method: "POST",
        body: new FormData(form),
        headers: { accept: "application/json" }
      }).then(function (r) {
        if (!r.ok) throw new Error("HTTP " + r.status);
        return r.json();
      }).then(function (json) {
        if (!json || !json.redirect) throw new Error("redirect mancante");
        Progress.done(0);
        location.href = json.redirect;
      }).catch(function () {
        Progress.fail("Caricamento non riuscito. Controlla il file e riprova.");
      });
      return false;
    }
  };

  document.addEventListener("click", function (e) {
    if (e.target && e.target.id === "progress-close") Progress.close();
  });
  window.addEventListener("pageshow", function (e) {
    if (e.persisted) { Progress.close(); Progress._busy = false; enableButtons(); }
  });
  window.Progress = Progress;
})();
