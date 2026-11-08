/* reglages.js — réglages de l'utilisateur, enregistrés dans le navigateur (localStorage).
   À charger AVANT dashboard.js (qui les envoie au serveur en ouvrant le flux d'analyse). */
(function () {
  var CLE = 'quant_reglages_v1';
  var DEFAUT = {
    affichage: { densite: 'normale', texte: 100, lignes: 100, daltonien: false, masquees: [], resume: true, filtres: true },
    score: { poids: { valo: 30, qual: 25, crois: 15, risq: 15, mom: 15 }, achat_fort: 90, achat: 75, vente: 20,
             couverture_min: 50, poids_secteur: 60, exclure_fin: false },
    valo: { erp: 5.5, g_term: 2.5, rf: null, ecart_g: 3, ecart_ke: 1 },
    analyse: { concurrence: 6 }
  };
  var copie = function (o) { return JSON.parse(JSON.stringify(o)); };
  var nombreOk = function (x) { return typeof x === 'number' && isFinite(x); };

  // fusionne `extra` dans `base` en ne gardant que les clés connues, avec le bon type (un fichier abîmé ne casse rien)
  function fusion(base, extra) {
    if (!extra || typeof extra !== 'object') return base;
    Object.keys(base).forEach(function (k) {
      if (!(k in extra)) return;
      var b = base[k], e = extra[k];
      if (Array.isArray(b)) { if (Array.isArray(e)) base[k] = e.filter(Number.isInteger); }
      else if (b === null) { base[k] = nombreOk(e) ? e : null; }
      else if (typeof b === 'object') { fusion(b, e); }
      else if (typeof b === 'number') { if (nombreOk(e)) base[k] = e; }
      else if (typeof e === typeof b) { base[k] = e; }
    });
    return base;
  }

  // réglages purement visuels : appliqués dès le chargement, sans attendre le tableau (pas de flash)
  function appliquerVisuel() {
    if (typeof document === 'undefined') return;
    var A = courant.affichage, r = document.documentElement;
    r.dataset.dens = A.densite;
    r.style.fontSize = (15 * A.texte / 100) + 'px';
    r.classList.toggle('daltonien', A.daltonien);
  }

  var courant;
  function lire() {
    try { return fusion(copie(DEFAUT), JSON.parse(localStorage.getItem(CLE) || '{}')); } catch (e) { return copie(DEFAUT); }
  }
  function sauver() { try { localStorage.setItem(CLE, JSON.stringify(courant)); } catch (e) { /* stockage indisponible */ } }
  courant = lire();

  appliquerVisuel();

  var ecouteurs = [];
  function cible(chemin) {
    var p = chemin.split('.'), o = courant;
    for (var i = 0; i < p.length - 1; i++) o = o[p[i]];
    return [o, p[p.length - 1]];
  }
  function valeurDe(chemin, source) { var o = source; chemin.split('.').forEach(function (k) { o = o[k]; }); return o; }
  function feuilles(o, prefixe, sortie) {
    Object.keys(o).forEach(function (k) {
      var v = o[k], c = prefixe ? prefixe + '.' + k : k;
      if (v && typeof v === 'object' && !Array.isArray(v)) feuilles(v, c, sortie); else sortie.push(c);
    });
    return sortie;
  }

  window.Reglages = {
    defaut: DEFAUT,
    appliquerVisuel: appliquerVisuel,
    get: function () { return courant; },
    lire: function (chemin) { return valeurDe(chemin, courant); },
    set: function (chemin, valeur) { var c = cible(chemin); c[0][c[1]] = valeur; sauver(); appliquerVisuel(); ecouteurs.forEach(function (f) { f(chemin); }); },
    onChange: function (f) { ecouteurs.push(f); },
    // réglages envoyés au serveur (flux d'analyse, recalcul des scores)
    serveur: function () {
      var S = courant.score;
      return { poids: S.poids, achat_fort: S.achat_fort, achat: S.achat, vente: S.vente, couverture_min: S.couverture_min,
               poids_secteur: S.poids_secteur, exclure_fin: S.exclure_fin, hyp: courant.valo, concurrence: courant.analyse.concurrence };
    },
    // ce qui exige de relancer l'analyse : si cela change, on propose de recharger
    relance: function () { return JSON.stringify({ valo: courant.valo, concurrence: courant.analyse.concurrence }); },
    modifies: function () {
      return feuilles(DEFAUT, '', []).filter(function (c) { return JSON.stringify(valeurDe(c, courant)) !== JSON.stringify(valeurDe(c, DEFAUT)); }).length;
    },
    reinitialiser: function (zone) {
      if (zone) courant[zone] = copie(DEFAUT[zone]); else courant = copie(DEFAUT);
      sauver(); appliquerVisuel(); ecouteurs.forEach(function (f) { f(zone || '*'); });
    },
    exporter: function () { return JSON.stringify(courant, null, 2); },
    importer: function (texte) {
      try { var brut = JSON.parse(texte); if (!brut || typeof brut !== 'object') return false; courant = fusion(copie(DEFAUT), brut); sauver(); appliquerVisuel(); return true; }
      catch (e) { return false; }
    }
  };
})();
