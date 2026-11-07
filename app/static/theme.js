/* theme.js — thème sombre / clair partagé par l'accueil et le tableau de bord.
   À charger dans le <head> des DEUX pages, AVANT la feuille de style si possible :
   la classe est posée sur <html> dès le départ, donc pas de flash sombre quand on a choisi le clair. */
(function () {
  var CLE = 'quant_theme';
  var racine = document.documentElement;

  function lire() {
    try { return localStorage.getItem(CLE) === 'light' ? 'light' : 'dark'; } catch (e) { return 'dark'; }
  }

  function appliquer(t) {
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

  function basculer() {
    var suivant = lire() === 'light' ? 'dark' : 'light';
    try { localStorage.setItem(CLE, suivant); } catch (e) { /* stockage indisponible */ }
    appliquer(suivant);
  }

  window.Theme = { get: lire, set: function (t) { try { localStorage.setItem(CLE, t); } catch (e) {} appliquer(t); }, basculer: basculer };

  appliquer(lire());                                    // tout de suite (le bouton n'existe pas encore)
  document.addEventListener('DOMContentLoaded', function () {
    appliquer(lire());                                  // met à jour icône et texte du bouton
    var b = document.getElementById('themeToggleBtn');
    if (b) b.addEventListener('click', basculer);
  });
})();
