/* theme.js — thème sombre / clair / automatique, partagé par l'accueil et le tableau de bord.
   À charger dans le <head> des DEUX pages, AVANT la feuille de style si possible :
   la classe est posée sur <html> dès le départ, donc pas de flash sombre quand on a choisi le clair. */
(function () {
  var CLE = 'quant_theme';
  var racine = document.documentElement;
  var systeme = window.matchMedia ? window.matchMedia('(prefers-color-scheme: light)') : null;

  function preference() {
    try { var v = localStorage.getItem(CLE); return v === 'light' || v === 'auto' ? v : 'dark'; } catch (e) { return 'dark'; }
  }
  function resolu(pref) {                               // 'auto' suit le réglage du système
    if (pref === 'auto') return systeme && systeme.matches ? 'light' : 'dark';
    return pref;
  }

  function appliquer() {
    var t = resolu(preference());
    racine.classList.toggle('light-mode', t === 'light');
    racine.style.colorScheme = t;                       // champs, barres de défilement, <dialog> natifs
    var icone = document.getElementById('themeIcon'), texte = document.getElementById('themeText');
    if (icone) icone.className = 'fa-solid ' + (t === 'light' ? 'fa-sun' : 'fa-moon');
    if (texte) texte.textContent = t === 'light' ? 'Clair' : 'Sombre';
    // les graphiques Plotly vivent dans des iframes : on leur envoie le thème
    document.querySelectorAll('iframe').forEach(function (f) {
      try { f.contentWindow.postMessage({ type: 'quant-theme', theme: t }, location.origin); } catch (e) { /* iframe pas prête */ }
    });
    document.dispatchEvent(new CustomEvent('quant-theme', { detail: t }));
  }

  function definir(pref) {
    try { localStorage.setItem(CLE, pref); } catch (e) { /* stockage indisponible */ }
    appliquer();
  }
  function basculer() { definir(resolu(preference()) === 'light' ? 'dark' : 'light'); }   // le bouton choisit un thème explicite

  // get() : thème réellement affiché (utilisé pour les iframes) ; pref() : choix enregistré (dark, light ou auto)
  window.Theme = { get: function () { return resolu(preference()); }, pref: preference, set: definir, basculer: basculer };

  if (systeme && systeme.addEventListener) systeme.addEventListener('change', function () { if (preference() === 'auto') appliquer(); });
  appliquer();                                          // tout de suite (le bouton n'existe pas encore)
  document.addEventListener('DOMContentLoaded', function () {
    appliquer();                                        // met à jour icône et texte du bouton
    var b = document.getElementById('themeToggleBtn');
    if (b) b.addEventListener('click', basculer);
  });
})();
